"""Service métier pour le module Scheduling (§33-§34 du cahier des charges).

Le calcul d'impact des pauses (§34) réutilise volontairement la même
grille de 48 intervalles de 30 min que Daily/Intraday (commit 08) —
`intraday_service.slot_bounds` / `SLOTS_PER_DAY` sont partagés plutôt que
dupliqués, pour que "l'intervalle 09:00-09:30" désigne toujours exactement
la même tranche horaire dans tout le système.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Optional

from sqlmodel import Session, select

from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.campaign import Campaign
from app.models.skill import Skill
from app.schemas.scheduling import ScheduleEntryInput, ShiftInput
from app.services import client_stf_service, compliance_service, intraday_service, kpi_service, workforce_service


# ============================================================================
# Shifts (§33)
# ============================================================================

def create_shift(session: Session, data: ShiftInput) -> Shift:
    shift = Shift(
        name=data.name,
        start_time=data.start_time,
        end_time=data.end_time,
        break_minutes=data.break_minutes,
        break_count=data.break_count,
        break_paid=data.break_paid,
        lunch_minutes=data.lunch_minutes,
        lunch_paid=data.lunch_paid,
    )
    session.add(shift)
    session.commit()
    session.refresh(shift)
    return shift


def list_shifts(session: Session, *, active_only: bool = True) -> list[Shift]:
    query = select(Shift)
    if active_only:
        query = query.where(Shift.is_active == True)  # noqa: E712
    return list(session.exec(query.order_by(Shift.start_time)).all())


# ============================================================================
# Affectations (ScheduleEntry)
# ============================================================================

def _time_offset_from_shift_start(shift: Shift, value: time) -> int:
    """Minute offset depuis le début du shift, y compris les shifts overnight."""
    start = _time_minutes(shift.start_time)
    current = _time_minutes(value)
    if shift.start_time > shift.end_time and current < start:
        current += 24 * 60
    if shift.start_time <= shift.end_time and current < start:
        return -1
    return current - start


def _validate_break_plan(entry: ScheduleEntry, shift: Shift) -> list[str]:
    """Valide présence, durée, position et chevauchement des pauses."""
    errors: list[str] = []
    expected_breaks = max(0, min(shift.break_count, 2))
    break_pairs = [
        (entry.break_start, entry.break_end, "Pause 1"),
        (entry.break2_start, entry.break2_end, "Pause 2"),
    ]
    intervals: list[tuple[int, int, str]] = []

    for index, (start, end, label) in enumerate(break_pairs):
        required = index < expected_breaks and shift.break_minutes > 0
        if start is None or end is None:
            if required:
                errors.append(f"{label}: horaires obligatoires pour ce shift.")
            continue
        start_offset = _time_offset_from_shift_start(shift, start)
        end_offset = _time_offset_from_shift_start(shift, end)
        if start_offset < 0 or end_offset < 0 or end_offset <= start_offset:
            errors.append(f"{label}: plage horaire invalide ou en dehors du shift.")
            continue
        if end_offset > int(round(workforce_service.shift_elapsed_hours(shift) * 60)):
            errors.append(f"{label}: la pause sort du shift.")
        if end_offset - start_offset != shift.break_minutes:
            errors.append(f"{label}: durée attendue {shift.break_minutes} minute(s).")
        intervals.append((start_offset, end_offset, label))

    if shift.lunch_minutes > 0:
        if entry.lunch_start is None or entry.lunch_end is None:
            errors.append("Déjeuner: horaires obligatoires pour ce shift.")
        else:
            start_offset = _time_offset_from_shift_start(shift, entry.lunch_start)
            end_offset = _time_offset_from_shift_start(shift, entry.lunch_end)
            if start_offset < 0 or end_offset < 0 or end_offset <= start_offset:
                errors.append("Déjeuner: plage horaire invalide ou en dehors du shift.")
            elif end_offset > int(round(workforce_service.shift_elapsed_hours(shift) * 60)):
                errors.append("Déjeuner: le déjeuner sort du shift.")
            elif end_offset - start_offset != shift.lunch_minutes:
                errors.append(f"Déjeuner: durée attendue {shift.lunch_minutes} minute(s).")
            else:
                intervals.append((start_offset, end_offset, "Déjeuner"))

    intervals.sort(key=lambda item: item[0])
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] < previous[1]:
            errors.append(f"{previous[2]} et {current[2]} se chevauchent.")

    return errors

def upsert_schedule_entry(session: Session, data: ScheduleEntryInput) -> ScheduleEntry:
    """Crée ou met à jour l'affectation d'un employé pour une date donnée.

    Upsert sur (employee_id, entry_date) : un agent a un seul planning par
    jour — contrairement au Shrinkage, où plusieurs occurrences peuvent
    coexister le même jour.
    """
    existing = session.exec(
        select(ScheduleEntry).where(
            ScheduleEntry.employee_id == data.employee_id,
            ScheduleEntry.date == data.entry_date,
        )
    ).first()
    previous_scope = (existing.campaign_id, existing.skill_id) if existing is not None else None

    entry = existing or ScheduleEntry(employee_id=data.employee_id, date=data.entry_date)
    entry.campaign_id = data.campaign_id
    entry.skill_id = data.skill_id
    entry.is_day_off = data.is_day_off
    entry.shift_id = None if data.is_day_off else data.shift_id
    entry.break_start = None if data.is_day_off else data.break_start
    entry.break_end = None if data.is_day_off else data.break_end
    entry.break2_start = None if data.is_day_off else data.break2_start
    entry.break2_end = None if data.is_day_off else data.break2_end
    entry.lunch_start = None if data.is_day_off else data.lunch_start
    entry.lunch_end = None if data.is_day_off else data.lunch_end

    employee = session.get(Employee, data.employee_id)
    campaign = session.get(Campaign, data.campaign_id)
    skill = session.get(Skill, data.skill_id)
    shift = session.get(Shift, data.shift_id) if data.shift_id is not None else None
    if employee is None:
        raise ValueError("Employé introuvable.")
    if campaign is None or not campaign.is_active:
        raise ValueError("Campagne introuvable ou inactive.")
    if skill is None or not skill.is_active or skill.campaign_id != data.campaign_id:
        raise ValueError("Skill introuvable, inactif ou rattaché à une autre campagne.")
    if employee.campaign_id != data.campaign_id:
        raise ValueError("L'employé n'appartient pas à la campagne sélectionnée.")
    skill_link = session.exec(
        select(EmployeeSkill).where(
            EmployeeSkill.employee_id == data.employee_id,
            EmployeeSkill.skill_id == data.skill_id,
        )
    ).first()
    if skill_link is None:
        raise ValueError("L'employé ne possède pas le skill sélectionné.")
    if data.entry_date < employee.hire_date:
        raise ValueError("La date du planning est antérieure à la date d'embauche.")
    if employee.termination_date is not None and data.entry_date > employee.termination_date:
        raise ValueError("La date du planning est postérieure à la date de sortie.")
    absence = session.exec(
        select(EmployeeAbsence).where(
            EmployeeAbsence.employee_id == data.employee_id,
            EmployeeAbsence.start_date <= data.entry_date,
            EmployeeAbsence.end_date >= data.entry_date,
        )
    ).first()
    if absence is not None and not data.is_day_off:
        raise ValueError(
            f"L'employé est absent ({absence.absence_type}) à cette date."
        )
    if not data.is_day_off and shift is None:
        raise ValueError("Shift introuvable.")
    if not data.is_day_off and shift is not None:
        break_errors = _validate_break_plan(entry, shift)
        if break_errors:
            session.rollback()
            raise ValueError("Planning: " + " ".join(break_errors))
        policy = compliance_service.get_policy(
            session, campaign_id=data.campaign_id, skill_id=data.skill_id
        )
        if policy is not None:
            errors = compliance_service.validate_manual_entry(
                session,
                policy=policy,
                employee=employee,
                entry=entry,
                shift=shift,
            )
            if errors:
                session.rollback()
                raise ValueError("Compliance: " + " ".join(errors))

    session.add(entry)
    session.commit()
    scopes = {(data.campaign_id, data.skill_id)}
    if previous_scope is not None:
        scopes.add(previous_scope)
    for scope_campaign_id, scope_skill_id in scopes:
        refresh_interval_scheduled_hc(
            session,
            target_date=data.entry_date,
            campaign_id=scope_campaign_id,
            skill_id=scope_skill_id,
        )
    session.refresh(entry)
    return entry


def list_schedule_entries(
    session: Session, *, target_date: date, campaign_id: Optional[int] = None, skill_id: Optional[int] = None
) -> list[ScheduleEntry]:
    query = select(ScheduleEntry).where(ScheduleEntry.date == target_date)
    if campaign_id is not None:
        query = query.where(ScheduleEntry.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(ScheduleEntry.skill_id == skill_id)
    return list(session.exec(query).all())


def refresh_interval_scheduled_hc(
    session: Session,
    *,
    target_date: date,
    campaign_id: int,
    skill_id: int,
    commit: bool = True,
) -> list:
    """Synchronise Scheduled HC des intervalles depuis le planning réel.

    ScheduleEntry est la source de vérité du planning. Les pauses et déjeuner
    retirent l'agent de la couverture de l'intervalle lorsqu'ils chevauchent
    cette tranche.
    """
    entries = [
        e for e in list_schedule_entries(
            session,
            target_date=target_date,
            campaign_id=campaign_id,
            skill_id=skill_id,
        )
        if not e.is_day_off and e.shift_id is not None
    ]
    shifts = {
        shift.id: shift
        for shift in session.exec(
            select(Shift).where(Shift.id.in_({e.shift_id for e in entries}))
        ).all()
    } if entries else {}

    intervals = intraday_service.list_intervals_for_day(
        session,
        target_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    for interval in intervals:
        covered = 0
        for entry in entries:
            shift = shifts.get(entry.shift_id)
            if shift is None:
                continue
            if not _shift_covers_interval(shift, interval.interval_start, interval.interval_end):
                continue
            if _entry_on_break_during_interval(entry, interval.interval_start, interval.interval_end):
                continue
            covered += 1
        interval.scheduled_hc = float(covered)
        session.add(interval)

    if commit:
        session.commit()
    return intervals

# ============================================================================
# Impact des pauses sur le staffing (§34)
# ============================================================================

def _shift_covers_interval(shift: Shift, interval_start: time, interval_end: time) -> bool:
    """Vrai si le shift couvre cet intervalle de 30 min.

    Gère les shifts qui chevauchent minuit (ex: 17:00-02:00, cité en
    exemple au §33) : start_time > end_time signale ce cas.
    """
    if shift.start_time <= shift.end_time:
        return shift.start_time <= interval_start < shift.end_time
    return interval_start >= shift.start_time or interval_start < shift.end_time


def _time_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _segment_overlaps(
    period_start: time,
    period_end: time,
    interval_start: time,
    interval_end: time,
) -> bool:
    """Chevauchement robuste, y compris pour une pause après minuit."""
    ps, pe = _time_minutes(period_start), _time_minutes(period_end)
    ins, ine = _time_minutes(interval_start), _time_minutes(interval_end)
    if pe <= ps:
        pe += 24 * 60
    if ine <= ins:
        ine += 24 * 60
    # Teste le segment direct puis sa projection sur le jour suivant.
    return (
        ps < ine and ins < pe
    ) or (
        (ps + 24 * 60) < ine and ins < (pe + 24 * 60)
    )


def _overlaps(period_start: Optional[time], period_end: Optional[time], interval_start: time, interval_end: time) -> bool:
    if period_start is None or period_end is None:
        return False
    return _segment_overlaps(period_start, period_end, interval_start, interval_end)


def _entry_on_break_during_interval(entry: ScheduleEntry, interval_start: time, interval_end: time) -> bool:
    """Vrai si l'employé est en pause 1, pause 2 ou déjeuner durant cet intervalle."""
    return any(
        _overlaps(start, end, interval_start, interval_end)
        for start, end in (
            (entry.break_start, entry.break_end),
            (entry.break2_start, entry.break2_end),
            (entry.lunch_start, entry.lunch_end),
        )
    )


