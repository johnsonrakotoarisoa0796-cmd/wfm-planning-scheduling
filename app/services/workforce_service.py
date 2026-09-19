"""Règles Workforce : contrat, pauses, absences, fuseaux et fenêtres opérationnelles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.models.employee import Employee, EmployeeAbsence
from app.models.shift import Shift

settings = get_settings()

DEFAULT_BREAK_COUNT = 2
DEFAULT_BREAK_MINUTES = 15
DEFAULT_LUNCH_MINUTES = 60
DEFAULT_DAILY_CONTRACT_HOURS = 8.0


@dataclass(frozen=True)
class WorkdayRule:
    weekly_contract_hours: float
    working_days_per_week: int
    daily_contract_hours: float
    lunch_minutes: int
    break_count: int
    break_minutes: int
    break_paid: bool
    lunch_paid: bool


@dataclass(frozen=True)
class ShiftHours:
    elapsed_hours: float
    paid_hours: float
    unpaid_break_hours: float
    unpaid_lunch_hours: float
    regular_paid_hours: float
    overtime_hours: float


@dataclass(frozen=True)
class SeasonalWindow:
    timezone_name: str
    start_local: time
    end_local: time
    start_utc: datetime
    end_utc: datetime


def validate_timezone_name(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Fuseau horaire IANA inconnu: {timezone_name}") from exc
    return timezone_name


def daily_contract_hours(employee: Employee, working_days_per_week: int | None = None) -> float:
    days = working_days_per_week or settings.working_days
    if days <= 0:
        raise ValueError("working_days_per_week doit être positif.")
    return employee.weekly_hours_contract / days


def shift_elapsed_hours(shift: Shift) -> float:
    start = datetime.combine(date(2000, 1, 1), shift.start_time)
    end_date = date(2000, 1, 1) if shift.end_time > shift.start_time else date(2000, 1, 2)
    end = datetime.combine(end_date, shift.end_time)
    return max(0.0, (end - start).total_seconds() / 3600)


def shift_hours(
    shift: Shift,
    *,
    contract_daily_hours: float = DEFAULT_DAILY_CONTRACT_HOURS,
) -> ShiftHours:
    elapsed = shift_elapsed_hours(shift)
    unpaid_break_hours = (
        0.0 if shift.break_paid
        else shift.break_count * shift.break_minutes / 60
    )
    unpaid_lunch_hours = 0.0 if shift.lunch_paid else shift.lunch_minutes / 60
    paid_hours = max(0.0, elapsed - unpaid_break_hours - unpaid_lunch_hours)
    regular_paid_hours = min(paid_hours, contract_daily_hours)
    overtime_hours = max(0.0, paid_hours - contract_daily_hours)
    return ShiftHours(
        elapsed_hours=elapsed,
        paid_hours=paid_hours,
        unpaid_break_hours=unpaid_break_hours,
        unpaid_lunch_hours=unpaid_lunch_hours,
        regular_paid_hours=regular_paid_hours,
        overtime_hours=overtime_hours,
    )


def expected_shift_elapsed_hours(
    *,
    contract_daily_hours: float = DEFAULT_DAILY_CONTRACT_HOURS,
    break_minutes: int = DEFAULT_BREAK_MINUTES,
    break_count: int = DEFAULT_BREAK_COUNT,
    break_paid: bool = True,
    lunch_minutes: int = DEFAULT_LUNCH_MINUTES,
    lunch_paid: bool = False,
) -> float:
    """Amplitude minimale correspondant au contrat.

    Avec 8h de travail + 1h déjeuner :
    - pauses payées: 9h d'amplitude (ex: 07:00 -> 16:00)
    - pauses non payées: 9h30 d'amplitude (ex: 07:00 -> 16:30)
    """
    unpaid_break = 0 if break_paid else break_minutes * break_count
    unpaid_lunch = 0 if lunch_paid else lunch_minutes
    return contract_daily_hours + (unpaid_break + unpaid_lunch) / 60


def absence_overlaps_date(absence: EmployeeAbsence, target_date: date) -> bool:
    return absence.start_date <= target_date <= absence.end_date


def is_employee_absent(absences: list[EmployeeAbsence], target_date: date) -> bool:
    return any(absence_overlaps_date(a, target_date) for a in absences)


def absence_paid_hours(
    employee: Employee,
    absence: EmployeeAbsence,
    target_date: date,
    *,
    working_days_per_week: int | None = None,
) -> float:
    if not absence_paid_on_date(absence, target_date):
        return 0.0
    return daily_contract_hours(employee, working_days_per_week)


def absence_paid_on_date(absence: EmployeeAbsence, target_date: date) -> bool:
    return absence_overlaps_date(absence, target_date) and absence.paid


def validate_absence_type(value: str) -> str:
    allowed = {"maternity", "availability", "paid_leave", "unpaid_leave"}
    if value not in allowed:
        raise ValueError(f"absence_type doit être l'un de: {', '.join(sorted(allowed))}")
    return value


def _parse_local_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":")[:2])
    return time(hour, minute)


def is_dst(target_date: date, timezone_name: str) -> bool:
    validate_timezone_name(timezone_name)
    tz = ZoneInfo(timezone_name)
    noon = datetime(target_date.year, target_date.month, target_date.day, 12, tzinfo=tz)
    return bool(noon.dst() and noon.dst() != timedelta(0))


def seasonal_operating_window(
    target_date: date,
    timezone_name: str,
    *,
    summer_start: str | None = None,
    summer_end: str | None = None,
    winter_start: str | None = None,
    winter_end: str | None = None,
) -> SeasonalWindow:
    timezone_name = validate_timezone_name(timezone_name)
    tz = ZoneInfo(timezone_name)

    summer = is_dst(target_date, timezone_name)
    start_local = _parse_local_time(
        summer_start or settings.summer_operating_start
        if summer else winter_start or settings.winter_operating_start
    )
    end_local = _parse_local_time(
        summer_end or settings.summer_operating_end
        if summer else winter_end or settings.winter_operating_end
    )

    start = datetime.combine(target_date, start_local, tzinfo=tz)
    end_date = target_date if end_local > start_local else target_date + timedelta(days=1)
    end = datetime.combine(end_date, end_local, tzinfo=tz)
    return SeasonalWindow(
        timezone_name=timezone_name,
        start_local=start_local,
        end_local=end_local,
        start_utc=start.astimezone(ZoneInfo("UTC")),
        end_utc=end.astimezone(ZoneInfo("UTC")),
    )


def local_interval_to_utc(
    target_date: date,
    start_local: time,
    end_local: time,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    tz_name = validate_timezone_name(timezone_name)
    tz = ZoneInfo(tz_name)
    start = datetime.combine(target_date, start_local, tzinfo=tz)
    end_date = target_date if end_local > start_local else target_date + timedelta(days=1)
    end = datetime.combine(end_date, end_local, tzinfo=tz)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))
