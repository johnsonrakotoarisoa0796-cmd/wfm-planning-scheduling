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
from app.models.employee import Employee, EmployeeAbsence
from app.schemas.scheduling import ScheduleEntryInput, ShiftInput
from app.services import client_stf_service, intraday_service, kpi_service, workforce_service


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

    session.add(entry)
    session.commit()
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
