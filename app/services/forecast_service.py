"""Service métier pour le forecast LTF Monthly et STF Weekly (§6-§9 du
cahier des charges).

Toute la logique de versioning (jamais d'écrasement — une seule version
"courante" par période/campagne/skill) et l'orchestration des moteurs KPI/
Erlang vit ici. Les routers n'appellent que ces fonctions, jamais de calcul
inline (règle §11 / §40).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.enums import ForecastVersionType
from app.models.skill import Skill
from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
from app.schemas.ltf import LTFCreateInput
from app.schemas.stf import STFCreateInput
from app.services import channel_service, kpi_service
from app.services.erlang_service import apply_shrinkage

settings = get_settings()

MONTH_NAMES_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def count_weekdays_in_range(start_date: date, end_date: date) -> int:
    """Nombre de jours ouvrés (lundi-vendredi) entre deux dates incluses.

    Généralisation de working_days_in_month (ci-dessous, qui délègue
    désormais à cette fonction) — réutilisée par le module Shrinkage pour
    calculer des Paid Hours sur une période arbitraire (jour/semaine/mois,
    §25), pas seulement un mois calendaire complet.
    """
    if end_date < start_date:
        raise ValueError("end_date doit être postérieure ou égale à start_date.")
    total_days = (end_date - start_date).days + 1
    return sum(1 for offset in range(total_days) if (start_date + timedelta(days=offset)).weekday() < 5)


def working_days_in_month(year: int, month: int) -> int:
    """Nombre de jours ouvrés (lundi-vendredi) dans le mois donné.

    Hypothèse V1 : semaine de travail lundi-vendredi, cohérent avec le
    défaut `working_days=5` de app/core/config.py. Une semaine de travail
    avec un jour de repos différent du week-end classique nécessiterait un
    calcul spécifique — hors périmètre V1.
    """
    _, days_in_month = calendar.monthrange(year, month)
    return count_weekdays_in_range(date(year, month, 1), date(year, month, days_in_month))


def _mark_previous_version_as_not_current(session: Session, data: LTFCreateInput) -> None:
    """Marque l'éventuelle version LTF courante existante comme non-courante.

    Ne supprime ni ne modifie jamais les valeurs déjà enregistrées — c'est
    la règle de non-écrasement du forecast (§9). L'historique complet reste
    consultable via ForecastVersion.is_current == False.
    """
    current_versions = session.exec(
        select(ForecastVersion).where(
            ForecastVersion.version_type == ForecastVersionType.LTF,
            ForecastVersion.campaign_id == data.campaign_id,
            ForecastVersion.skill_id == data.skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).all()
    for version in current_versions:
        ltf_row = session.exec(
            select(LTFForecast).where(LTFForecast.forecast_version_id == version.id)
        ).first()
        if ltf_row is not None and ltf_row.year == data.year and ltf_row.month == data.month:
            version.is_current = False
            session.add(version)


def create_ltf_forecast(session: Session, data: LTFCreateInput, created_by_user_id: int) -> LTFForecast:
    """Crée une nouvelle version LTF à partir des entrées validées.

    Pipeline de calcul (chaque étape appelle le moteur KPI/Erlang, jamais de
    formule inline ici) :
      1. Workload Hours = Volume x AHT
      2. Net Required HC = Workload / (Heures dispo par agent x Occupancy)
         — formule agrégée mensuelle, PAS Erlang C (voir
         kpi_service.required_hc_aggregate pour la justification ; Erlang C
         s'applique au niveau Daily/Intraday, commit 08)
      3. Gross Required HC = Net Required HC / (1 - Shrinkage%)
      4. Paid Hours = Gross Required HC x heures/jour x jours ouvrés du mois
      5. Productive Hours = Paid Hours - Shrinkage Hours
      6. Production Hours = Productive Hours - Waiting Hours

    staffing_gap et overtime_required_hours restent à 0.0 à la création :
    ils seront calculés par les modules dédiés Capacity Planning (commit 09)
    et Overtime (commit 11), qui ont besoin de l'effectif réel/planifié —
    inconnu au moment de la simple saisie d'un forecast (§26, §31).
    """
    _mark_previous_version_as_not_current(session, data)

    total_shrinkage_pct = data.indoor_shrinkage_pct + data.outdoor_shrinkage_pct
    working_days = working_days_in_month(data.year, data.month)

    skill = session.get(Skill, data.skill_id)
    if skill is None:
        raise ValueError("Skill introuvable.")
    workload = kpi_service.workload_hours(data.forecast_volume, data.forecast_aht_seconds)
    available_hours_per_agent = kpi_service.paid_hours(1, settings.daily_hours, working_days)
    net_required_hc = channel_service.required_hc_aggregate_channel(
        workload,
        available_hours_per_agent,
        data.occupancy_required_pct,
        skill.channel,
    )
    gross_required_hc = apply_shrinkage(net_required_hc, total_shrinkage_pct)

    paid_hours_value = kpi_service.paid_hours(gross_required_hc, settings.daily_hours, working_days)
    total_shrinkage_hours = paid_hours_value * (total_shrinkage_pct / 100)
    productive_hours_value = kpi_service.productive_hours(paid_hours_value, total_shrinkage_hours)
    waiting_hours = max(productive_hours_value - workload, 0.0)
    production_hours_value = kpi_service.production_hours(productive_hours_value, waiting_hours)

    period_start = date(data.year, data.month, 1)
    _, last_day = calendar.monthrange(data.year, data.month)
    period_end = date(data.year, data.month, last_day)

    version = ForecastVersion(
        version_type=ForecastVersionType.LTF,
        period_start=period_start,
        period_end=period_end,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        label=f"LTF {MONTH_NAMES_FR[data.month]} {data.year}",
        created_by=created_by_user_id,
        notes=data.notes,
        is_current=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    ltf = LTFForecast(
        forecast_version_id=version.id,
        year=data.year,
        month=data.month,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        forecast_volume=data.forecast_volume,
        forecast_aht_seconds=data.forecast_aht_seconds,
        aht_required_seconds=data.aht_required_seconds,
        occupancy_required_pct=data.occupancy_required_pct,
        service_level_target_pct=data.service_level_target_pct,
        asa_target_seconds=data.asa_target_seconds,
        headcount_required=gross_required_hc,
        paid_hours=paid_hours_value,
        productive_hours=productive_hours_value,
        production_hours=production_hours_value,
        waiting_hours=waiting_hours,
        indoor_shrinkage_pct=data.indoor_shrinkage_pct,
        outdoor_shrinkage_pct=data.outdoor_shrinkage_pct,
        total_shrinkage_pct=total_shrinkage_pct,
        available_hours=productive_hours_value,
        staffing_gap=0.0,
        overtime_required_hours=0.0,
    )
    session.add(ltf)
    session.commit()
    session.refresh(ltf)
    return ltf


def list_current_ltf_forecasts(
    session: Session,
    *,
    year: Optional[int] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[LTFForecast]:
    """Liste les forecasts LTF courants (is_current=True sur leur version),
    avec filtres optionnels (§43)."""
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(ForecastVersion.is_current == True)  # noqa: E712
    )
    if year is not None:
        query = query.where(LTFForecast.year == year)
    if campaign_id is not None:
        query = query.where(LTFForecast.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(LTFForecast.skill_id == skill_id)
    query = query.order_by(LTFForecast.year, LTFForecast.month)
    return list(session.exec(query).all())


def get_current_ltf_forecast(
    session: Session, *, year: int, month: int, campaign_id: int, skill_id: int
) -> Optional[LTFForecast]:
    """LTF courant pour un mois/campagne/skill donné, ou None s'il n'existe
    pas encore — utilisé par le STF pour retrouver le plan de référence
    qu'il réajuste (§8)."""
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            ForecastVersion.is_current == True,  # noqa: E712
            LTFForecast.year == year,
            LTFForecast.month == month,
            LTFForecast.campaign_id == campaign_id,
            LTFForecast.skill_id == skill_id,
        )
    )
    return session.exec(query).first()


