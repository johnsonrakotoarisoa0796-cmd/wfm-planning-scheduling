"""Automatic WFM schedule generation inspired by Teleopti-style scheduling."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import EmployeeStatus
from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.services import client_stf_service, compliance_service, intraday_service, scheduling_service, workforce_service

settings = get_settings()


@dataclass(frozen=True)
class GeneratedEntry:
    employee: Employee
    entry: ScheduleEntry
    shift: Shift


@dataclass(frozen=True)
class CoverageSummary:
    target_date: date
    required_hc_hours: float
    scheduled_hc_hours: float
    shortage_hc_hours: float
    coverage_pct: float


@dataclass(frozen=True)
class ScheduleGenerationResult:
    week_start_date: date
    week_end_date: date
    entries: list[GeneratedEntry]
    coverage: list[CoverageSummary]
    warnings: list[str]


def _weekdays(week_start_date: date) -> list[date]:
    """Les forecasts intraday couvrent les 7 jours calendaires de la semaine."""
    return [week_start_date + timedelta(days=i) for i in range(7)]


def _eligible_employees(session: Session, *, campaign_id: int, skill_id: int, week_start_date: date) -> list[Employee]:
    week_end = week_start_date + timedelta(days=6)
    employee_ids = {
        row.employee_id
        for row in session.exec(select(EmployeeSkill).where(EmployeeSkill.skill_id == skill_id)).all()
    }
    employees = list(
        session.exec(
            select(Employee)
            .where(Employee.campaign_id == campaign_id)
            .where(Employee.status == EmployeeStatus.ACTIVE)
            .order_by(Employee.last_name, Employee.first_name)
        ).all()
    )
    return [
        employee
        for employee in employees
        if employee.id in employee_ids
        and employee.hire_date <= week_end
        and (employee.termination_date is None or employee.termination_date >= week_start_date)
    ]


def _absence_map(session: Session, employees: list[Employee], week_start_date: date) -> dict[int, list[EmployeeAbsence]]:
    week_end = week_start_date + timedelta(days=6)
    employee_ids = [employee.id for employee in employees]
    if not employee_ids:
        return {}
    rows = list(
        session.exec(
            select(EmployeeAbsence)
            .where(EmployeeAbsence.employee_id.in_(employee_ids))
            .where(EmployeeAbsence.start_date <= week_end)
            .where(EmployeeAbsence.end_date >= week_start_date)
        ).all()
    )
    result: dict[int, list[EmployeeAbsence]] = {}
    for row in rows:
        result.setdefault(row.employee_id, []).append(row)
    return result


def _target_hours(employee: Employee, absences: list[EmployeeAbsence], week_start_date: date) -> float:
    _, paid_absence, unpaid_absence = workforce_service.workforce_period_hours(
        employee,
        absences,
        start_date=week_start_date,
        end_date=week_start_date + timedelta(days=6),
    )
    return max(0.0, employee.weekly_hours_contract - paid_absence - unpaid_absence)


def _generate_activities(shift: Shift) -> tuple[time | None, time | None, time | None, time | None, time | None, time | None]:
    elapsed_minutes = int(round(workforce_service.shift_elapsed_hours(shift) * 60))
    if elapsed_minutes <= 0:
        return (None, None, None, None, None, None)

    start_minutes = shift.start_time.hour * 60 + shift.start_time.minute

    def at(offset: int) -> time:
        minute = (start_minutes + offset) % (24 * 60)
        return time(minute // 60, minute % 60)

    def pair(offset: int, duration: int) -> tuple[time, time]:
        return at(offset), at(offset + duration)

    break_len = max(shift.break_minutes, 0)
    lunch_len = max(shift.lunch_minutes, 0)
    b1_offset = max(75, int(elapsed_minutes * 0.27))
    lunch_offset = int(elapsed_minutes * 0.50)
    b2_offset = int(elapsed_minutes * 0.76)

    b1 = pair(b1_offset, break_len) if shift.break_count >= 1 and break_len else (None, None)
    b2 = pair(b2_offset, break_len) if shift.break_count >= 2 and break_len else (None, None)
    lunch = pair(lunch_offset, lunch_len) if lunch_len else (None, None)
    return b1[0], b1[1], b2[0], b2[1], lunch[0], lunch[1]


def _interval_rows(session: Session, *, target_date: date, campaign_id: int, skill_id: int):
    raw = intraday_service.list_intervals_for_day(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    plan = client_stf_service.current_plan(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    if plan is None:
        return raw
    return client_stf_service.effective_intervals(
        raw, client_stf_service.list_intervals(session, plan.id)
    )


def _shift_productive_in_interval(shift: Shift, interval, entry_date: date) -> bool:
    if not scheduling_service._shift_covers_interval(
        shift, interval.interval_start, interval.interval_end
    ):
        return False
    b1s, b1e, b2s, b2e, ls, le = _generate_activities(shift)
    return not any(
        scheduling_service._overlaps(start, end, interval.interval_start, interval.interval_end)
        for start, end in ((b1s, b1e), (b2s, b2e), (ls, le))
    )


def _shift_gain(shift: Shift, intervals, current_hc: dict[time, float]) -> tuple[float, float]:
    gain = 0.0
    surplus_penalty = 0.0
    for row in intervals:
        if _shift_productive_in_interval(shift, row, row.date):
            shortage = max(row.required_hc - current_hc.get(row.interval_start, 0.0), 0.0)
            gain += min(shortage, 1.0)
            surplus_penalty += max(current_hc.get(row.interval_start, 0.0) - row.required_hc, 0.0) * 0.15
    return gain, surplus_penalty


def _choose_shift(shifts: list[Shift], intervals, current_hc: dict[time, float], remaining_hours: float, employee: Employee) -> Shift:
    ranked = []
    for shift in shifts:
        paid = workforce_service.shift_hours(shift, contract_daily_hours=workforce_service.daily_contract_hours(employee)).paid_hours
        if paid <= 0:
            continue
        gain, penalty = _shift_gain(shift, intervals, current_hc)
        fit = abs(remaining_hours - paid)
        ranked.append((gain * 10.0 - penalty - fit * 0.05, gain, -fit, shift))
    if not ranked:
        raise ValueError("Aucun shift actif exploitable.")
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3]


def _build_entry(employee: Employee, target_date: date, campaign_id: int, skill_id: int, shift: Shift) -> ScheduleEntry:
    b1s, b1e, b2s, b2e, ls, le = _generate_activities(shift)
    return ScheduleEntry(
        employee_id=employee.id,
        date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
        is_day_off=False,
        shift_id=shift.id,
        break_start=b1s,
        break_end=b1e,
        break2_start=b2s,
        break2_end=b2e,
        lunch_start=ls,
        lunch_end=le,
    )


def _apply_coverage(entry: ScheduleEntry, shift: Shift, intervals, current_hc: dict[time, float]) -> None:
    for row in intervals:
        if _shift_productive_in_interval(shift, row, entry.date):
            current_hc[row.interval_start] = current_hc.get(row.interval_start, 0.0) + 1.0


def generate_schedule(
    session: Session,
    *,
    week_start_date: date,
    campaign_id: int,
    skill_id: int,
    replace_existing: bool = False,
) -> ScheduleGenerationResult:
    if week_start_date.weekday() != 0:
        raise ValueError("La semaine de planification doit commencer un lundi.")

    days = _weekdays(week_start_date)
    employees = _eligible_employees(
        session, campaign_id=campaign_id, skill_id=skill_id, week_start_date=week_start_date
    )
    if not employees:
        raise ValueError("Aucun agent actif éligible sur ce skill.")

    shifts = scheduling_service.list_shifts(session, active_only=True)
    if not shifts:
        raise ValueError("Aucun shift actif. Configurez d'abord vos gabarits.")

    intervals_by_day = {
        day: _interval_rows(session, target_date=day, campaign_id=campaign_id, skill_id=skill_id)
        for day in days
    }
    missing = [day for day, rows in intervals_by_day.items() if not rows]
    if missing:
        raise ValueError(
            "Forecast Daily/Intraday manquant pour: "
            + ", ".join(day.isoformat() for day in missing)
        )

    existing = list(
        session.exec(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.date >= week_start_date,
                ScheduleEntry.date <= week_start_date + timedelta(days=6),
                ScheduleEntry.campaign_id == campaign_id,
                ScheduleEntry.skill_id == skill_id,
            )
        ).all()
    )
    if existing and not replace_existing:
        raise ValueError(
            "Un planning existe déjà sur cette semaine. "
            "Activez 'Remplacer le planning existant' pour régénérer."
        )
    if replace_existing:
        for row in existing:
            session.delete(row)
        session.flush()

    absences = _absence_map(session, employees, week_start_date)
    targets = {e.id: _target_hours(e, absences.get(e.id, []), week_start_date) for e in employees}
    scheduled_hours = {e.id: 0.0 for e in employees}
    assigned_days: dict[int, set[date]] = {e.id: set() for e in employees}
    generated: list[GeneratedEntry] = []
    warnings: list[str] = []
    compliance_policy = compliance_service.get_policy(
        session, campaign_id=campaign_id, skill_id=skill_id
    )
    assigned_intervals: dict[int, list[tuple[datetime, datetime]]] = {
        employee.id: [] for employee in employees
    }

    # Teleopti-style priority: cover the forecast deficit first, while
    # rotating agents so contract hours are distributed across the week.
    for day in days:
        intervals = intervals_by_day[day]
        current_hc = {row.interval_start: 0.0 for row in intervals}
        for _ in range(len(employees)):
            shortage = sum(
                max(row.required_hc - current_hc.get(row.interval_start, 0.0), 0.0)
                for row in intervals
            )
            candidates = []
            for employee in employees:
                if day in assigned_days[employee.id]:
                    continue
                if workforce_service.is_employee_absent(absences.get(employee.id, []), day):
                    continue
                remaining = targets[employee.id] - scheduled_hours[employee.id]
                if remaining <= 0.1:
                    continue
                shift = _choose_shift(shifts, intervals, current_hc, remaining, employee)
                paid = workforce_service.shift_hours(shift, contract_daily_hours=workforce_service.daily_contract_hours(employee)).paid_hours
                if compliance_policy is not None:
                    compliance_errors = compliance_service.validate_schedule_candidate(
                        session,
                        policy=compliance_policy,
                        employee=employee,
                        shift=shift,
                        target_date=day,
                        assigned_dates=assigned_days[employee.id],
                        scheduled_hours=scheduled_hours[employee.id],
                    )
                    candidate_start = datetime.combine(day, shift.start_time)
                    candidate_end_date = day if shift.end_time > shift.start_time else day + timedelta(days=1)
                    candidate_end = datetime.combine(candidate_end_date, shift.end_time)
                    compliance_errors.extend(
                        compliance_service.validate_candidate_rest(
                            existing_intervals=assigned_intervals[employee.id],
                            candidate_start=candidate_start,
                            candidate_end=candidate_end,
                            min_rest_hours=compliance_policy.min_rest_hours,
                        )
                    )
                    if compliance_errors:
                        continue
                gain, penalty = _shift_gain(shift, intervals, current_hc)
                balance = 1.0 / (1 + len(assigned_days[employee.id]))
                fairness = remaining / max(targets[employee.id], 1.0)
                score = gain * 10 - penalty + balance + fairness * 2 - max(paid - remaining, 0) * 0.5
                candidates.append((score, gain, employee, shift, paid))
            if not candidates:
                break
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            _, gain, employee, shift, paid = candidates[0]
            if shortage > 0.05 or gain > 0:
                entry = _build_entry(employee, day, campaign_id, skill_id, shift)
                generated.append(GeneratedEntry(employee, entry, shift))
                assigned_days[employee.id].add(day)
                scheduled_hours[employee.id] += paid
                if compliance_policy is not None:
                    candidate_start = datetime.combine(day, shift.start_time)
                    candidate_end_date = day if shift.end_time > shift.start_time else day + timedelta(days=1)
                    candidate_end = datetime.combine(candidate_end_date, shift.end_time)
                    assigned_intervals[employee.id].append((candidate_start, candidate_end))
                _apply_coverage(entry, shift, intervals, current_hc)
            else:
                break

        remaining_shortage = sum(
            max(row.required_hc - current_hc.get(row.interval_start, 0.0), 0.0)
            for row in intervals
        )
        if remaining_shortage > 0.05:
            warnings.append(f"{day.isoformat()}: {remaining_shortage:.1f} HC moyen reste à couvrir.")

    # Contract fill phase: complete remaining paid hours on the days with the
    # lowest current surplus, still respecting absences and one shift/day.
    for employee in employees:
        remaining = targets[employee.id] - scheduled_hours[employee.id]
        for day in days:
            if remaining <= 0.5:
                break
            if day in assigned_days[employee.id]:
                continue
            if workforce_service.is_employee_absent(absences.get(employee.id, []), day):
                continue
            intervals = intervals_by_day[day]
            current_hc = {
                row.interval_start: sum(
                    1
                    for item in generated
                    if item.entry.date == day
                    and scheduling_service._shift_covers_interval(
                        item.shift, row.interval_start, row.interval_end
                    )
                )
                for row in intervals
            }
            shift = _choose_shift(shifts, intervals, current_hc, remaining, employee)
            paid = workforce_service.shift_hours(shift, contract_daily_hours=workforce_service.daily_contract_hours(employee)).paid_hours
            if paid > remaining + 1.0 and remaining < 4.0:
                continue
            if compliance_policy is not None:
                compliance_errors = compliance_service.validate_schedule_candidate(
                    session,
                    policy=compliance_policy,
                    employee=employee,
                    shift=shift,
                    target_date=day,
                    assigned_dates=assigned_days[employee.id],
                    scheduled_hours=scheduled_hours[employee.id],
                )
                candidate_start = datetime.combine(day, shift.start_time)
                candidate_end_date = day if shift.end_time > shift.start_time else day + timedelta(days=1)
                candidate_end = datetime.combine(candidate_end_date, shift.end_time)
                compliance_errors.extend(
                    compliance_service.validate_candidate_rest(
                        existing_intervals=assigned_intervals[employee.id],
                        candidate_start=candidate_start,
                        candidate_end=candidate_end,
                        min_rest_hours=compliance_policy.min_rest_hours,
                    )
                )
                if compliance_errors:
                    continue
            entry = _build_entry(employee, day, campaign_id, skill_id, shift)
            generated.append(GeneratedEntry(employee, entry, shift))
            assigned_days[employee.id].add(day)
            scheduled_hours[employee.id] += paid
            if compliance_policy is not None:
                candidate_start = datetime.combine(day, shift.start_time)
                candidate_end_date = day if shift.end_time > shift.start_time else day + timedelta(days=1)
                candidate_end = datetime.combine(candidate_end_date, shift.end_time)
                assigned_intervals[employee.id].append((candidate_start, candidate_end))
            remaining -= paid
        if targets[employee.id] - scheduled_hours[employee.id] > 0.75:
            warnings.append(
                f"{employee.first_name} {employee.last_name}: "
                f"{targets[employee.id] - scheduled_hours[employee.id]:.1f} h non planifiées."
            )

    # Persist explicit day-off entries so the weekly schedule is complete and
    # can be viewed/edited from the normal Scheduling screen.
    for employee in employees:
        for day in days:
            if day in assigned_days[employee.id]:
                continue
            if workforce_service.is_employee_absent(absences.get(employee.id, []), day):
                continue
            generated.append(
                GeneratedEntry(
                    employee,
                    ScheduleEntry(
                        employee_id=employee.id,
                        date=day,
                        campaign_id=campaign_id,
                        skill_id=skill_id,
                        is_day_off=True,
                    ),
                    shifts[0],
                )
            )

    session.add_all([row.entry for row in generated])
    session.commit()
    for day in days:
        scheduling_service.refresh_interval_scheduled_hc(
            session,
            target_date=day,
            campaign_id=campaign_id,
            skill_id=skill_id,
        )

    coverage: list[CoverageSummary] = []
    for day in days:
        intervals = intervals_by_day[day]
        required_h = sum(max(row.required_hc, 0.0) * settings.interval_minutes / 60 for row in intervals)
        scheduled_h = sum(
            settings.interval_minutes / 60
            for item in generated
            if item.entry.date == day
            for row in intervals
            if not item.entry.is_day_off
            and _shift_productive_in_interval(item.shift, row, day)
        )
        covered_h = sum(
            min(
                max(row.required_hc, 0.0),
                sum(
                    1
                    for item in generated
                    if item.entry.date == day
                    and not item.entry.is_day_off
                    and _shift_productive_in_interval(item.shift, row, day)
                ),
            ) * settings.interval_minutes / 60
            for row in intervals
        )
        coverage.append(
            CoverageSummary(
                target_date=day,
                required_hc_hours=required_h,
                scheduled_hc_hours=scheduled_h,
                shortage_hc_hours=max(required_h - covered_h, 0.0),
                coverage_pct=min(100.0, covered_h / required_h * 100.0) if required_h else 100.0,
            )
        )

    if compliance_policy is not None:
        total_required = sum(item.required_hc_hours for item in coverage)
        total_shortage = sum(item.shortage_hc_hours for item in coverage)
        weekly_coverage_pct = (
            max(0.0, (total_required - total_shortage) / total_required * 100.0)
            if total_required else 100.0
        )
        if weekly_coverage_pct < compliance_policy.weekly_coverage_target_pct:
            warnings.append(
                f"Weekly Coverage {weekly_coverage_pct:.1f}% < cible "
                f"{compliance_policy.weekly_coverage_target_pct:.1f}%."
            )

    return ScheduleGenerationResult(
        week_start_date=week_start_date,
        week_end_date=week_start_date + timedelta(days=6),
        entries=generated,
        coverage=coverage,
        warnings=warnings,
    )
