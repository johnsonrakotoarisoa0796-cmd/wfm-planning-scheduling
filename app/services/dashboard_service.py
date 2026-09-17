"""Service métier pour le Dashboard (§5 du cahier des charges).

Ce service n'invente AUCUN nouveau calcul : il assemble des résultats déjà
produits par les modules existants (LTF, Daily/Intraday, Capacity,
Shrinkage, Overtime) et les compare via kpi_service.evaluate_kpi (déjà
construit au commit 04, jamais utilisé jusqu'ici faute de dashboard).

Vue centrée sur UNE date/campagne/skill à la fois — cohérent avec le
reste de l'app (Daily/Intraday, Shrinkage, Overtime fonctionnent tous
ainsi), plutôt qu'un agrégat multi-campagnes qui masquerait les écarts
propres à chaque skill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlmodel import Session

from app.models.forecast import LTFForecast
from app.services import capacity_service, forecast_service, kpi_service, overtime_service, shrinkage_service
from app.services.intraday_service import compute_daily_summary, list_intervals_for_day


@dataclass(frozen=True)
class KPIRow:
    """Une ligne Current/Target/Variance/Status (§5)."""

    label: str
    actual: float
    target: float
    variance: float
    status: str
    unit: str = ""


@dataclass(frozen=True)
class StaffingSnapshot:
    required_hc: float
    scheduled_hc: float
    actual_hc: Optional[float]
    gap: Optional[float]


@dataclass(frozen=True)
class CapacitySnapshot:
    current_hc: float
    projected_hc: float
    required_hc: float
    gap: float


@dataclass(frozen=True)
class DashboardData:
    target_date: date
    has_ltf: bool
    has_intervals: bool
    kpi_rows: list[KPIRow] = field(default_factory=list)
    staffing: Optional[StaffingSnapshot] = None
    forecast_volume: Optional[float] = None
    actual_volume: Optional[float] = None
    forecast_accuracy_pct: Optional[float] = None
    capacity: Optional[CapacitySnapshot] = None
    overtime_required_hours: float = 0.0
    monthly_paid_hours: Optional[float] = None
    monthly_productive_hours: Optional[float] = None
    monthly_production_hours: Optional[float] = None
    monthly_waiting_hours: Optional[float] = None


def _row(label: str, actual: float, target: float, higher_is_better: bool, unit: str = "") -> KPIRow:
    comparison = kpi_service.evaluate_kpi(actual, target, higher_is_better=higher_is_better)
    return KPIRow(
        label=label, actual=comparison.actual, target=comparison.target,
        variance=comparison.variance, status=comparison.status.value, unit=unit,
    )


def _average(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def build_dashboard(session: Session, *, target_date: date, campaign_id: int, skill_id: int) -> DashboardData:
    ltf: Optional[LTFForecast] = forecast_service.get_current_ltf_forecast(
        session, year=target_date.year, month=target_date.month, campaign_id=campaign_id, skill_id=skill_id
    )
    intervals = list_intervals_for_day(session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id)

    kpi_rows: list[KPIRow] = []
    staffing = None
    forecast_volume = actual_volume = forecast_accuracy = None

    if intervals:
        summary = compute_daily_summary(intervals)
        forecast_volume = summary.forecast_volume
        actual_volume = summary.actual_volume
        if actual_volume is not None:
            forecast_accuracy = kpi_service.forecast_accuracy_pct(forecast_volume, actual_volume)

        staffing = StaffingSnapshot(
            required_hc=summary.peak_required_hc,
            scheduled_hc=summary.peak_scheduled_hc,
            actual_hc=summary.peak_actual_hc,
            gap=kpi_service.staffing_gap(summary.peak_actual_hc, summary.peak_required_hc) if summary.peak_actual_hc is not None else None,
        )

        if ltf is not None:
            weighted_aht_points = [(i.actual_volume, i.actual_aht_seconds) for i in intervals if i.actual_volume and i.actual_aht_seconds]
            total_weighted_volume = sum(v for v, _ in weighted_aht_points)
            actual_aht = (sum(v * a for v, a in weighted_aht_points) / total_weighted_volume) if total_weighted_volume else None

            avg_occupancy = _average([i.occupancy_pct for i in intervals if i.occupancy_pct is not None])
            avg_asa = _average([i.asa_seconds for i in intervals if i.asa_seconds is not None])
            avg_sl = _average([i.service_level_pct for i in intervals if i.service_level_pct is not None])

            if avg_sl is not None:
                kpi_rows.append(_row("Service Level", avg_sl, ltf.service_level_target_pct, True, "%"))
            if avg_occupancy is not None:
                kpi_rows.append(_row("Occupancy", avg_occupancy, ltf.occupancy_required_pct, True, "%"))
            if actual_aht is not None:
                kpi_rows.append(_row("AHT", actual_aht, ltf.aht_required_seconds, False, "s"))
            if avg_asa is not None:
                kpi_rows.append(_row("ASA", avg_asa, ltf.asa_target_seconds, False, "s"))

    shrinkage_records = shrinkage_service.list_shrinkage_records(
        session, start_date=target_date, end_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    if ltf is not None:
        categories = shrinkage_service.list_active_categories(session)
        shrinkage_summary = shrinkage_service.compute_shrinkage_summary(
            session, shrinkage_records, categories, skill_id=skill_id, start_date=target_date, end_date=target_date
        )
        if shrinkage_summary.paid_hours > 0:
            kpi_rows.append(_row("Shrinkage", shrinkage_summary.total_pct, ltf.total_shrinkage_pct, False, "%"))

    ot_report = overtime_service.compute_overtime_report(
        session, start_date=target_date, end_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )

    period_key = f"{target_date.year}-{target_date.month:02d}"
    capacity_plans = capacity_service.list_capacity_plans(session, period=period_key, campaign_id=campaign_id, skill_id=skill_id)
    capacity = None
    if capacity_plans:
        plan = capacity_plans[0]
        capacity = CapacitySnapshot(
            current_hc=plan.current_hc, projected_hc=plan.projected_hc, required_hc=plan.required_hc,
            gap=kpi_service.staffing_gap(plan.projected_hc, plan.required_hc),
        )

    return DashboardData(
        target_date=target_date,
        has_ltf=ltf is not None,
        has_intervals=bool(intervals),
        kpi_rows=kpi_rows,
        staffing=staffing,
        forecast_volume=forecast_volume,
        actual_volume=actual_volume,
        forecast_accuracy_pct=forecast_accuracy,
        capacity=capacity,
        overtime_required_hours=ot_report.ot_required_hours,
        monthly_paid_hours=ltf.paid_hours if ltf else None,
        monthly_productive_hours=ltf.productive_hours if ltf else None,
        monthly_production_hours=ltf.production_hours if ltf else None,
        monthly_waiting_hours=ltf.waiting_hours if ltf else None,
    )
