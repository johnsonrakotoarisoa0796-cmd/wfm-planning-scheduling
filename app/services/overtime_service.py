"""Service métier pour le module Overtime (§26-§30 du cahier des charges).

Required Hours et Available Hours sont calculées à partir des intervalles
Daily/Intraday déjà générés (commit 08) — Required = somme(required_hc x
durée intervalle), Available = somme(scheduled_hc x durée intervalle).
Une seule fonction de calcul sur une plage de dates arbitraire sert
Daily/Weekly/Monthly (§27-29), même principe que le rapport Shrinkage
(commit 10) : un jour, une semaine ou un mois ne sont que des plages
particulières, pas des calculs différents.

Required OT et Actual OT restent deux données strictement distinctes
(§30) : Required est toujours recalculé depuis les intervalles ; Actual
est saisi manuellement une fois connu (aucune intégration paie/pointage
en V1) et ne modifie jamais Required.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.models.enums import PeriodType
from app.models.intraday import IntervalForecast
from app.models.overtime import OvertimePlan
from app.schemas.overtime import OvertimeActualInput, OvertimePlanInput
from app.services import client_stf_service, kpi_service
from app.services.intraday_service import INTERVAL_MINUTES

_INTERVAL_DURATION_HOURS = INTERVAL_MINUTES / 60  # 0.5


@dataclass(frozen=True)
class DailyOTPoint:
    """Un point du graphique OT Required by Day/Week (§29)."""

    day: date
    ot_required_hours: float


@dataclass(frozen=True)
class OvertimeReport:
    """Résultat du calcul Overtime sur une plage de dates (§27-29)."""

    start_date: date
    end_date: date
    required_hours: float
    available_hours: float
    gap_hours: float
    ot_required_hours: float
    daily_breakdown: list[DailyOTPoint]


def _hours_from_intervals(intervals: list[IntervalForecast]) -> tuple[float, float]:
    """(Required Hours, Available Hours) en agent-heures, à partir
    d'intervalles de 30 min : somme(required_hc x 0.5h), somme(scheduled_hc x 0.5h)."""
    required = sum(i.required_hc for i in intervals) * _INTERVAL_DURATION_HOURS
    available = sum(i.scheduled_hc for i in intervals) * _INTERVAL_DURATION_HOURS
    return required, available


def compute_overtime_report(
    session: Session, *, start_date: date, end_date: date, campaign_id: int, skill_id: int
) -> OvertimeReport:
    """Calcule Required/Available/Gap/OT Required sur une plage de dates,
    à partir des intervalles Daily/Intraday existants. Retourne un rapport
    à 0 (pas une exception) si aucun intervalle n'existe encore — le
    rapport reste affichable, juste vide, plutôt qu'une erreur bloquante
    pour une plage partiellement couverte."""
    query = select(IntervalForecast).where(
        IntervalForecast.date >= start_date,
        IntervalForecast.date <= end_date,
        IntervalForecast.campaign_id == campaign_id,
        IntervalForecast.skill_id == skill_id,
    )
    intervals = list(session.exec(query).all())
    intervals = client_stf_service.effective_intervals_for_range(
        session,
        intervals,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )

    required_hours, available_hours = _hours_from_intervals(intervals)
    gap_hours = kpi_service.staffing_gap(available_hours, required_hours)
    ot_required = kpi_service.overtime_required_hours(required_hours, available_hours)

    by_date: dict[date, list[IntervalForecast]] = {}
    for interval in intervals:
        by_date.setdefault(interval.date, []).append(interval)

    daily_breakdown = []
    for day in sorted(by_date.keys()):
        day_required, day_available = _hours_from_intervals(by_date[day])
        daily_breakdown.append(
            DailyOTPoint(day=day, ot_required_hours=kpi_service.overtime_required_hours(day_required, day_available))
        )

    return OvertimeReport(
        start_date=start_date,
        end_date=end_date,
        required_hours=required_hours,
        available_hours=available_hours,
        gap_hours=gap_hours,
        ot_required_hours=ot_required,
        daily_breakdown=daily_breakdown,
    )


def _derive_period_key(period_type: PeriodType, start_date: date) -> str:
    """Dérive period_key depuis start_date selon la granularité choisie."""
    if period_type == PeriodType.DAILY:
        return str(start_date)
    if period_type == PeriodType.WEEKLY:
        iso_year, iso_week, _ = start_date.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    return f"{start_date.year}-{start_date.month:02d}"


def date_range_from_period_key(period_type: PeriodType, period_key: str) -> tuple[date, date]:
    """Reconstruit (start_date, end_date) à partir d'un period_key stocké —
    utilisé pour rejouer le calcul (ex: rafraîchir le graphique de détail)
    sans avoir à stocker la plage de dates séparément sur OvertimePlan."""
    if period_type == PeriodType.DAILY:
        d = date.fromisoformat(period_key)
        return d, d
    if period_type == PeriodType.WEEKLY:
        year_str, week_str = period_key.split("-W")
        year, week = int(year_str), int(week_str)
        return date.fromisocalendar(year, week, 1), date.fromisocalendar(year, week, 7)
    year_str, month_str = period_key.split("-")
    year, month = int(year_str), int(month_str)
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def upsert_overtime_plan(session: Session, data: OvertimePlanInput) -> OvertimePlan:
    """Calcule le rapport Overtime pour la plage donnée et l'enregistre.

    Upsert (pas de versioning) : ré-enregistrer pour la même
    période/campagne/skill met à jour le plan existant plutôt que d'en
    créer un nouveau — même logique que Capacity Planning (commit 09), ce
    n'est pas un forecast mais un suivi recalculé à la demande.
    """
    report = compute_overtime_report(
        session, start_date=data.start_date, end_date=data.end_date,
        campaign_id=data.campaign_id, skill_id=data.skill_id,
    )
    period_key = _derive_period_key(data.period_type, data.start_date)

    existing = session.exec(
        select(OvertimePlan).where(
            OvertimePlan.period_type == data.period_type,
            OvertimePlan.period_key == period_key,
            OvertimePlan.campaign_id == data.campaign_id,
            OvertimePlan.skill_id == data.skill_id,
        )
    ).first()

    plan = existing or OvertimePlan(
        period_type=data.period_type, period_key=period_key,
        campaign_id=data.campaign_id, skill_id=data.skill_id,
    )
    plan.required_hours = report.required_hours
    plan.available_hours = report.available_hours
    plan.gap_hours = report.gap_hours
    plan.ot_required_hours = report.ot_required_hours
    plan.notes = data.notes
    # ot_actual_hours n'est jamais touché ici : il vit sa vie propre,
    # saisi séparément via update_actual_ot() une fois connu (§30).

    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def update_actual_ot(session: Session, *, plan_id: int, data: OvertimeActualInput) -> OvertimePlan:
    """Enregistre l'OT réellement effectué (§30) — ne recalcule jamais
    Required, qui reste la référence théorique indépendante."""
    plan = session.get(OvertimePlan, plan_id)
    if plan is None:
        raise ValueError(f"Plan Overtime {plan_id} introuvable.")
    plan.ot_actual_hours = data.ot_actual_hours
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def list_overtime_plans(
    session: Session,
    *,
    period_type: Optional[PeriodType] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[OvertimePlan]:
    query = select(OvertimePlan)
    if period_type is not None:
        query = query.where(OvertimePlan.period_type == period_type)
    if campaign_id is not None:
        query = query.where(OvertimePlan.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(OvertimePlan.skill_id == skill_id)
    return list(session.exec(query.order_by(OvertimePlan.period_key.desc())).all())
