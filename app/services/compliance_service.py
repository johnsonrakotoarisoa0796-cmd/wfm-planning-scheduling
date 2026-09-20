"""Moteur Compliance : règles sociales, repos et couverture hebdomadaire."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.core.time_utils import utc_now
from app.models.campaign import Campaign
from app.models.compliance import CompliancePolicy
from app.models.employee import Employee, EmployeeAbsence
from app.models.enums import EmployeeStatus
from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.models.skill import Skill
from app.schemas.compliance import CompliancePolicyInput
from app.services import client_stf_service, intraday_service, workforce_service


@dataclass(frozen=True)
class ComplianceViolation:
    employee_id: Optional[int]
    employee_name: Optional[str]
    rule: str
    detail: str
    severity: str = "critical"


@dataclass(frozen=True)
class WeeklyCoverage:
    required_hc_hours: float
    covered_hc_hours: float
    shortage_hc_hours: float
    surplus_hc_hours: float
    coverage_pct: float
    target_pct: float
    gap_to_target_pct: float


@dataclass(frozen=True)
class ComplianceReport:
    week_start_date: date
    week_end_date: date
    policy: CompliancePolicy
    violations: list[ComplianceViolation] = field(default_factory=list)
    weekly_coverage: Optional[WeeklyCoverage] = None
    compliant: bool = True


def get_policy(
    session: Session,
    *,
    campaign_id: int,
    skill_id: Optional[int] = None,
) -> Optional[CompliancePolicy]:
    if skill_id is not None:
        exact = session.exec(
            select(CompliancePolicy)
            .where(
                CompliancePolicy.campaign_id == campaign_id,
                CompliancePolicy.skill_id == skill_id,
                CompliancePolicy.is_active == True,  # noqa: E712
            )
            .order_by(CompliancePolicy.updated_at.desc())
        ).first()
        if exact is not None:
            return exact
    return session.exec(
        select(CompliancePolicy)
        .where(
            CompliancePolicy.campaign_id == campaign_id,
            CompliancePolicy.skill_id.is_(None),
            CompliancePolicy.is_active == True,  # noqa: E712
        )
        .order_by(CompliancePolicy.updated_at.desc())
    ).first()


def upsert_policy(
    session: Session,
    data: CompliancePolicyInput,
    *,
    created_by_user_id: int | None,
) -> CompliancePolicy:
    campaign = session.get(Campaign, data.campaign_id)
    if campaign is None or not campaign.is_active:
        raise ValueError("La campagne sélectionnée est introuvable ou inactive.")
    if data.skill_id is not None:
        skill = session.get(Skill, data.skill_id)
        if skill is None or not skill.is_active or skill.campaign_id != data.campaign_id:
            raise ValueError("Le skill sélectionné doit appartenir à la campagne et être actif.")

    policy = get_policy(session, campaign_id=data.campaign_id, skill_id=data.skill_id)
    if policy is None:
        policy = CompliancePolicy(
            campaign_id=data.campaign_id,
            skill_id=data.skill_id,
            created_by=created_by_user_id,
        )
    policy.name = data.name.strip()
    policy.max_consecutive_work_days = data.max_consecutive_work_days
    policy.max_daily_hours = data.max_daily_hours
    policy.max_weekly_hours = data.max_weekly_hours
    policy.max_weekly_overtime_hours = data.max_weekly_overtime_hours
    policy.min_rest_hours = data.min_rest_hours
    policy.weekly_coverage_target_pct = data.weekly_coverage_target_pct
    policy.notes = data.notes.strip() or None if data.notes else None
    policy.updated_at = utc_now()
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return policy


def list_policies(session: Session, *, campaign_id: Optional[int] = None) -> list[CompliancePolicy]:
    query = select(CompliancePolicy).where(CompliancePolicy.is_active == True)  # noqa: E712
    if campaign_id is not None:
        query = query.where(CompliancePolicy.campaign_id == campaign_id)
    return list(session.exec(query.order_by(CompliancePolicy.campaign_id, CompliancePolicy.skill_id)).all())



def _shift_covers_interval(shift: Shift, interval_start: time) -> bool:
    if shift.start_time <= shift.end_time:
        return shift.start_time <= interval_start < shift.end_time
    return interval_start >= shift.start_time or interval_start < shift.end_time

def _shift_datetimes(entry: ScheduleEntry, shift: Shift) -> tuple[datetime, datetime]:
    start = datetime.combine(entry.date, shift.start_time)
    end_date = entry.date if shift.end_time > shift.start_time else entry.date + timedelta(days=1)
    end = datetime.combine(end_date, shift.end_time)
    return start, end


def _scheduled_rows(
    session: Session,
    *,
    week_start_date: date,
    campaign_id: int,
    skill_id: int,
) -> tuple[list[ScheduleEntry], dict[int, Employee], dict[int, Shift]]:
    rows = list(
        session.exec(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.date >= week_start_date,
                ScheduleEntry.date <= week_start_date + timedelta(days=6),
                ScheduleEntry.campaign_id == campaign_id,
                ScheduleEntry.skill_id == skill_id,
                ScheduleEntry.is_day_off == False,  # noqa: E712
            )
        ).all()
    )
    employee_ids = {row.employee_id for row in rows}
    employees = {
        employee.id: employee
        for employee in session.exec(select(Employee).where(Employee.id.in_(employee_ids))).all()
    } if employee_ids else {}
    shifts = {
        shift.id: shift
        for shift in session.exec(select(Shift).where(Shift.id.in_({row.shift_id for row in rows if row.shift_id is not None}))).all()
    } if rows else {}
    return rows, employees, shifts


def _daily_hours(rows: list[ScheduleEntry], shifts: dict[int, Shift], employee_id: int, target_date: date) -> float:
    for row in rows:
        if row.employee_id == employee_id and row.date == target_date and row.shift_id in shifts:
            return workforce_service.shift_hours(shifts[row.shift_id]).paid_hours
    return 0.0


def _work_dates(rows: list[ScheduleEntry], employee_id: int) -> list[date]:
    return sorted({row.date for row in rows if row.employee_id == employee_id})


def validate_schedule_candidate(
    session: Session,
    *,
    policy: CompliancePolicy,
    employee: Employee,
    shift: Shift,
    target_date: date,
    assigned_dates: set[date],
    scheduled_hours: float,
    weekly_contract_hours: Optional[float] = None,
) -> list[str]:
    """Valide l'ajout d'un shift avant de le proposer/affecter."""
    paid = workforce_service.shift_hours(
        shift,
        contract_daily_hours=workforce_service.daily_contract_hours(employee),
    ).paid_hours
    errors: list[str] = []

    if paid > policy.max_daily_hours + 1e-6:
        errors.append(f"{employee.first_name} {employee.last_name}: {paid:.1f}h > max {policy.max_daily_hours:.1f}h/jour.")

    new_weekly_hours = scheduled_hours + paid
    if new_weekly_hours > policy.max_weekly_hours + 1e-6:
        errors.append(f"{employee.first_name} {employee.last_name}: {new_weekly_hours:.1f}h > max {policy.max_weekly_hours:.1f}h/semaine.")

    contract = weekly_contract_hours if weekly_contract_hours is not None else employee.weekly_hours_contract
    new_ot = max(0.0, new_weekly_hours - contract)
    if new_ot > policy.max_weekly_overtime_hours + 1e-6:
        errors.append(f"{employee.first_name} {employee.last_name}: OT {new_ot:.1f}h > max {policy.max_weekly_overtime_hours:.1f}h/semaine.")

    prior = target_date - timedelta(days=1)
    consecutive = 0
    while prior in assigned_dates:
        consecutive += 1
        prior -= timedelta(days=1)
    following = target_date + timedelta(days=1)
    forward = 0
    while following in assigned_dates:
        forward += 1
        following += timedelta(days=1)
    if 1 + consecutive + forward > policy.max_consecutive_work_days:
        errors.append(
            f"{employee.first_name} {employee.last_name}: séquence de {1 + consecutive + forward} jours "
            f"> max {policy.max_consecutive_work_days} jours consécutifs."
        )

    return errors


def validate_candidate_rest(
    *,
    existing_intervals: list[tuple[datetime, datetime]],
    candidate_start: datetime,
    candidate_end: datetime,
    min_rest_hours: float,
) -> list[str]:
    errors: list[str] = []
    for existing_start, existing_end in existing_intervals:
        if candidate_start < existing_end and existing_start < candidate_end:
            errors.append("Les shifts se chevauchent.")
            continue
        if candidate_start >= existing_end:
            rest = (candidate_start - existing_end).total_seconds() / 3600.0
        else:
            rest = (existing_start - candidate_end).total_seconds() / 3600.0
        if rest < min_rest_hours - 1e-6:
            errors.append(f"Repos de {rest:.1f}h < minimum {min_rest_hours:.1f}h.")
    return errors


def validate_manual_entry(
    session: Session,
    *,
    policy: CompliancePolicy,
    employee: Employee,
    entry: ScheduleEntry,
    shift: Shift,
) -> list[str]:
    week_start = entry.date - timedelta(days=entry.date.weekday())
    query = select(ScheduleEntry).where(
        ScheduleEntry.employee_id == employee.id,
        ScheduleEntry.date >= week_start,
        ScheduleEntry.date <= week_start + timedelta(days=6),
        ScheduleEntry.is_day_off == False,  # noqa: E712
    )
    if entry.id is not None:
        query = query.where(ScheduleEntry.id != entry.id)
    rows = list(session.exec(query).all())
    shift_ids = {row.shift_id for row in rows if row.shift_id is not None}
    existing_shifts = {
        item.id: item
        for item in session.exec(select(Shift).where(Shift.id.in_(shift_ids))).all()
    } if shift_ids else {}
    scheduled_hours = sum(
        workforce_service.shift_hours(existing_shifts[row.shift_id]).paid_hours
        for row in rows if row.shift_id in existing_shifts
    )
    assigned_dates = {row.date for row in rows}
    errors = validate_schedule_candidate(
        session,
        policy=policy,
        employee=employee,
        shift=shift,
        target_date=entry.date,
        assigned_dates=assigned_dates,
        scheduled_hours=scheduled_hours,
    )
    candidate_start, candidate_end = _shift_datetimes(entry, shift)
    existing_intervals = [
        _shift_datetimes(row, existing_shifts[row.shift_id])
        for row in rows if row.shift_id in existing_shifts
    ]
    errors.extend(
        validate_candidate_rest(
            existing_intervals=existing_intervals,
            candidate_start=candidate_start,
            candidate_end=candidate_end,
            min_rest_hours=policy.min_rest_hours,
        )
    )
    return errors

def validate_rest_between(
    *,
    previous_end: Optional[datetime],
    next_start: datetime,
    min_rest_hours: float,
) -> Optional[str]:
    if previous_end is None:
        return None
    rest_hours = (next_start - previous_end).total_seconds() / 3600.0
    if rest_hours < min_rest_hours - 1e-6:
        return f"Repos de {rest_hours:.1f}h < minimum {min_rest_hours:.1f}h."
    return None


def _entry_on_break(entry: ScheduleEntry, interval_start: time, interval_end: time) -> bool:
    start_min = interval_start.hour * 60 + interval_start.minute
    end_min = interval_end.hour * 60 + interval_end.minute
    if end_min <= start_min:
        end_min += 24 * 60

    def overlaps(period_start: Optional[time], period_end: Optional[time]) -> bool:
        if period_start is None or period_end is None:
            return False
        ps = period_start.hour * 60 + period_start.minute
        pe = period_end.hour * 60 + period_end.minute
        if pe <= ps:
            pe += 24 * 60
        return ps < end_min and start_min < pe

    return any(
        overlaps(start, end)
        for start, end in (
            (entry.break_start, entry.break_end),
            (entry.break2_start, entry.break2_end),
            (entry.lunch_start, entry.lunch_end),
        )
    )


def _coverage(
    session: Session,
    *,
    week_start_date: date,
    campaign_id: int,
    skill_id: int,
    policy: CompliancePolicy,
) -> WeeklyCoverage:
    effective_rows: dict[date, list] = {}
    for offset in range(7):
        day = week_start_date + timedelta(days=offset)
        raw = intraday_service.list_intervals_for_day(
            session, target_date=day, campaign_id=campaign_id, skill_id=skill_id
        )
        client_plan = client_stf_service.current_plan(
            session, target_date=day, campaign_id=campaign_id, skill_id=skill_id
        )
        if client_plan is not None:
            rows = client_stf_service.effective_intervals(
                raw, client_stf_service.list_intervals(session, client_plan.id)
            )
        else:
            rows = raw
        effective_rows[day] = rows

    shift_rows, _, shifts = _scheduled_rows(
        session, week_start_date=week_start_date, campaign_id=campaign_id, skill_id=skill_id
    )
    required_h = 0.0
    covered_h = 0.0
    shortage_h = 0.0
    surplus_h = 0.0

    for day, intervals in effective_rows.items():
        for row in intervals:
            scheduled = sum(
                1
                for entry in shift_rows
                if entry.date == day
                and entry.shift_id in shifts
                and _shift_covers_interval(shifts[entry.shift_id], row.interval_start)
                and not _entry_on_break(entry, row.interval_start, row.interval_end)
            )
            required = max(row.required_hc, 0.0)
            covered = min(required, float(scheduled))
            hours = intraday_service.interval_duration_hours(row.interval_start, row.interval_end)
            required_h += required * hours
            covered_h += covered * hours
            shortage_h += max(required - scheduled, 0.0) * hours
            surplus_h += max(scheduled - required, 0.0) * hours

    pct = covered_h / required_h * 100.0 if required_h else 100.0
    return WeeklyCoverage(
        required_hc_hours=required_h,
        covered_hc_hours=covered_h,
        shortage_hc_hours=shortage_h,
        surplus_hc_hours=surplus_h,
        coverage_pct=pct,
        target_pct=policy.weekly_coverage_target_pct,
        gap_to_target_pct=pct - policy.weekly_coverage_target_pct,
    )


def evaluate_week(
    session: Session,
    *,
    week_start_date: date,
    campaign_id: int,
    skill_id: int,
) -> ComplianceReport:
    if week_start_date.weekday() != 0:
        raise ValueError("La période de conformité doit commencer un lundi.")
    policy = get_policy(session, campaign_id=campaign_id, skill_id=skill_id)
    if policy is None:
        raise ValueError("Aucune Compliance Policy active pour cette campagne/skill.")

    rows, employees, shifts = _scheduled_rows(
        session, week_start_date=week_start_date, campaign_id=campaign_id, skill_id=skill_id
    )
    by_employee: dict[int, list[ScheduleEntry]] = {}
    for row in rows:
        by_employee.setdefault(row.employee_id, []).append(row)

    violations: list[ComplianceViolation] = []
    for employee_id, employee_rows in by_employee.items():
        employee = employees.get(employee_id)
        if employee is None:
            continue
        employee_rows.sort(key=lambda row: row.date)
        worked_dates = [row.date for row in employee_rows]
        total_hours = 0.0
        max_run = 0
        run = 0
        previous_end: Optional[datetime] = None
        for row in employee_rows:
            shift = shifts.get(row.shift_id)
            if shift is None:
                continue
            hours = workforce_service.shift_hours(
                shift,
                contract_daily_hours=workforce_service.daily_contract_hours(employee),
            ).paid_hours
            total_hours += hours
            if hours > policy.max_daily_hours + 1e-6:
                violations.append(ComplianceViolation(
                    employee_id=employee_id,
                    employee_name=f"{employee.first_name} {employee.last_name}",
                    rule="Maximum heures / jour",
                    detail=f"{row.date}: {hours:.1f}h > {policy.max_daily_hours:.1f}h.",
                ))
            if previous_end is not None:
                rest_error = validate_rest_between(
                    previous_end=previous_end,
                    next_start=_shift_datetimes(row, shift)[0],
                    min_rest_hours=policy.min_rest_hours,
                )
                if rest_error:
                    violations.append(ComplianceViolation(
                        employee_id=employee_id,
                        employee_name=f"{employee.first_name} {employee.last_name}",
                        rule="Repos minimum entre shifts",
                        detail=f"{row.date}: {rest_error}",
                    ))
            previous_end = max(previous_end, _shift_datetimes(row, shift)[1]) if previous_end else _shift_datetimes(row, shift)[1]
            run = run + 1 if (len(worked_dates) == 1 or row.date == employee_rows[employee_rows.index(row)-1].date + timedelta(days=1)) else 1
            max_run = max(max_run, run)

        if max_run > policy.max_consecutive_work_days:
            violations.append(ComplianceViolation(
                employee_id=employee_id,
                employee_name=f"{employee.first_name} {employee.last_name}",
                rule="Maximum jours consécutifs",
                detail=f"{max_run} jours consécutifs > {policy.max_consecutive_work_days}.",
            ))
        if total_hours > policy.max_weekly_hours + 1e-6:
            violations.append(ComplianceViolation(
                employee_id=employee_id,
                employee_name=f"{employee.first_name} {employee.last_name}",
                rule="Maximum heures / semaine",
                detail=f"{total_hours:.1f}h > {policy.max_weekly_hours:.1f}h.",
            ))
        overtime = max(0.0, total_hours - employee.weekly_hours_contract)
        if overtime > policy.max_weekly_overtime_hours + 1e-6:
            violations.append(ComplianceViolation(
                employee_id=employee_id,
                employee_name=f"{employee.first_name} {employee.last_name}",
                rule="Maximum overtime / semaine",
                detail=f"{overtime:.1f}h > {policy.max_weekly_overtime_hours:.1f}h.",
            ))

    coverage = _coverage(
        session,
        week_start_date=week_start_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
        policy=policy,
    )
    if coverage.coverage_pct + 1e-6 < policy.weekly_coverage_target_pct:
        violations.append(ComplianceViolation(
            employee_id=None,
            employee_name=None,
            rule="Weekly Coverage",
            detail=f"Couverture {coverage.coverage_pct:.1f}% < cible {policy.weekly_coverage_target_pct:.1f}%.",
            severity="warning",
        ))

    return ComplianceReport(
        week_start_date=week_start_date,
        week_end_date=week_start_date + timedelta(days=6),
        policy=policy,
        violations=violations,
        weekly_coverage=coverage,
        compliant=not any(v.severity == "critical" for v in violations),
    )
