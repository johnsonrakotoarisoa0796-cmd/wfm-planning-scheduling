from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from app.models.employee import Employee, EmployeeAbsence
from app.models.enums import EmployeeStatus
from app.models.shift import Shift
from app.services.intraday_service import profile_for_operating_window
from app.services.workforce_service import (
    daily_contract_hours,
    expected_shift_elapsed_hours,
    is_dst,
    seasonal_operating_window,
    shift_hours,
)


def _employee(**kwargs):
    base = dict(
        employee_code="EMP-WF-1",
        first_name="Test",
        last_name="Agent",
        campaign_id=1,
        hire_date=date(2025, 1, 1),
        status=EmployeeStatus.ACTIVE,
        weekly_hours_contract=40.0,
        timezone_name="America/New_York",
    )
    base.update(kwargs)
    return Employee(**base)


def test_40_hours_week_is_8_hours_per_day():
    assert daily_contract_hours(_employee()) == pytest.approx(8.0)


def test_paid_breaks_are_inside_8_paid_hours():
    shift = Shift(
        name="07-16",
        start_time=time(7, 0),
        end_time=time(16, 0),
        break_minutes=15,
        break_count=2,
        break_paid=True,
        lunch_minutes=60,
        lunch_paid=False,
    )
    result = shift_hours(shift, contract_daily_hours=8)
    assert result.elapsed_hours == pytest.approx(9.0)
    assert result.paid_hours == pytest.approx(8.0)
    assert result.unpaid_break_hours == 0.0
    assert result.unpaid_lunch_hours == pytest.approx(1.0)
    assert result.overtime_hours == 0.0


def test_unpaid_breaks_extend_elapsed_day_without_creating_paid_hours():
    shift = Shift(
        name="07-1630",
        start_time=time(7, 0),
        end_time=time(16, 30),
        break_minutes=15,
        break_count=2,
        break_paid=False,
        lunch_minutes=60,
        lunch_paid=False,
    )
    result = shift_hours(shift, contract_daily_hours=8)
    assert result.elapsed_hours == pytest.approx(9.5)
    assert result.paid_hours == pytest.approx(8.0)
    assert result.unpaid_break_hours == pytest.approx(0.5)
    assert result.unpaid_lunch_hours == pytest.approx(1.0)


def test_expected_amplitude_changes_when_breaks_are_unpaid():
    assert expected_shift_elapsed_hours(break_paid=True) == pytest.approx(9.0)
    assert expected_shift_elapsed_hours(break_paid=False) == pytest.approx(9.5)


def test_dst_controls_summer_and_winter_operating_windows():
    assert is_dst(date(2026, 7, 1), "America/New_York") is True
    assert is_dst(date(2026, 1, 15), "America/New_York") is False

    summer = seasonal_operating_window(date(2026, 7, 1), "America/New_York")
    winter = seasonal_operating_window(date(2026, 1, 15), "America/New_York")
    assert summer.start_local == time(7, 0)
    assert summer.end_local == time(1, 0)
    assert winter.start_local == time(8, 0)
    assert winter.end_local == time(2, 0)


def test_operating_window_is_timezone_aware_and_crosses_midnight():
    window = seasonal_operating_window(date(2026, 7, 1), "America/New_York")
    assert window.start_utc.tzinfo == ZoneInfo("UTC")
    assert window.end_utc > window.start_utc


def test_intraday_profile_is_zero_outside_operating_window():
    profile = profile_for_operating_window(date(2026, 7, 1), "America/New_York")
    assert len(profile) == 48
    assert sum(profile) == pytest.approx(100.0)
    assert profile[0] > 0      # 00:00-00:30 remains open in summer
    assert profile[2] == pytest.approx(0.0)  # 01:00-01:30 is closed
    assert profile[6] == pytest.approx(0.0)  # 03:00-03:30 is closed
    assert profile[14] > 0     # 07:00-07:30 is open


def test_absence_model_preserves_paid_vs_unpaid_rule():
    paid = EmployeeAbsence(
        employee_id=1,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        absence_type="paid_leave",
        paid=True,
    )
    unpaid = EmployeeAbsence(
        employee_id=1,
        start_date=date(2026, 9, 8),
        end_date=date(2026, 9, 12),
        absence_type="unpaid_leave",
        paid=False,
    )
    assert paid.paid is True
    assert unpaid.paid is False