@dataclass(frozen=True)
class IntervalStaffing:
    """Une ligne du rapport d'impact des pauses (§34)."""

    interval_start: time
    interval_end: time
    required_hc: float
    available_before_break: int
    available_after_break: int
    gap_after_break: float


def compute_break_impact(
    session: Session, *, target_date: date, campaign_id: int, skill_id: int
) -> list[IntervalStaffing]:
    """Pour chaque intervalle de 30 min de la journée : Available HC avant
    pause, après pause, comparé au Required HC (issu du forecast Daily/
    Intraday s'il existe déjà pour ce jour) — identifie les intervalles où
    le placement des pauses crée un sous-staffing (§34).
    """
    entries = [
        e for e in list_schedule_entries(session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id)
        if not e.is_day_off
    ]
    shifts_by_id = {s.id: s for s in list_shifts(session, active_only=False)}

    forecast_intervals = intraday_service.list_intervals_for_day(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    client_plan = client_stf_service.current_plan(
        session,
        target_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    client_rows = (
        client_stf_service.list_intervals(session, client_plan.id)
        if client_plan is not None
        else []
    )
    effective_intervals = (
        client_stf_service.effective_intervals(forecast_intervals, client_rows)
        if client_rows
        else forecast_intervals
    )
    required_by_start = {i.interval_start: i.required_hc for i in effective_intervals}

    results = []
    for slot_index in range(intraday_service.SLOTS_PER_DAY):
        interval_start, interval_end = intraday_service.slot_bounds(slot_index)

        before = 0
        after = 0
        for entry in entries:
            shift = shifts_by_id.get(entry.shift_id)
            if shift is not None and _shift_covers_interval(shift, interval_start, interval_end):
                before += 1
                if not _entry_on_break_during_interval(entry, interval_start, interval_end):
                    after += 1

        required = required_by_start.get(interval_start, 0.0)
        results.append(
            IntervalStaffing(
                interval_start=interval_start,
                interval_end=interval_end,
                required_hc=required,
                available_before_break=before,
                available_after_break=after,
                gap_after_break=kpi_service.staffing_gap(after, required),
            )
        )
    return results


# ============================================================================
# Pauses / absentéisme contractuel
# ============================================================================

def shift_hours_summary(session: Session, *, employee_id: int, shift_id: int):
    employee = session.get(Employee, employee_id)
    shift = session.get(Shift, shift_id)
    if employee is None or shift is None:
        raise ValueError("Employé ou shift introuvable.")
    return workforce_service.shift_hours(
        shift,
        contract_daily_hours=workforce_service.daily_contract_hours(employee),
    )


def create_absence(session: Session, data) -> EmployeeAbsence:
    workforce_service.validate_absence_type(data.absence_type)
    employee = session.get(Employee, data.employee_id)
    if employee is None:
        raise ValueError("Employé introuvable.")
    overlap = session.exec(
        select(EmployeeAbsence).where(
            EmployeeAbsence.employee_id == data.employee_id,
            EmployeeAbsence.start_date <= data.end_date,
            EmployeeAbsence.end_date >= data.start_date,
        )
    ).first()
    if overlap is not None:
        raise ValueError("Une absence existe déjà sur une partie de cette période.")
    absence = EmployeeAbsence(
        employee_id=data.employee_id,
        start_date=data.start_date,
        end_date=data.end_date,
        absence_type=data.absence_type,
        paid=data.paid,
        notes=data.notes,
    )
    session.add(absence)
    session.commit()
    session.refresh(absence)
    return absence


def list_absences(
    session: Session,
    *,
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[EmployeeAbsence]:
    query = select(EmployeeAbsence)
    if employee_id is not None:
        query = query.where(EmployeeAbsence.employee_id == employee_id)
    if start_date is not None:
        query = query.where(EmployeeAbsence.end_date >= start_date)
    if end_date is not None:
        query = query.where(EmployeeAbsence.start_date <= end_date)
    return list(session.exec(query.order_by(EmployeeAbsence.start_date.desc())).all())
