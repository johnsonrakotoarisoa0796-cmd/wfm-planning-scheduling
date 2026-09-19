"""Service de construction du dashboard WFM."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlmodel import Session

from app.models.forecast import LTFForecast
from app.services import capacity_service, forecast_service, kpi_service, overtime_service, shrinkage_service
from app.services.intraday_service import compute_daily_summary, list_intervals_for_day
from app.services.wfm_metrics_service import WFMScorecard, build_scorecard


@dataclass(frozen=True)
class KPIRow:
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
    wfm_scorecard: Optional[WFMScorecard] = None


def _row(
    label: str,
    actual: float,
    target: float,
    higher_is_better: bool,
    unit: str = "",
) -> KPIRow:
    comparison = kpi_service.evaluate_kpi(
        actual, target, higher_is_better=higher_is_better
    )
    return KPIRow(
        label=label,
        actual=comparison.actual,
        target=comparison.target,
        variance=comparison.variance,
        status=comparison.status.value,
        unit=unit,
    )


def _weighted_average(values: list[float], weights: list[float]) -> Optional[float]:
    pairs = [(v, w) for v, w in zip(values, weights) if w > 0]
    if not pairs:
        return None
    return kpi_service.weighted_average([v for v, _ in pairs], [w for _, w in pairs])


def build_dashboard(
    session: Session,
    *,
    target_date: date,
    campaign_id: int,
    skill_id: int,
) -> DashboardData:
    ltf: Optional[LTFForecast] = forecast_service.get_current_ltf_forecast(
        session,
        year=target_date.year,
        month=target_date.month,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    intervals = list_intervals_for_day(
        session,
        target_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )

    scorecard = build_scorecard(
        intervals,
        occupancy_target_pct=ltf.occupancy_required_pct if ltf else None,
        aht_target_seconds=ltf.aht_required_seconds if ltf else None,
    ) if intervals else None

    kpi_rows: list[KPIRow] = []
    staffing = None
    forecast_volume = actual_volume = forecast_accuracy = None

    if intervals:
        summary = compute_daily_summary(intervals)
        forecast_volume = summary.forecast_volume
        actual_volume = summary.actual_volume
        forecast_accuracy = (
            kpi_service.forecast_accuracy_pct(forecast_volume, actual_volume)
            if actual_volume is not None else None
        )
        staffing = StaffingSnapshot(
            required_hc=summary.peak_required_hc,
            scheduled_hc=summary.peak_scheduled_hc,
            actual_hc=summary.peak_actual_hc,
            gap=(
                kpi_service.staffing_gap(
                    summary.peak_actual_hc, summary.peak_required_hc
                )
                if summary.peak_actual_hc is not None else None
            ),
        )

        if ltf is not None:
            actual_aht = scorecard.operations.actual_aht_seconds if scorecard else None
            actual_occupancy = scorecard.operations.occupancy_pct if scorecard else None
            actual_asa = scorecard.operations.actual_asa_seconds if scorecard else None
            actual_sl = scorecard.operations.actual_service_level_pct if scorecard else None
            if actual_sl is not None:
                kpi_rows.append(_row("Service Level", actual_sl, ltf.service_level_target_pct, True, "%"))
            if actual_occupancy is not None:
                kpi_rows.append(_row("Occupancy", actual_occupancy, ltf.occupancy_required_pct, False, "%"))
            if actual_aht is not None:
                kpi_rows.append(_row("AHT", actual_aht, ltf.aht_required_seconds, False, "s"))
            if actual_asa is not None:
                kpi_rows.append(_row("ASA", actual_asa, ltf.asa_target_seconds, False, "s"))

    shrinkage_records = shrinkage_service.list_shrinkage_records(
        session,
        start_date=target_date,
        end_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    if ltf is not None:
        categories = shrinkage_service.list_active_categories(session)
        shrinkage_summary = shrinkage_service.compute_shrinkage_summary(
            session,
            shrinkage_records,
            categories,
            skill_id=skill_id,
            start_date=target_date,
            end_date=target_date,
        )
        if shrinkage_summary.paid_hours > 0:
            kpi_rows.append(
                _row(
                    "Shrinkage",
                    shrinkage_summary.total_pct,
                    ltf.total_shrinkage_pct,
                    False,
                    "%",
                )
            )

    ot_report = overtime_service.compute_overtime_report(
        session,
        start_date=target_date,
        end_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )

    period_key = f"{target_date.year}-{target_date.month:02d}"
    capacity_plans = capacity_service.list_capacity_plans(
        session,
        period=period_key,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    capacity = None
    if capacity_plans:
        plan = capacity_plans[0]
        capacity = CapacitySnapshot(
            current_hc=plan.current_hc,
            projected_hc=plan.projected_hc,
            required_hc=plan.required_hc,
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
        wfm_scorecard=scorecard,
    )
