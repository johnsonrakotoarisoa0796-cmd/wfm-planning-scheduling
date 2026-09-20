"""Module Scheduling (§33-§34) — shifts configurables, affectations par
agent, impact des pauses sur le staffing.

Écriture (shifts, affectations) réservée à admin/wfm_analyst, comme
LTF/STF/Capacity. Le rapport d'impact des pauses est en lecture pour tout
utilisateur connecté.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.scheduling import EmployeeAbsenceInput, ScheduleEntryInput, ShiftInput
from app.services import client_stf_service, compliance_service, planner_service, scheduling_service, intraday_service, auto_scheduler_service

router = APIRouter(prefix="/scheduling", tags=["scheduling"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _reference_data(session: Session, campaign_id: Optional[int] = None) -> tuple[list[Campaign], list[Skill], list[Employee]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())
    employees = list(session.exec(select(Employee)).all())
    return campaigns, skills, employees


# ============================================================================
# Shifts
# ============================================================================

@router.get("/shifts")
def list_shifts(
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    shifts = scheduling_service.list_shifts(session, active_only=False)
    return templates.TemplateResponse(
        request,
        "scheduling/shifts.html",
        {
            "active_nav": "scheduling",
            "current_user": current_user,
            "shifts": shifts,
            "errors": [],
            "values": {},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.post("/shifts", dependencies=[Depends(verify_csrf)])
def create_shift(
    request: Request,
    name: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    break_minutes: int = Form(15),
    break_count: int = Form(2),
    break_paid: bool = Form(True),
    lunch_minutes: int = Form(60),
    lunch_paid: bool = Form(False),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {"name": name, "start_time": start_time, "end_time": end_time, "break_minutes": break_minutes, "break_count": break_count, "break_paid": break_paid, "lunch_minutes": lunch_minutes, "lunch_paid": lunch_paid}
    try:
        payload = ShiftInput(**submitted_values)
        scheduling_service.create_shift(session, payload)
    except ValidationError as exc:
        errors = [str(e["msg"]) for e in exc.errors()]
        shifts = scheduling_service.list_shifts(session, active_only=False)
        return templates.TemplateResponse(
            request,
            "scheduling/shifts.html",
            {
                "active_nav": "scheduling",
                "current_user": current_user,
                "shifts": shifts,
                "errors": errors,
                "values": submitted_values,
                "can_edit": True,
            },
            status_code=400,
        )
    return RedirectResponse(url="/scheduling/shifts", status_code=303)


# ============================================================================
# Affectations (roster)
# ============================================================================

@router.get("")
def list_schedule(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    target_date = target_date or date.today()
    campaigns, skills, employees = _reference_data(session)
    entries = scheduling_service.list_schedule_entries(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    shifts_by_id = {s.id: s for s in scheduling_service.list_shifts(session, active_only=False)}
    employees_by_id = {e.id: e for e in employees}

    rows = [
        {
            "entry": entry,
            "employee_name": f"{employees_by_id[entry.employee_id].first_name} {employees_by_id[entry.employee_id].last_name}"
            if entry.employee_id in employees_by_id else "?",
            "shift_name": shifts_by_id[entry.shift_id].name if entry.shift_id in shifts_by_id else None,
        }
        for entry in entries
    ]

    return templates.TemplateResponse(
        request,
        "scheduling/list.html",
        {
            "active_nav": "scheduling",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"target_date": target_date, "campaign_id": campaign_id, "skill_id": skill_id},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.get("/new")
def new_entry_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills, employees = _reference_data(session)
    shifts = scheduling_service.list_shifts(session, active_only=True)
    return templates.TemplateResponse(
        request,
        "scheduling/form.html",
        {
            "active_nav": "scheduling",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "employees": employees,
            "shifts": shifts,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_entry(
    request: Request,
    employee_id: int = Form(...),
    entry_date: date = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    is_day_off: bool = Form(False),
    shift_id: Optional[int] = Form(None),
    break_start: Optional[str] = Form(None),
    break_end: Optional[str] = Form(None),
    break2_start: Optional[str] = Form(None),
    break2_end: Optional[str] = Form(None),
    lunch_start: Optional[str] = Form(None),
    lunch_end: Optional[str] = Form(None),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {
        "employee_id": employee_id, "entry_date": entry_date, "campaign_id": campaign_id,
        "skill_id": skill_id, "is_day_off": is_day_off, "shift_id": shift_id,
        "break_start": break_start, "break_end": break_end, "break2_start": break2_start, "break2_end": break2_end,
        "lunch_start": lunch_start, "lunch_end": lunch_end,
    }
    try:
        payload = ScheduleEntryInput(**{
            **submitted_values,
            "shift_id": shift_id or None,
            "break_start": break_start or None,
            "break_end": break_end or None,
            "break2_start": break2_start or None,
            "break2_end": break2_end or None,
            "lunch_start": lunch_start or None,
            "lunch_end": lunch_end or None,
        })
        scheduling_service.upsert_schedule_entry(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills, employees = _reference_data(session)
        shifts = scheduling_service.list_shifts(session, active_only=True)
        return templates.TemplateResponse(
            request,
            "scheduling/form.html",
            {
                "active_nav": "scheduling",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "employees": employees,
                "shifts": shifts,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/scheduling?target_date={entry_date}&campaign_id={campaign_id}&skill_id={skill_id}", status_code=303)


# ============================================================================
# Absences / congés
# ============================================================================

@router.get("/absences")
def list_absences(
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    employees = list(session.exec(select(Employee).order_by(Employee.last_name, Employee.first_name)).all())
    employees_by_id = {employee.id: employee for employee in employees}
    absences = scheduling_service.list_absences(session)
    rows = [
        {
            "absence": absence,
            "employee_name": (
                f"{employees_by_id[absence.employee_id].first_name} {employees_by_id[absence.employee_id].last_name}"
                if absence.employee_id in employees_by_id
                else "?"
            ),
        }
        for absence in absences
    ]
    return templates.TemplateResponse(
        request,
        "scheduling/absences.html",
        {
            "active_nav": "scheduling",
            "current_user": current_user,
            "employees": employees,
            "rows": rows,
            "errors": [],
            "values": {},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.post("/absences", dependencies=[Depends(verify_csrf)])
def create_absence(
    request: Request,
    employee_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    absence_type: str = Form(...),
    paid: str = Form("false"),
    notes: Optional[str] = Form(None),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    paid_value = paid.strip().lower() in {"1", "true", "yes", "on"}
    submitted_values = {
        "employee_id": employee_id,
        "start_date": start_date,
        "end_date": end_date,
        "absence_type": absence_type,
        "paid": paid_value,
        "notes": notes,
    }
    try:
        payload = EmployeeAbsenceInput(**submitted_values)
        scheduling_service.create_absence(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(error["msg"]) for error in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        employees = list(session.exec(select(Employee).order_by(Employee.last_name, Employee.first_name)).all())
        rows = []
        employees_by_id = {employee.id: employee for employee in employees}
        absences = scheduling_service.list_absences(session)
        for absence in absences:
            rows.append(
                {
                    "absence": absence,
                    "employee_name": (
                        f"{employees_by_id[absence.employee_id].first_name} {employees_by_id[absence.employee_id].last_name}"
                        if absence.employee_id in employees_by_id
                        else "?"
                    ),
                }
            )
        return templates.TemplateResponse(
            request,
            "scheduling/absences.html",
            {
                "active_nav": "scheduling",
                "current_user": current_user,
                "employees": employees,
                "rows": rows,
                "errors": errors,
                "values": submitted_values,
                "can_edit": True,
            },
            status_code=400,
        )

    return RedirectResponse(url="/scheduling/absences", status_code=303)



# ============================================================================
# Generate Schedule — workflow automatique hebdomadaire
# ============================================================================

@router.get("/generate")
def generate_schedule_view(
    request: Request,
    week: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    period = week or date.today().strftime("%G-W%V")
    return _render_schedule_generator(
        request,
        session,
        current_user,
        period=period,
        campaign_id=campaign_id,
        skill_id=skill_id,
        errors=[],
    )


@router.post("/generate", dependencies=[Depends(verify_csrf)])
def generate_schedule_action(
    request: Request,
    period: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    replace_existing: bool = Form(False),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        year_text, week_text = period.split("-W", 1)
        week_start = date.fromisocalendar(int(year_text), int(week_text), 1)
        auto_scheduler_service.generate_schedule(
            session,
            week_start_date=week_start,
            campaign_id=campaign_id,
            skill_id=skill_id,
            replace_existing=replace_existing,
        )
        return RedirectResponse(
            url=f"/scheduling/generate?week={period}&campaign_id={campaign_id}&skill_id={skill_id}&generated=1",
            status_code=303,
        )
    except (ValueError, TypeError) as exc:
        return _render_schedule_generator(
            request,
            session,
            current_user,
            period=period,
            campaign_id=campaign_id,
            skill_id=skill_id,
            errors=[str(exc)],
            status_code=400,
        )


def _render_schedule_generator(
    request: Request,
    session: Session,
    current_user: User,
    *,
    period: str,
    campaign_id: Optional[int],
    skill_id: Optional[int],
    errors: list[str],
    status_code: int = 200,
):
    campaigns, skills, employees = _reference_data(session, campaign_id)
    try:
        year_text, week_text = period.split("-W", 1)
        week_start = date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError):
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        period = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"

    entries = []
    compliance_report = None
    if campaign_id is not None and skill_id is not None:
        for offset in range(5):
            entries.extend(
                scheduling_service.list_schedule_entries(
                    session,
                    target_date=week_start + timedelta(days=offset),
                    campaign_id=campaign_id,
                    skill_id=skill_id,
                )
            )
        try:
            compliance_report = compliance_service.evaluate_week(
                session,
                week_start_date=week_start,
                campaign_id=campaign_id,
                skill_id=skill_id,
            )
        except ValueError:
            compliance_report = None

    shifts_by_id = {shift.id: shift for shift in scheduling_service.list_shifts(session, active_only=False)}
    week_days = [week_start + timedelta(days=i) for i in range(5)]
    week_rows = []

    for employee in employees:
        cells = []
        for day in week_days:
            entry = next((item for item in entries if item.employee_id == employee.id and item.date == day), None)
            absences = scheduling_service.list_absences(
                session, employee_id=employee.id, start_date=day, end_date=day
            )
            absence = absences[0] if absences else None
            shift = shifts_by_id.get(entry.shift_id) if entry and entry.shift_id else None
            cells.append({"date": day, "entry": entry, "shift": shift, "absence": absence})
        week_rows.append({"employee": employee, "days": cells})

    return templates.TemplateResponse(
        request,
        "scheduling/generate.html",
        {
            "active_nav": "scheduling-generate",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "employees": employees,
            "filters": {"period": period, "campaign_id": campaign_id, "skill_id": skill_id},
            "week_rows": week_rows,
            "week_days": week_days,
            "generated": request.query_params.get("generated") == "1",
            "errors": errors,
            "can_edit": current_user.role in WRITE_ROLES,
            "has_schedule": bool(entries),
            "compliance_report": compliance_report,
        },
        status_code=status_code,
    )



# ============================================================================
# Planner de mix de shifts
# ============================================================================

@router.get("/planner")
def planner_view(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    target_date = target_date or date.today()
    campaigns, skills, employees = _reference_data(session, campaign_id)
    intervals = []
    client_stf_active = False
    recommendations = []
    if campaign_id is not None and skill_id is not None:
        raw_intervals = intraday_service.list_intervals_for_day(
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
        intervals = (
            client_stf_service.effective_intervals(raw_intervals, client_rows)
            if client_rows
            else raw_intervals
        )
        client_stf_active = bool(client_rows)
        shifts = scheduling_service.list_shifts(session, active_only=True)
        existing_entries = scheduling_service.list_schedule_entries(
            session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
        )
        assigned_employee_ids = {entry.employee_id for entry in existing_entries}
        eligible_skill_employee_ids = {
            row.employee_id
            for row in session.exec(
                select(EmployeeSkill).where(EmployeeSkill.skill_id == skill_id)
            ).all()
        }
        target_absences = scheduling_service.list_absences(
            session, start_date=target_date, end_date=target_date
        )
        absent_employee_ids = {
            absence.employee_id
            for absence in target_absences
        }
        available_employee_count = sum(
            1
            for employee in employees
            if (
                employee.status.value == "active"
                and employee.campaign_id == campaign_id
                and employee.id in eligible_skill_employee_ids
                and employee.id not in assigned_employee_ids
                and employee.id not in absent_employee_ids
            )
        )
        recommendations = planner_service.recommend_shift_mix(
            intervals, shifts, max_agents=available_employee_count
        )
    return templates.TemplateResponse(
        request,
        "scheduling/planner.html",
        {
            "active_nav": "scheduling-planner",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "employees": employees,
            "available_employee_count": available_employee_count if campaign_id is not None and skill_id is not None else 0,
            "filters": {
                "target_date": target_date,
                "campaign_id": campaign_id,
                "skill_id": skill_id,
            },
            "intervals": intervals,
            "recommendations": recommendations,
            "client_stf_active": client_stf_active,
        },
    )


# ============================================================================
# Impact des pauses (§34)
# ============================================================================

@router.get("/breaks")
def break_impact_report(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns, skills, _ = _reference_data(session)
    report = None
    if target_date is not None and campaign_id is not None and skill_id is not None:
        report = scheduling_service.compute_break_impact(
            session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
        )

    return templates.TemplateResponse(
        request,
        "scheduling/breaks.html",
        {
            "active_nav": "scheduling",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"target_date": target_date or date.today(), "campaign_id": campaign_id, "skill_id": skill_id},
            "report": report,
        },
    )
