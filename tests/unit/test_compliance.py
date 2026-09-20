"""Tests du moteur Compliance WFM."""
from datetime import date, datetime, time

import pytest

from app.models.compliance import CompliancePolicy
from app.models.employee import Employee
from app.models.enums import EmployeeStatus
from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.schemas.compliance import CompliancePolicyInput
from app.services import compliance_service


def _employee() -> Employee:
    return Employee(
        id=1,
        employee_code="CMP001",
        first_name="Agent",
        last_name="Compliance",
        campaign_id=1,
        hire_date=date(2026, 1, 1),
        status=EmployeeStatus.ACTIVE,
        weekly_hours_contract=40,
    )


def _policy() -> CompliancePolicy:
    return CompliancePolicy(
        id=1,
        campaign_id=1,
        max_consecutive_work_days=5,
        max_daily_hours=8,
        max_weekly_hours=40,
        max_weekly_overtime_hours=2,
        min_rest_hours=11,
        weekly_coverage_target_pct=95,
    )


def test_compliance_policy_validates_relationship_between_limits():
    with pytest.raises(ValueError):
        CompliancePolicyInput(
            campaign_id=1,
            max_daily_hours=10,
            max_weekly_hours=8,
        )


def test_candidate_rejects_weekly_overtime_limit():
    employee = _employee()
    shift = Shift(
        id=1,
        name="Long",
        start_time=time(8, 0),
        end_time=time(17, 0),
        break_minutes=0,
        break_count=0,
        lunch_minutes=0,
        lunch_paid=True,
    )
    errors = compliance_service.validate_schedule_candidate(
        None,
        policy=_policy(),
        employee=employee,
        shift=shift,
        target_date=date(2026, 9, 21),
        assigned_dates={date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)},
        scheduled_hours=40,
    )
    assert any("OT" in error for error in errors)


def test_candidate_rest_rejects_less_than_minimum():
    errors = compliance_service.validate_candidate_rest(
        existing_intervals=[
            (datetime(2026, 9, 21, 8, 0), datetime(2026, 9, 21, 16, 0))
        ],
        candidate_start=datetime(2026, 9, 22, 1, 0),
        candidate_end=datetime(2026, 9, 22, 9, 0),
        min_rest_hours=11,
    )
    assert errors
    assert "Repos" in errors[0]


def test_candidate_rest_accepts_compliant_gap():
    errors = compliance_service.validate_candidate_rest(
        existing_intervals=[
            (datetime(2026, 9, 21, 8, 0), datetime(2026, 9, 21, 16, 0))
        ],
        candidate_start=datetime(2026, 9, 22, 3, 0),
        candidate_end=datetime(2026, 9, 22, 11, 0),
        min_rest_hours=11,
    )
    assert errors == []


def test_candidate_rejects_too_many_consecutive_days():
    employee = _employee()
    shift = Shift(
        id=2,
        name="Standard",
        start_time=time(8, 0),
        end_time=time(16, 0),
        break_minutes=0,
        break_count=0,
        lunch_minutes=0,
        lunch_paid=True,
    )
    errors = compliance_service.validate_schedule_candidate(
        None,
        policy=_policy(),
        employee=employee,
        shift=shift,
        target_date=date(2026, 9, 21),
        assigned_dates={
            date(2026, 9, 18),
            date(2026, 9, 19),
            date(2026, 9, 20),
            date(2026, 9, 22),
            date(2026, 9, 23),
        },
        scheduled_hours=24,
    )
    assert any("consécutifs" in error for error in errors)
