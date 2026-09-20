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
from app.models.campaign import Campaign
from app.models.skill import Skill
from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
from app.models.intraday import IntervalForecast
from app.schemas.ltf import LTFCreateInput
from app.schemas.stf import STFCreateInput
from app.services import channel_service, kpi_service
from app.services.erlang_service import apply_shrinkage

settings = get_settings()

MONTH_NAMES_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def _validate_skill_scope(session: Session, campaign_id: int, skill_id: int) -> Skill:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError("Campagne introuvable.")
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise ValueError("Skill introuvable.")
    if skill.campaign_id != campaign_id:
        raise ValueError("Le skill sélectionné n'appartient pas à la campagne.")
    if not skill.is_active:
        raise ValueError("Le skill sélectionné est désactivé.")
    if not campaign.is_active:
        raise ValueError("La campagne sélectionnée est désactivée.")
    return skill


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
    """Marque la version LTF courante correspondant à la même période."""
    current_versions = session.exec(
        select(ForecastVersion).where(
            ForecastVersion.version_type == ForecastVersionType.LTF,
            ForecastVersion.campaign_id == data.campaign_id,
            ForecastVersion.skill_id == data.skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).all()
    for version in current_versions:
        row = session.exec(
            select(LTFForecast).where(LTFForecast.forecast_version_id == version.id)
        ).first()
        if row is None:
            continue
        same_week = (
            data.iso_year is not None
            and data.iso_week is not None
            and row.iso_year == data.iso_year
            and row.iso_week == data.iso_week
        )
        same_month = (
            data.iso_year is None
            and data.iso_week is None
            and data.year is not None
            and data.month is not None
            and row.year == data.year
            and row.month == data.month
            and row.iso_year is None
        )
        if same_week or same_month:
            version.is_current = False
            session.add(version)


def create_ltf_forecast(session: Session, data: LTFCreateInput, created_by_user_id: int) -> LTFForecast:
    """Crée un LTF.

    Le mode courant est hebdomadaire. Le mode mensuel reste disponible pour
    les historiques existants et les anciennes intégrations.
    """
    _mark_previous_version_as_not_current(session, data)

    skill = _validate_skill_scope(session, data.campaign_id, data.skill_id)

    total_shrinkage_pct = data.indoor_shrinkage_pct + data.outdoor_shrinkage_pct

    if data.iso_year is not None and data.iso_week is not None:
        period_start = date.fromisocalendar(data.iso_year, data.iso_week, 1)
        period_end = date.fromisocalendar(data.iso_year, data.iso_week, 7)
        working_days = count_weekdays_in_range(period_start, period_end)
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
        label = f"LTF Semaine {data.iso_week} - {data.iso_year}"
        row_year, row_month = period_start.year, period_start.month
    else:
        if data.year is None or data.month is None:
            raise ValueError("La période LTF est obligatoire.")
        period_start = date(data.year, data.month, 1)
        _, last_day = calendar.monthrange(data.year, data.month)
        period_end = date(data.year, data.month, last_day)
        working_days = working_days_in_month(data.year, data.month)
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
        label = f"LTF {MONTH_NAMES_FR[data.month]} {data.year}"
        row_year, row_month = data.year, data.month

    total_shrinkage_hours = paid_hours_value * (total_shrinkage_pct / 100)
    productive_hours_value = kpi_service.productive_hours(paid_hours_value, total_shrinkage_hours)
    waiting_hours = max(productive_hours_value - workload, 0.0)
    production_hours_value = kpi_service.production_hours(productive_hours_value, waiting_hours)

    version = ForecastVersion(
        version_type=ForecastVersionType.LTF,
        period_start=period_start,
        period_end=period_end,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        label=label,
        created_by=created_by_user_id,
        notes=data.notes,
        is_current=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    ltf = LTFForecast(
        forecast_version_id=version.id,
        year=row_year,
        month=row_month,
        iso_year=data.iso_year,
        iso_week=data.iso_week,
        week_start_date=period_start if data.iso_week is not None else None,
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


def get_current_weekly_ltf_forecast(
    session: Session,
    *,
    iso_year: int,
    iso_week: int,
    campaign_id: int,
    skill_id: int,
) -> Optional[LTFForecast]:
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            ForecastVersion.is_current == True,  # noqa: E712
            LTFForecast.iso_year == iso_year,
            LTFForecast.iso_week == iso_week,
            LTFForecast.campaign_id == campaign_id,
            LTFForecast.skill_id == skill_id,
        )
    )
    return session.exec(query).first()


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

    parent_ltf = get_current_weekly_ltf_forecast(
        session,
        iso_year=data.iso_year,
        iso_week=data.iso_week,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
    )
    if parent_ltf is None:
        # Compatibilité avec les anciens LTF mensuels.
        parent_ltf = get_current_ltf_forecast(
            session,
            year=week_start_date.year,
            month=week_start_date.month,
            campaign_id=data.campaign_id,
            skill_id=data.skill_id,
        )
    if parent_ltf is None:
        raise ValueError(
            f"Aucun LTF actif pour la semaine {data.iso_week}/{data.iso_year} "
            "sur cette campagne/skill."
        )

    _mark_previous_stf_version_as_not_current(session, data)

    working_days = settings.working_days  # semaine ISO complète = 5 jours ouvrés
    skill = _validate_skill_scope(session, data.campaign_id, data.skill_id)
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


def _promote_previous_ltf_version(session: Session, current: ForecastVersion) -> None:
    previous = session.exec(
        select(ForecastVersion)
        .where(
            ForecastVersion.version_type == ForecastVersionType.LTF,
            ForecastVersion.campaign_id == current.campaign_id,
            ForecastVersion.skill_id == current.skill_id,
            ForecastVersion.period_start == current.period_start,
            ForecastVersion.period_end == current.period_end,
            ForecastVersion.id != current.id,
            ForecastVersion.is_current == False,  # noqa: E712
        )
        .order_by(ForecastVersion.created_at.desc())
    ).first()
    if previous is not None:
        previous.is_current = True
        session.add(previous)


def delete_ltf_forecast(session: Session, ltf_id: int) -> None:
    ltf = session.get(LTFForecast, ltf_id)
    if ltf is None:
        raise ValueError("Forecast LTF introuvable.")

    version = session.get(ForecastVersion, ltf.forecast_version_id)
    if version is None:
        raise ValueError("Version LTF introuvable.")

    children = session.exec(
        select(ForecastVersion).where(ForecastVersion.parent_version_id == version.id)
    ).first()
    if children is not None:
        raise ValueError(
            "Impossible de supprimer ce LTF : un ou plusieurs STF dépendent de cette version. "
            "Supprimez ou rectifiez d'abord les STF concernés."
        )

    _promote_previous_ltf_version(session, version)
    session.delete(ltf)
    session.delete(version)
    session.commit()


def _promote_previous_stf_version(session: Session, current: ForecastVersion) -> None:
    previous = session.exec(
        select(ForecastVersion)
        .where(
            ForecastVersion.version_type == ForecastVersionType.STF,
            ForecastVersion.campaign_id == current.campaign_id,
            ForecastVersion.skill_id == current.skill_id,
            ForecastVersion.period_start == current.period_start,
            ForecastVersion.period_end == current.period_end,
            ForecastVersion.id != current.id,
            ForecastVersion.is_current == False,  # noqa: E712
        )
        .order_by(ForecastVersion.created_at.desc())
    ).first()
    if previous is not None:
        previous.is_current = True
        session.add(previous)


def delete_stf_forecast(session: Session, stf_id: int) -> None:
    stf = session.get(STFForecast, stf_id)
    if stf is None:
        raise ValueError("Forecast STF introuvable.")

    existing_daily = session.exec(
        select(IntervalForecast).where(
            IntervalForecast.campaign_id == stf.campaign_id,
            IntervalForecast.skill_id == stf.skill_id,
            IntervalForecast.date >= stf.week_start_date,
            IntervalForecast.date <= stf.week_start_date + timedelta(days=6),
        )
    ).first()
    if existing_daily is not None:
        raise ValueError(
            "Impossible de supprimer ce STF : des données Daily/Intraday existent déjà "
            "pour cette semaine. Supprimez ou remplacez d'abord la dispersion Daily."
        )

    version = session.get(ForecastVersion, stf.forecast_version_id)
    if version is None:
        raise ValueError("Version STF introuvable.")

    _promote_previous_stf_version(session, version)
    session.delete(stf)
    session.delete(version)
    session.commit()
