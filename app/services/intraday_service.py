"""Service métier pour le module Daily/Intraday (§10 du cahier des charges).

C'est ici qu'Erlang C (app/services/erlang_service.py) s'applique enfin
intervalle par intervalle — contrairement au LTF/STF qui utilisent une
formule agrégée mensuelle/hebdomadaire (kpi_service.required_hc_aggregate),
la fenêtre de 30 minutes est le niveau de granularité où la théorie des
files d'attente a un sens réel : le trafic à l'intérieur d'un intervalle
court est traité comme un flux stationnaire, ce qui n'est plus une
approximation raisonnable à l'échelle d'un mois.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as DateType
from datetime import time
from typing import Optional

from sqlmodel import Session, select

from app.models.intraday import IntervalForecast
from app.models.skill import Skill
from app.schemas.intraday import GenerateIntradayInput, IntervalUpdateInput
from app.services import channel_service, client_stf_service, kpi_service
from app.services.workforce_service import seasonal_operating_window, validate_timezone_name
from app.services.erlang_service import (
    apply_shrinkage,
    average_speed_of_answer_erlang_c,
    find_required_agents,
    occupancy_from_traffic_pct,
    service_level_erlang_c,
    traffic_intensity_erlangs,
)

INTERVAL_MINUTES = 30
INTERVAL_SECONDS = INTERVAL_MINUTES * 60
SLOTS_PER_DAY = (24 * 60) // INTERVAL_MINUTES  # 48


# ============================================================================
# Profil de distribution intraday par défaut
# ============================================================================

def _default_profile_raw_weights() -> list[float]:
    """Poids bruts (non normalisés) d'une courbe de volume typique de
    centre de contacts sur 24h : quasi nulle la nuit, deux pics (matin
    ~10h30, après-midi ~14h30), léger creux déjeuner entre les deux.
    Construite comme la somme de deux gaussiennes plus un plancher nocturne
    faible mais non nul (activité résiduelle d'un centre 24/7)."""
    weights = []
    for slot in range(SLOTS_PER_DAY):
        hour = slot * 0.5
        morning_peak = math.exp(-((hour - 10.5) ** 2) / (2 * 2.2**2))
        afternoon_peak = math.exp(-((hour - 14.5) ** 2) / (2 * 2.5**2))
        night_floor = 0.03 if (hour < 7 or hour >= 21) else 0.0
        weights.append(morning_peak + afternoon_peak + night_floor)
    return weights


def profile_for_operating_window(
    target_date: DateType,
    timezone_name: str,
    profile_pct: list[float] | None = None,
) -> list[float]:
    """Masque les tranches hors fenêtre opérationnelle puis renormalise à 100%."""
    validate_timezone_name(timezone_name)
    profile = list(profile_pct or default_intraday_profile_pct())
    if len(profile) != SLOTS_PER_DAY:
        raise ValueError(f"Le profil doit contenir {SLOTS_PER_DAY} tranches.")
    window = seasonal_operating_window(target_date, timezone_name)
    masked = []
    for slot_index, pct in enumerate(profile):
        start, _ = slot_bounds(slot_index)
        inside = (
            window.start_local <= window.end_local
            and window.start_local <= start < window.end_local
        ) or (
            window.start_local > window.end_local
            and (start >= window.start_local or start < window.end_local)
        )
        masked.append(pct if inside else 0.0)
    total = sum(masked)
    if total <= 0:
        raise ValueError("La fenêtre opérationnelle ne recouvre aucun intervalle.")
    return [pct / total * 100 for pct in masked]


def default_intraday_profile_pct() -> list[float]:
    """Profil de distribution par défaut : 48 tranches de 30 min (00:00 à
    23:30), exprimées en % du volume journalier, sommant exactement à 100%.

    Hypothèse V1 documentée (§10) : en l'absence d'historique réel importé,
    on utilise une courbe générique à deux pics plutôt que de forcer une
    saisie manuelle de 48 valeurs. Sera remplacée par un profil calculé sur
    l'historique réel une fois l'import de données disponible (§36).
    """
    raw = _default_profile_raw_weights()
    total = sum(raw)
    return [w / total * 100 for w in raw]


def slot_bounds(slot_index: int) -> tuple[time, time]:
    """Bornes horaires d'un slot de 30 min (0 -> 00:00-00:30, ..., 47 ->
    23:30-24:00). Le dernier slot se termine à 23:59:59 : le type `time`
    Python ne représente pas minuit comme 24:00:00."""
    start_minutes = slot_index * INTERVAL_MINUTES
    start_h, start_m = divmod(start_minutes, 60)
    start = time(start_h, start_m)
    if slot_index == SLOTS_PER_DAY - 1:
        end = time(23, 59, 59)
    else:
        end_h, end_m = divmod(start_minutes + INTERVAL_MINUTES, 60)
        end = time(end_h, end_m)
    return start, end


# ============================================================================
# Génération (Erlang C par intervalle)
# ============================================================================

def build_intraday_forecast_rows(
    session: Session,
    data: GenerateIntradayInput,
    *,
    check_existing: bool = True,
) -> list[IntervalForecast]:
    """Construit les intervalles sans persister ; réutilisable par Daily et Weekly."""
    if check_existing:
        existing = session.exec(
            select(IntervalForecast).where(
                IntervalForecast.date == data.target_date,
                IntervalForecast.campaign_id == data.campaign_id,
                IntervalForecast.skill_id == data.skill_id,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"Des intervalles existent déjà pour le {data.target_date} sur cette campagne/skill "
                "— supprimez-les avant de régénérer."
            )

    profile_pct = profile_for_operating_window(data.target_date, data.timezone_name)
    skill = session.get(Skill, data.skill_id)
    if skill is None:
        raise ValueError("Skill introuvable.")
    channel = skill.channel
    created: list[IntervalForecast] = []

    for slot_index, pct in enumerate(profile_pct):
        interval_start, interval_end = slot_bounds(slot_index)
        interval_volume = data.daily_volume * (pct / 100)

        if channel_service.is_realtime_channel(channel):
            result = find_required_agents(
                volume_contacts=interval_volume,
                aht_seconds=data.daily_aht_seconds,
                interval_seconds=INTERVAL_SECONDS,
                service_level_target_pct=data.service_level_target_pct,
                answer_time_target_seconds=data.answer_time_target_seconds,
                occupancy_target_pct=data.occupancy_target_pct,
            )
            net_required_hc = result.net_required_hc
        else:
            net_required_hc = channel_service.required_hc_for_async(
                volume_contacts=interval_volume,
                aht_seconds=data.daily_aht_seconds,
                interval_seconds=INTERVAL_SECONDS,
                occupancy_target_pct=data.occupancy_target_pct,
                channel=channel,
            )

        gross_required_hc = apply_shrinkage(net_required_hc, data.shrinkage_pct)
        created.append(
            IntervalForecast(
                date=data.target_date,
                interval_start=interval_start,
                interval_end=interval_end,
                campaign_id=data.campaign_id,
                skill_id=data.skill_id,
                channel=channel,
                forecast_volume=interval_volume,
                forecast_aht_seconds=data.daily_aht_seconds,
                required_hc=gross_required_hc,
                scheduled_hc=0.0,
                service_level_target_pct=data.service_level_target_pct,
                answer_time_target_seconds=data.answer_time_target_seconds,
            )
        )
    return created


def generate_intraday_forecast(
    session: Session,
    data: GenerateIntradayInput,
) -> list[IntervalForecast]:
    """Génère et persiste les intervalles d'une journée."""
    created = build_intraday_forecast_rows(session, data, check_existing=True)
    session.add_all(created)
    session.commit()
    for interval in created:
        session.refresh(interval)
    return created


# ============================================================================
# Saisie planning réel / actuals
# ============================================================================

def update_interval(session: Session, *, interval_id: int, data: IntervalUpdateInput) -> IntervalForecast:
    """Met à jour une tranche horaire : planning réel (scheduled_hc)
    et/ou actuals une fois la journée passée.

    Important : Service Level/ASA/Occupancy "atteints" sont des ESTIMATIONS
    recalculées via Erlang C à partir du volume/AHT/HC réels — la V1 n'a
    pas d'intégration ACD pour mesurer directement ces valeurs (l'import de
    données du §36 viendra plus tard). C'est la même formule que pour la
    planification, appliquée à des entrées réelles plutôt que prévisionnelles
    — cohérent, mais pas une mesure brute du superviseur plateau.
    """
    interval = session.get(IntervalForecast, interval_id)
    if interval is None:
        raise ValueError(f"Intervalle {interval_id} introuvable.")

    if data.scheduled_hc is not None:
        interval.scheduled_hc = data.scheduled_hc
    if data.actual_volume is not None:
        interval.actual_volume = data.actual_volume
    if data.actual_aht_seconds is not None:
        interval.actual_aht_seconds = data.actual_aht_seconds
    if data.actual_talk_time_seconds is not None:
        interval.actual_talk_time_seconds = data.actual_talk_time_seconds
    if data.actual_hold_time_seconds is not None:
        interval.actual_hold_time_seconds = data.actual_hold_time_seconds
    if data.actual_acw_seconds is not None:
        interval.actual_acw_seconds = data.actual_acw_seconds

    handle_components = (
        data.actual_talk_time_seconds,
        data.actual_hold_time_seconds,
        data.actual_acw_seconds,
    )
    if any(value is not None for value in handle_components):
        if any(value is None for value in handle_components):
            raise ValueError("Talk Time, Hold Time et ACW doivent être renseignés ensemble.")
        interval.actual_aht_seconds = kpi_service.handle_time_seconds(
            data.actual_talk_time_seconds,
            data.actual_hold_time_seconds,
            data.actual_acw_seconds,
        )
        if interval.actual_aht_seconds <= 0:
            raise ValueError("Handle Time calculé doit être strictement positif.")
    if data.actual_hc is not None:
        interval.actual_hc = data.actual_hc

    client_plan = client_stf_service.current_plan(
        session,
        target_date=interval.date,
        campaign_id=interval.campaign_id,
        skill_id=interval.skill_id,
    )
    effective_required_hc = interval.required_hc
    if client_plan is not None:
        client_rows = client_stf_service.list_intervals(session, client_plan.id)
        matched = next(
            (
                row for row in client_rows
                if row.date == interval.date and row.interval_start == interval.interval_start
            ),
            None,
        )
        if matched is not None:
            effective_required_hc = matched.required_hc

    if interval.actual_volume is not None and interval.actual_aht_seconds is not None and interval.actual_hc:
        agents = max(round(interval.actual_hc), 0)
        traffic_actual = traffic_intensity_erlangs(interval.actual_volume, interval.actual_aht_seconds, INTERVAL_SECONDS)

        if channel_service.is_realtime_channel(interval.channel):
            interval.occupancy_pct = occupancy_from_traffic_pct(traffic_actual, agents) if agents else 0.0
            interval.service_level_pct = (
                service_level_erlang_c(
                    agents,
                    traffic_actual,
                    interval.actual_aht_seconds,
                    interval.answer_time_target_seconds,
                )
                if agents
                else 0.0
            )
            asa_estimate = (
                average_speed_of_answer_erlang_c(
                    agents, traffic_actual, interval.actual_aht_seconds
                )
                if agents
                else None
            )
            interval.asa_seconds = (
                asa_estimate if (asa_estimate is not None and math.isfinite(asa_estimate)) else None
            )
        else:
            workload_hours = channel_service.normalized_workload_hours(
                interval.actual_volume,
                interval.actual_aht_seconds,
                interval.channel,
            )
            capacity_hours = agents * (INTERVAL_SECONDS / 3600.0)
            interval.occupancy_pct = (
                workload_hours / capacity_hours * 100.0 if capacity_hours > 0 else 0.0
            )
            # Les canaux asynchrones nécessitent un modèle SLA basé sur l'âge
            # de la file/message ; il n'est pas assimilé à Erlang C.
            interval.service_level_pct = None
            interval.asa_seconds = None

        interval.staffing_gap = kpi_service.staffing_gap(interval.actual_hc, effective_required_hc)

    if data.abandoned_contacts is not None and interval.actual_volume:
        interval.abandon_rate_pct = kpi_service.abandon_rate_pct(data.abandoned_contacts, interval.actual_volume)

    session.add(interval)
    session.commit()
    session.refresh(interval)
    return interval


# ============================================================================
# Lecture / agrégation
# ============================================================================

def list_intervals_for_day(
    session: Session, *, target_date: DateType, campaign_id: int, skill_id: int
) -> list[IntervalForecast]:
    query = (
        select(IntervalForecast)
        .where(
            IntervalForecast.date == target_date,
            IntervalForecast.campaign_id == campaign_id,
            IntervalForecast.skill_id == skill_id,
        )
        .order_by(IntervalForecast.interval_start)
    )
    return list(session.exec(query).all())


@dataclass(frozen=True)
class DailySummary:
    """Agrégat calculé à la volée depuis les intervalles — jamais persisté
    séparément, pour éviter tout risque d'incohérence avec les intervalles
    sources (une seule source de vérité, DailyForecast reste inutilisée
    en V1)."""

    forecast_volume: float
    actual_volume: Optional[float]
    peak_required_hc: float
    peak_scheduled_hc: float
    peak_actual_hc: Optional[float]
    avg_service_level_pct: Optional[float]
    avg_actual_aht_seconds: Optional[float]


def compute_daily_summary(intervals: list[IntervalForecast]) -> DailySummary:
    forecast_volume = sum(i.forecast_volume for i in intervals)
    actual_values = [i.actual_volume for i in intervals if i.actual_volume is not None]
    peak_required_hc = max((i.required_hc for i in intervals), default=0.0)
    peak_scheduled_hc = max((i.scheduled_hc for i in intervals), default=0.0)
    actual_hcs = [i.actual_hc for i in intervals if i.actual_hc is not None]
    aht_points = [
        (i.actual_aht_seconds, i.actual_volume)
        for i in intervals
        if i.actual_aht_seconds is not None and i.actual_volume is not None
    ]
    avg_actual_aht_seconds = (
        kpi_service.weighted_average(
            [aht for aht, _ in aht_points],
            [volume for _, volume in aht_points],
        )
        if aht_points else None
    )
    service_level_points = [
        (i.service_level_pct, i.actual_volume or i.forecast_volume)
        for i in intervals
        if i.service_level_pct is not None
    ]
    avg_service_level_pct = (
        kpi_service.weighted_average(
            [sl for sl, _ in service_level_points],
            [volume for _, volume in service_level_points],
        )
        if service_level_points else None
    )

    return DailySummary(
        forecast_volume=forecast_volume,
        actual_volume=sum(actual_values) if actual_values else None,
        peak_required_hc=peak_required_hc,
        peak_scheduled_hc=peak_scheduled_hc,
        peak_actual_hc=max(actual_hcs) if actual_hcs else None,
        avg_service_level_pct=avg_service_level_pct,
        avg_actual_aht_seconds=avg_actual_aht_seconds,
    )


def list_days_with_intervals(
    session: Session, *, campaign_id: Optional[int] = None, skill_id: Optional[int] = None
) -> list[dict]:
    """Liste les journées ayant des intervalles générés, les plus récentes
    d'abord, avec un résumé agrégé par journée."""
    query = select(IntervalForecast)
    if campaign_id is not None:
        query = query.where(IntervalForecast.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(IntervalForecast.skill_id == skill_id)
    all_intervals = session.exec(query).all()

    grouped: dict[tuple, list[IntervalForecast]] = {}
    for interval in all_intervals:
        key = (interval.date, interval.campaign_id, interval.skill_id)
        grouped.setdefault(key, []).append(interval)

    results = [
        {"date": d, "campaign_id": c_id, "skill_id": s_id, "summary": compute_daily_summary(intervals)}
        for (d, c_id, s_id), intervals in grouped.items()
    ]
    results.sort(key=lambda r: r["date"], reverse=True)
    return results
