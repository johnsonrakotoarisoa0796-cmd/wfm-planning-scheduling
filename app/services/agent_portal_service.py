"""Self-service agent et demandes RH légères."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from sqlmodel import Session, select

from app.core.time_utils import utc_now
from app.models.agent_request import AgentRequest
from app.models.employee import Employee, EmployeeAbsence
from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.models.user import User


def linked_employee(session: Session, user: User) -> Employee | None:
    if user.employee_id is None:
        return None
    return session.get(Employee, user.employee_id)


def list_agent_schedule(session: Session, employee_id: int, start_date: date, end_date: date):
    entries = list(
        session.exec(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.employee_id == employee_id,
                ScheduleEntry.date >= start_date,
                ScheduleEntry.date <= end_date,
            )
            .order_by(ScheduleEntry.date)
        ).all()
    )
    shifts = {shift.id: shift for shift in session.exec(select(Shift)).all()}
    absences = list(
        session.exec(
            select(EmployeeAbsence)
            .where(
                EmployeeAbsence.employee_id == employee_id,
                EmployeeAbsence.start_date <= end_date,
                EmployeeAbsence.end_date >= start_date,
            )
        ).all()
    )
    absence_by_date = {}
    for absence in absences:
        current = max(start_date, absence.start_date)
        finish = min(end_date, absence.end_date)
        while current <= finish:
            absence_by_date[current] = absence
            current += timedelta(days=1)

    entry_by_date = {entry.date: entry for entry in entries}
    rows = []
    current = start_date
    while current <= end_date:
        entry = entry_by_date.get(current)
        rows.append(
            {
                "date": current,
                "entry": entry,
                "shift": shifts.get(entry.shift_id) if entry and entry.shift_id else None,
                "absence": absence_by_date.get(current),
            }
        )
        current += timedelta(days=1)
    return rows


def create_time_off_request(
    session: Session,
    *,
    employee_id: int,
    start_date: date,
    end_date: date,
    notes: str | None = None,
) -> AgentRequest:
    if end_date < start_date:
        raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")
    overlap = session.exec(
        select(AgentRequest).where(
            AgentRequest.employee_id == employee_id,
            AgentRequest.status == "pending",
            AgentRequest.start_date <= end_date,
            AgentRequest.end_date >= start_date,
        )
    ).first()
    if overlap is not None:
        raise ValueError("Une demande est déjà en attente sur cette période.")
    request = AgentRequest(
        employee_id=employee_id,
        request_type="time_off",
        start_date=start_date,
        end_date=end_date,
        notes=notes.strip() if notes else None,
        status="pending",
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def list_requests(session: Session, employee_id: int | None = None, status: str | None = None):
    query = select(AgentRequest)
    if employee_id is not None:
        query = query.where(AgentRequest.employee_id == employee_id)
    if status:
        query = query.where(AgentRequest.status == status)
    return list(session.exec(query.order_by(AgentRequest.requested_at.desc())).all())


def review_request(session: Session, *, request_id: int, reviewer_id: int, decision: str) -> AgentRequest:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Décision invalide.")
    item = session.get(AgentRequest, request_id)
    if item is None:
        raise ValueError("Demande introuvable.")
    if item.status != "pending":
        raise ValueError("Cette demande a déjà été traitée.")
    item.status = decision
    item.reviewed_by = reviewer_id
    item.reviewed_at = utc_now()
    session.add(item)
    session.commit()
    session.refresh(item)

    if decision == "approved":
        session.add(
            EmployeeAbsence(
                employee_id=item.employee_id,
                start_date=item.start_date,
                end_date=item.end_date,
                absence_type="paid_leave",
                paid=True,
                notes=f"Demande agent #{item.id}",
            )
        )
        session.commit()
    return item
