from datetime import time

import pytest

from app.models.enums import PeriodType
from app.schemas.overtime import OvertimePlanInput
from app.schemas.scheduling import ShiftInput
from app.services import kpi_service, weekly_intraday_service
from app.services.intraday_service import interval_duration_hours


def test_last_30_minute_interval_is_exactly_half_hour():
    assert interval_duration_hours(time(23, 30), time(23, 59, 59)) == pytest.approx(0.5)


def test_forecast_accuracy_is_bounded_to_zero_when_error_exceeds_actual():
    assert kpi_service.forecast_accuracy_pct(300, 100) == 0.0


def test_coverage_never_exceeds_100_percent():
    assert kpi_service.coverage_pct(10, 15) == 100.0


def test_core_hours_reject_negative_inputs():
    with pytest.raises(ValueError):
        kpi_service.paid_hours(-1, 8, 5)
    with pytest.raises(ValueError):
        kpi_service.workload_hours(100, -10)


def test_aggregate_required_hc_validates_occupancy():
    with pytest.raises(ValueError):
        kpi_service.required_hc_aggregate(100, 40, 0)


def test_default_weekday_weights_match_business_profile():
    weights = weekly_intraday_service.weekday_volume_weights()
    assert weights == pytest.approx([0.13, 0.14, 0.16, 0.17, 0.14, 0.13, 0.13])
    assert sum(weights) == pytest.approx(1.0)


def test_default_break_profile_represents_two_15_minute_breaks():
    profile = weekly_intraday_service.default_break_15m_profile_pct()
    exposure_hours = sum(profile) / 100.0 * 0.5
    assert exposure_hours == pytest.approx(0.5)


def test_default_lunch_profile_represents_60_minutes():
    profile = weekly_intraday_service.default_lunch_break_profile_pct()
    exposure_hours = sum(profile) / 100.0 * 0.5
    assert exposure_hours == pytest.approx(1.0)


def test_overtime_periods_match_selected_granularity():
    assert OvertimePlanInput(
        start_date="2026-09-15",
        end_date="2026-09-15",
        campaign_id=1,
        skill_id=1,
        period_type=PeriodType.DAILY,
    ).period_type == PeriodType.DAILY

    with pytest.raises(ValueError):
        OvertimePlanInput(
            start_date="2026-09-15",
            end_date="2026-09-16",
            campaign_id=1,
            skill_id=1,
            period_type=PeriodType.DAILY,
        )

    with pytest.raises(ValueError):
        OvertimePlanInput(
            start_date="2026-09-16",
            end_date="2026-09-22",
            campaign_id=1,
            skill_id=1,
            period_type=PeriodType.WEEKLY,
        )


def test_zero_length_shift_is_rejected():
    with pytest.raises(ValueError):
        ShiftInput(name="Invalid", start_time="09:00", end_time="09:00")
