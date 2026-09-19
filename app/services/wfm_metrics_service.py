"""Scorecard WFM et recommandations intraday.

Ce module assemble des KPI à partir des intervalles existants sans persister
de nouveaux agrégats. Il distingue systématiquement forecast, scheduled et
actual, et applique des moyennes pondérées par volume quand la métrique est
un taux opérationnel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional

from app.models.intraday import IntervalForecast
from app.services import kpi_service
from app.services.erlang_service import average_speed_of_answer_erlang_c, service_level_erlang_c, traffic_intensity_erlangs

INTERVAL_HOURS = 0.5


@dataclass(frozen=True)
class ForecastScorecard:
    forecast_volume: float
    actual_volume: Optional[float]
    variance_contacts: Optional[float]
    variance_pct: Optional[float]
    accuracy_pct: Optional[float]
    wape_pct: Optional[float]
    mape_pct: Optional[float]
    bias_pct: Optional[float]


@dataclass(frozen=True)
class StaffingScorecard:
    required_hc_hours: float
    scheduled_hc_hours: float
    actual_hc_hours: Optional[float]
    shortage_hc_hours: float
    surplus_hc_hours: float
    coverage_pct: float
    peak_required_hc: float
    peak_scheduled_hc: float
    peak_actual_hc: Optional[float]
    understaffed_intervals: int
    overstaffed_intervals: int
    overtime_required_hours: float
    staffing_adherence_proxy_pct: Optional[float]


@dataclass(frozen=True)
class OperationsScorecard:
    forecast_aht_seconds: float
    actual_aht_seconds: Optional[float]
    aht_variance_seconds: Optional[float]
    scheduled_service_level_pct: float
    actual_service_level_pct: Optional[float]
    service_level_target_pct: float
    service_level_gap_pct: Optional[float]
    scheduled_asa_seconds: Optional[float]
    actual_asa_seconds: Optional[float]
    occupancy_pct: Optional[float]
    occupancy_target_pct: float
    occupancy_gap_pct: Optional[float]
    abandon_rate_pct: Optional[float]
    workload_hours: Optional[float]
    utilization_pct: Optional[float]
    schedule_efficiency_pct: float


@dataclass(frozen=True)
class PlannerAlert:
    severity: str
    interval_start: time
    interval_end: time
    title: str
    detail: str
    recommended_hc_delta: float = 0.0


@dataclass(frozen=True)
class WFMScorecard:
    forecast: ForecastScorecard
    staffing: StaffingScorecard
    operations: OperationsScorecard
    alerts: list[PlannerAlert]


def _weighted_optional(values: list[Optional[float]], weights: list[float]) -> Optional[float]:
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None and w > 0]
    if not pairs:
        return None
    return kpi_service.weighted_average([v for v, _ in pairs], [w for _, w in pairs])


def _scheduled_metrics(interval: IntervalForecast) -> tuple[float, Optional[float]]:
    if interval.scheduled_hc <= 0 or interval.forecast_volume <= 0 or interval.forecast_aht_seconds <= 0:
        return 0.0, None
    traffic = traffic_intensity_erlangs(interval.forecast_volume, interval.forecast_aht_seconds, INTERVAL_HOURS * 3600)
    agents = max(round(interval.scheduled_hc), 0)
    if agents <= 0:
        return 0.0, None
    sl = service_level_erlang_c(
        agents,
        traffic,
        interval.forecast_aht_seconds,
        interval.answer_time_target_seconds,
    )
    asa = average_speed_of_answer_erlang_c(agents, traffic, interval.forecast_aht_seconds)
    return sl, asa if asa != float("inf") else None


def build_scorecard(intervals: list[IntervalForecast]) -> WFMScorecard:
    if not intervals:
        empty_forecast = ForecastScorecard(0, None, None, None, None, None, None, None)
        empty_staffing = StaffingScorecard(0, 0, None, 0, 0, 0, 0, 0, None, 0, 0, 0, None)
        empty_ops = OperationsScorecard(0, None, None, 0, None, 0, None, None, None, None, 0, None, None, None, None)
        return WFMScorecard(empty_forecast, empty_staffing, empty_ops, [])

    forecast_values = [i.forecast_volume for i in intervals]
    actual_pairs = [(i.forecast_volume, i.actual_volume) for i in intervals if i.actual_volume is not None]
    actual_values = [a for _, a in actual_pairs]
    forecast_for_actuals = [f for f, _ in actual_pairs]

    forecast_total = sum(forecast_values)
    actual_total = sum(actual_values) if actual_values else None
    forecast_metrics = ForecastScorecard(
        forecast_volume=forecast_total,
        actual_volume=actual_total,
        variance_contacts=(actual_total - forecast_total) if actual_total is not None else None,
        variance_pct=kpi_service.forecast_variance_pct(forecast_total, actual_total) if actual_total is not None else None,
        accuracy_pct=kpi_service.forecast_accuracy_pct(forecast_total, actual_total) if actual_total is not None else None,
        wape_pct=kpi_service.weighted_absolute_percentage_error_pct(forecast_for_actuals, actual_values) if actual_values else None,
        mape_pct=kpi_service.mean_absolute_percentage_error_pct(forecast_for_actuals, actual_values) if actual_values else None,
        bias_pct=kpi_service.forecast_bias_pct(forecast_for_actuals, actual_values) if actual_values else None,
    )

    required_hc_hours = sum(max(i.required_hc, 0) * INTERVAL_HOURS for i in intervals)
    scheduled_hc_hours = sum(max(i.scheduled_hc, 0) * INTERVAL_HOURS for i in intervals)
    actual_hc_values = [i.actual_hc for i in intervals if i.actual_hc is not None]
    actual_hc_hours = sum(actual_hc_values) * INTERVAL_HOURS if actual_hc_values else None
    shortage = sum(max(i.required_hc - i.scheduled_hc, 0) * INTERVAL_HOURS for i in intervals)
    surplus = sum(max(i.scheduled_hc - i.required_hc, 0) * INTERVAL_HOURS for i in intervals)
    covered = sum(min(max(i.required_hc, 0), max(i.scheduled_hc, 0)) * INTERVAL_HOURS for i in intervals)
    coverage = kpi_service.coverage_pct(required_hc_hours, covered)
    peaks_required = max((i.required_hc for i in intervals), default=0)
    peaks_scheduled = max((i.scheduled_hc for i in intervals), default=0)
    peaks_actual = max(actual_hc_values) if actual_hc_values else None
    under_count = sum(1 for i in intervals if i.required_hc - i.scheduled_hc > 0.5)
    over_count = sum(1 for i in intervals if i.scheduled_hc - i.required_hc > 0.5)
    overtime_required = shortage

    adherence_proxy = (
        kpi_service.staffing_adherence_proxy_pct(actual_hc_hours, scheduled_hc_hours)
        if actual_hc_hours is not None and scheduled_hc_hours > 0
        else None
    )

    staffing_metrics = StaffingScorecard(
        required_hc_hours=required_hc_hours,
        scheduled_hc_hours=scheduled_hc_hours,
        actual_hc_hours=actual_hc_hours,
        shortage_hc_hours=shortage,
        surplus_hc_hours=surplus,
        coverage_pct=coverage,
        peak_required_hc=peaks_required,
        peak_scheduled_hc=peaks_scheduled,
        peak_actual_hc=peaks_actual,
        understaffed_intervals=under_count,
        overstaffed_intervals=over_count,
        overtime_required_hours=overtime_required,
        staffing_adherence_proxy_pct=adherence_proxy,
    )

    actual_weights = [i.actual_volume or 0 for i in intervals]
    actual_aht = _weighted_optional([i.actual_aht_seconds for i in intervals], actual_weights)
    forecast_aht = _weighted_optional([i.forecast_aht_seconds for i in intervals], forecast_values) or 0.0
    actual_sl = _weighted_optional([i.service_level_pct for i in intervals], actual_weights)
    actual_asa = _weighted_optional([i.asa_seconds for i in intervals], actual_weights)
    actual_occupancy = _weighted_optional([i.occupancy_pct for i in intervals], actual_weights)
    abandon = _weighted_optional([i.abandon_rate_pct for i in intervals], [i.actual_volume or 0 for i in intervals])

    scheduled_sl_values = []
    scheduled_sl_weights = []
    scheduled_asa_values = []
    scheduled_asa_weights = []
    for i in intervals:
        sl, asa = _scheduled_metrics(i)
        if i.forecast_volume > 0:
            scheduled_sl_values.append(sl)
            scheduled_sl_weights.append(i.forecast_volume)
            if asa is not None:
                scheduled_asa_values.append(asa)
                scheduled_asa_weights.append(i.forecast_volume)

    scheduled_sl = kpi_service.weighted_average(scheduled_sl_values, scheduled_sl_weights) if scheduled_sl_values else 0.0
    scheduled_asa = (
        kpi_service.weighted_average(scheduled_asa_values, scheduled_asa_weights)
        if scheduled_asa_values else None
    )
    target_sl = _weighted_optional(
        [i.service_level_target_pct for i in intervals],
        forecast_values,
    ) or 0.0
    target_occ = _weighted_optional(
        [getattr(i, "occupancy_target_pct", None) for i in intervals],
        forecast_values,
    )
    # occupancy target is not stored per interval in V1; keep dashboard
    # compatible with an empty target until a future schema migration.
    target_occ = target_occ or 0.0

    workload = (
        kpi_service.workload_hours(actual_total, actual_aht)
        if actual_total is not None and actual_aht is not None
        else None
    )
    utilization = (
        kpi_service.utilization_pct(workload, scheduled_hc_hours - surplus)
        if workload is not None and scheduled_hc_hours > surplus
        else None
    )
    operations = OperationsScorecard(
        forecast_aht_seconds=forecast_aht,
        actual_aht_seconds=actual_aht,
        aht_variance_seconds=(actual_aht - forecast_aht) if actual_aht is not None else None,
        scheduled_service_level_pct=scheduled_sl,
        actual_service_level_pct=actual_sl,
        service_level_target_pct=target_sl,
        service_level_gap_pct=(actual_sl - target_sl) if actual_sl is not None else None,
        scheduled_asa_seconds=scheduled_asa,
        actual_asa_seconds=actual_asa,
        occupancy_pct=actual_occupancy,
        occupancy_target_pct=target_occ,
        occupancy_gap_pct=(actual_occupancy - target_occ) if actual_occupancy is not None and target_occ else None,
        abandon_rate_pct=abandon,
        workload_hours=workload,
        utilization_pct=utilization,
        schedule_efficiency_pct=kpi_service.schedule_efficiency_pct(required_hc_hours, scheduled_hc_hours),
    )

    alerts: list[PlannerAlert] = []
    for i in intervals:
        gap = i.required_hc - i.scheduled_hc
        if gap > 0.5:
            severity = "critical" if gap >= 2 else "warning"
            alerts.append(PlannerAlert(
                severity,
                i.interval_start,
                i.interval_end,
                "Sous-staffing",
                f"Ajouter {gap:.1f} HC sur cet intervalle pour couvrir la demande.",
                recommended_hc_delta=gap,
            ))
        elif i.scheduled_hc - i.required_hc > 1.0:
            surplus_interval = i.scheduled_hc - i.required_hc
            alerts.append(PlannerAlert(
                "info",
                i.interval_start,
                i.interval_end,
                "Sur-staffing",
                f"{surplus_interval:.1f} HC au-dessus du besoin : vérifier une libération ou une activité non modélisée.",
                recommended_hc_delta=-surplus_interval,
            ))
        if i.service_level_pct is not None and i.service_level_target_pct and i.service_level_pct < i.service_level_target_pct:
            gap_pct = i.service_level_target_pct - i.service_level_pct
            alerts.append(PlannerAlert(
                "critical" if gap_pct >= 10 else "warning",
                i.interval_start,
                i.interval_end,
                "Service Level sous cible",
                f"SL {i.service_level_pct:.1f}% vs cible {i.service_level_target_pct:.1f}%.",
            ))
        if i.occupancy_pct is not None and i.actual_hc and i.actual_hc > 0:
            # The interval itself does not store the occupancy target yet.
            if i.occupancy_pct > 95:
                alerts.append(PlannerAlert(
                    "critical",
                    i.interval_start,
                    i.interval_end,
                    "Occupancy élevée",
                    f"Occupancy {i.occupancy_pct:.1f}% : risque de saturation.",
                ))

    return WFMScorecard(forecast_metrics, staffing_metrics, operations, alerts)