def get_ltf_version_history(
    session: Session, *, campaign_id: int, skill_id: int, year: int, month: int
) -> list[LTFForecast]:
    """Historique complet (toutes versions, courante ou non) d'un couple
    campagne/skill/mois donné, du plus ancien au plus récent — utile pour
    comparer l'évolution d'un forecast (§9)."""
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            LTFForecast.campaign_id == campaign_id,
            LTFForecast.skill_id == skill_id,
            LTFForecast.year == year,
            LTFForecast.month == month,
        )
        .order_by(ForecastVersion.created_at)
    )
    return list(session.exec(query).all())


# ============================================================================
# STF — Short Term Forecast — réajustement hebdomadaire du LTF (§8)
# ============================================================================


def _mark_previous_stf_version_as_not_current(session: Session, data: STFCreateInput) -> None:
    """Équivalent de _mark_previous_version_as_not_current pour le STF :
    marque l'éventuelle version STF courante déjà existante pour la même
    semaine ISO comme non-courante (jamais de suppression — §9)."""
    current_versions = session.exec(
        select(ForecastVersion).where(
            ForecastVersion.version_type == ForecastVersionType.STF,
            ForecastVersion.campaign_id == data.campaign_id,
            ForecastVersion.skill_id == data.skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).all()
    for version in current_versions:
        stf_row = session.exec(
            select(STFForecast).where(STFForecast.forecast_version_id == version.id)
        ).first()
        if stf_row is not None and stf_row.iso_year == data.iso_year and stf_row.iso_week == data.iso_week:
            version.is_current = False
            session.add(version)


def create_stf_forecast(session: Session, data: STFCreateInput, created_by_user_id: int) -> STFForecast:
    """Crée une nouvelle version STF, réajustement hebdomadaire d'un LTF déjà
    existant. Échoue explicitement si aucun LTF courant ne couvre cette
    semaine (règle métier : le STF réajuste le LTF, il n'existe pas seul).

    Pipeline de calcul identique dans l'esprit à create_ltf_forecast, mais à
    l'échelle de la semaine : Workload Hours -> Net Required HC (formule
    agrégée) -> Gross Required HC -> Paid/Productive/Production Hours. Une
    semaine ISO fait toujours 5 jours ouvrés (lundi-vendredi) par
    construction, donc settings.working_days s'applique directement, sans
    équivalent de working_days_in_month.
    """
    week_start_date = date.fromisocalendar(data.iso_year, data.iso_week, 1)

    parent_ltf = get_current_ltf_forecast(
        session,
        year=week_start_date.year,
        month=week_start_date.month,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
    )
    if parent_ltf is None:
        raise ValueError(
            f"Aucun LTF actif pour {MONTH_NAMES_FR[week_start_date.month]} {week_start_date.year} "
            "sur cette campagne/skill — créez d'abord un LTF pour ce mois."
        )

    _mark_previous_stf_version_as_not_current(session, data)

    working_days = settings.working_days  # semaine ISO complète = 5 jours ouvrés
    skill = session.get(Skill, data.skill_id)
    if skill is None:
        raise ValueError("Skill introuvable.")
    workload = kpi_service.workload_hours(data.volume, data.aht_seconds)
    available_hours_per_agent = kpi_service.paid_hours(1, settings.daily_hours, working_days)
    net_required_hc = channel_service.required_hc_aggregate_channel(
        workload,
        available_hours_per_agent,
        data.occupancy_pct,
        skill.channel,
    )
    gross_required_hc = apply_shrinkage(net_required_hc, data.shrinkage_pct)

    paid_hours_value = kpi_service.paid_hours(gross_required_hc, settings.daily_hours, working_days)
    total_shrinkage_hours = paid_hours_value * (data.shrinkage_pct / 100)
    productive_hours_value = kpi_service.productive_hours(paid_hours_value, total_shrinkage_hours)
    waiting_hours = max(productive_hours_value - workload, 0.0)
    production_hours_value = kpi_service.production_hours(productive_hours_value, waiting_hours)

    week_end_date = date.fromisocalendar(data.iso_year, data.iso_week, 7)

    version = ForecastVersion(
        version_type=ForecastVersionType.STF,
        period_start=week_start_date,
        period_end=week_end_date,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        parent_version_id=parent_ltf.forecast_version_id,
        label=f"STF Semaine {data.iso_week} - {data.iso_year}",
        created_by=created_by_user_id,
        notes=data.notes,
        is_current=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    stf = STFForecast(
        forecast_version_id=version.id,
        iso_year=data.iso_year,
        iso_week=data.iso_week,
        week_start_date=week_start_date,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        volume=data.volume,
        aht_seconds=data.aht_seconds,
        occupancy_pct=data.occupancy_pct,
        shrinkage_pct=data.shrinkage_pct,
        service_level_target_pct=data.service_level_target_pct,
        headcount_required=gross_required_hc,
        paid_hours=paid_hours_value,
        productive_hours=productive_hours_value,
        production_hours=production_hours_value,
        waiting_hours=waiting_hours,
        overtime_required_hours=0.0,
    )
    session.add(stf)
    session.commit()
    session.refresh(stf)
    return stf


def list_current_stf_forecasts(
    session: Session,
    *,
    iso_year: Optional[int] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[STFForecast]:
    """Liste les forecasts STF courants (is_current=True sur leur version),
    avec filtres optionnels (§43)."""
    query = (
        select(STFForecast)
        .join(ForecastVersion, STFForecast.forecast_version_id == ForecastVersion.id)
        .where(ForecastVersion.is_current == True)  # noqa: E712
    )
    if iso_year is not None:
        query = query.where(STFForecast.iso_year == iso_year)
    if campaign_id is not None:
        query = query.where(STFForecast.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(STFForecast.skill_id == skill_id)
    query = query.order_by(STFForecast.iso_year, STFForecast.iso_week)
    return list(session.exec(query).all())


def get_stf_version_history(
    session: Session, *, campaign_id: int, skill_id: int, iso_year: int, iso_week: int
) -> list[STFForecast]:
    """Historique complet (toutes versions) d'une semaine ISO donnée, du
    plus ancien au plus récent (§9)."""
    query = (
        select(STFForecast)
        .join(ForecastVersion, STFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            STFForecast.campaign_id == campaign_id,
            STFForecast.skill_id == skill_id,
            STFForecast.iso_year == iso_year,
            STFForecast.iso_week == iso_week,
        )
        .order_by(ForecastVersion.created_at)
    )
    return list(session.exec(query).all())


def get_stf_forecasts_for_ltf_version(session: Session, ltf_version_id: int) -> list[STFForecast]:
    """Toutes les semaines STF (courantes) qui réajustent une version LTF
    donnée — permet d'afficher, depuis un LTF, les révisions hebdomadaires
    qui en découlent (§47)."""
    query = (
        select(STFForecast)
        .join(ForecastVersion, STFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            ForecastVersion.parent_version_id == ltf_version_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
        .order_by(STFForecast.iso_week)
    )
    return list(session.exec(query).all())


@dataclass(frozen=True)
class LTFvsSTFRow:
    """Une ligne du tableau LTF vs STF vs Variance (§8, §47)."""

    metric: str
    ltf_value: float
    stf_value: float
    adjustment: float
    adjustment_pct: float
    unit: str = ""


def compare_ltf_stf(ltf: LTFForecast, stf: STFForecast) -> list[LTFvsSTFRow]:
    """Construit le tableau LTF vs STF vs Variance de l'exemple du §8 :

        Volume       LTF 42,000   STF 44,500   +2,500
        AHT          LTF 320      STF 335      +15
        Occupancy    LTF 85%      STF 86%      +1 pt
        ...

    Adjustment = STF - LTF, Adjustment % = (STF - LTF) / LTF x 100 — les
    formules exactes du §8, réutilisées depuis kpi_service (forecast_variance
    / forecast_variance_pct) plutôt que réécrites ici.
    """

    def _row(metric: str, ltf_value: float, stf_value: float, unit: str = "") -> LTFvsSTFRow:
        return LTFvsSTFRow(
            metric=metric,
            ltf_value=ltf_value,
            stf_value=stf_value,
            adjustment=kpi_service.forecast_variance(ltf_value, stf_value),
            adjustment_pct=kpi_service.forecast_variance_pct(ltf_value, stf_value),
            unit=unit,
        )

    return [
        _row("Volume", ltf.forecast_volume, stf.volume, "contacts"),
        _row("AHT", ltf.forecast_aht_seconds, stf.aht_seconds, "s"),
        _row("Occupancy", ltf.occupancy_required_pct, stf.occupancy_pct, "%"),
        _row("Shrinkage", ltf.total_shrinkage_pct, stf.shrinkage_pct, "%"),
        _row("Service Level Target", ltf.service_level_target_pct, stf.service_level_target_pct, "%"),
        _row("Headcount Required", ltf.headcount_required, stf.headcount_required, "HC"),
        _row("Paid Hours", ltf.paid_hours, stf.paid_hours, "h"),
        _row("Productive Hours", ltf.productive_hours, stf.productive_hours, "h"),
        _row("Overtime Required", ltf.overtime_required_hours, stf.overtime_required_hours, "h"),
    ]
