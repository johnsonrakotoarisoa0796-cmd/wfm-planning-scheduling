from datetime import date, time

import pytest

from app.models.intraday import IntervalForecast
from app.models.shift import Shift
from app.services.kpi_service import (
    forecast_bias_pct,
    forecast_accuracy_wape_pct,
    mean_absolute_percentage_error_pct,
    schedule_adherence_pct,
    weighted_absolute_percentage_error_pct,
)
from app.services.planner_service import recommend_shift_mix
from app.services.wfm_metrics_service import build_scorecard


def test_wape_and_bias_are_stable():
    forecast = [100, 120, 80]
    actual = [110, 100, 90]
    assert weighted_absolute_percentage_error_pct(forecast, actual) == pytest.approx(13.33, abs=0.01)
    assert forecast_bias_pct(forecast, actual) == pytest.approx(0.0, abs=0.01)
    assert forecast_accuracy_wape_pct(forecast, actual) == pytest.approx(86.67, abs=0.01)


def test_mape_ignores_zero_actual_periods():
    assert mean_absolute_percentage_error_pct([100, 20], [100, 0]) == pytest.approx(0.0)


def test_schedule_adherence():
    assert schedule_adherence_pct(36, 40) == pytest.approx(90.0)


def test_scorecard_distinguishes_shortage_from_surplus():
    intervals = [
        IntervalForecast(
            date=date(2026, 9, 19), interval_start=time(10, 0), interval_end=time(10, 30),
            campaign_id=1, skill_id=1, forecast_volume=100, actual_volume=110,
            forecast_aht_seconds=300, actual_aht_seconds=320, required_hc=10,
            scheduled_hc=8, actual_hc=7, service_level_target_pct=80, answer_time_target_seconds=20,
            service_level_pct=72, occupancy_pct=92, abandon_rate_pct=5,
        ),
        IntervalForecast(
            date=date(2026, 9, 19), interval_start=time(10, 30), interval_end=time(11, 0),
            campaign_id=1, skill_id=1, forecast_volume=80, actual_volume=75,
            forecast_aht_seconds=300, actual_aht_seconds=290, required_hc=8,
            scheduled_hc=9, actual_hc=9, service_level_target_pct=80, answer_time_target_seconds=20,
            service_level_pct=84, occupancy_pct=84, abandon_rate_pct=2,
        ),
    ]
    scorecard = build_scorecard(intervals, occupancy_target_pct=85, aht_target_seconds=300)
    assert scorecard.staffing.shortage_hc_hours == pytest.approx(1.0)
    assert scorecard.staffing.surplus_hc_hours == pytest.approx(0.5)
    assert scorecard.staffing.understaffed_intervals == 1
    assert scorecard.forecast.actual_volume == 185
    assert scorecard.operations.actual_aht_seconds == pytest.approx((110*320 + 75*290) / 185, abs=0.01)
    assert scorecard.alerts


def test_planner_prefers_shift_covering_the_shortage():
    intervals = [
        IntervalForecast(
            date=date(2026, 9, 19), interval_start=time(10, 0), interval_end=time(10, 30),
            campaign_id=1, skill_id=1, forecast_volume=100, forecast_aht_seconds=300,
            required_hc=10, scheduled_hc=8,
        )
    ]
    morning = Shift(name="09-18", start_time=time(9, 0), end_time=time(18, 0), break_minutes=15, lunch_minutes=60)
    night = Shift(name="20-05", start_time=time(20, 0), end_time=time(5, 0), break_minutes=15, lunch_minutes=60)
    recs = recommend_shift_mix(intervals, [morning, night], max_agents=3)
    assert len(recs) == 1
    assert recs[0].shift_name == "09-18"
    assert recs[0].headcount == 2
