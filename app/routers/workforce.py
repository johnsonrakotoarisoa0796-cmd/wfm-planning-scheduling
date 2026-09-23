"""Référentiel Workforce / Agents."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import EmployeeStatus, UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.workforce import WorkforceEmployeeInput
from app.services import workforce_agents_service

router = APIRouter(prefix="/workforce", tags=["workforce"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)

def _reference_data(session: Session):
    campaigns = list(
        session.exec(
            select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)  # noqa: E712
        ).all()
    )
    skills = list(
        session.exec(
            select(Skill).where(Skill.is_active == True).order_by(Skill.name)
        ).all()
    )
    return campaigns, skills


def _render(
    request: Request,
    session: Session,
    current_user: User,
    *,
    search: str | None = None,
    campaign_id: int | None = None,
    skill_id: int | None = None,
    status: EmployeeStatus | None = None,
    data_source: str | None = None,
    errors: list[str] | None = None,
    result: dict | None = None,
    status_code: int = 200,
):
    campaigns, skills = _reference_data(session)
    employees = workforce_agents_service.list_employees(
        session,
        search=search,
        campaign_id=campaign_id,
        skill_id=skill_id,
        status=status,
        data_source=data_source,
    )
    skill_rows = workforce_agents_service.employee_skill_rows(
        session, [employee.id for employee in employees if employee.id is not None]
    )
    active_count = len(workforce_agents_service.list_employees(session, status=EmployeeStatus.ACTIVE))
    leave_count = len(workforce_agents_service.list_employees(session, status=EmployeeStatus.LEAVE))
    synthetic_count = len(workforce_agents_service.list_employees(session, data_source="synthetic"))
    real_count = len(workforce_agents_service.list_employees(session, data_source="real"))
    return templates.TemplateResponse(
        request,
        "workforce/index.html",
        {
            "active_nav": "workforce",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "employees": employees,
            "skill_rows": skill_rows,
            "errors": errors or [],
            "result": result,
            "filters": {
                "search": search or "",
                "campaign_id": campaign_id,
                "skill_id": skill_id,
                "status": status.value if status else "",
                "data_source": data_source or "",
            },
            "metrics": {
                "total": real_count + synthetic_count,
                "active": active_count,
                "leave": leave_count,
                "real": real_count,
                "synthetic": synthetic_count,
            },
            "can_edit": current_user.role in WRITE_ROLES,
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@router.get("")
def workforce_index(
    request: Request,
    search: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    status: Optional[str] = None,
    data_source: Optional[str] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    parsed_status = None
    if status:
        try:
            parsed_status = EmployeeStatus(status)
        except ValueError:
            parsed_status = None
    return _render(
        request,
        session,
        current_user,
        search=search,
        campaign_id=campaign_id,
        skill_id=skill_id,
        status=parsed_status,
        data_source=data_source,
    )


@router.get("/new")
def workforce_new(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "workforce/form.html",
        {
            "active_nav": "workforce",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def workforce_create(
    request: Request,
    employee_code: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    hire_date: date = Form(...),
    termination_date: Optional[date] = Form(None),
    weekly_hours_contract: float = Form(40.0),
    timezone_name: str = Form("UTC"),
    status: str = Form("active"),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    values = {
        "employee_code": employee_code, "first_name": first_name, "last_name": last_name,
        "campaign_id": campaign_id, "skill_id": skill_id, "hire_date": hire_date,
        "termination_date": termination_date, "weekly_hours_contract": weekly_hours_contract,
        "timezone_name": timezone_name, "status": status,
    }
    try:
        payload = WorkforceEmployeeInput(**{**values, "status": EmployeeStatus(status), "data_source": "real"})
        workforce_agents_service.create_employee(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(error["msg"]) for error in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "workforce/form.html",
            {
                "active_nav": "workforce",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": values,
            },
            status_code=400,
        )
    return RedirectResponse(url="/workforce", status_code=303)


@router.post("/generate", dependencies=[Depends(verify_csrf)])
def workforce_generate_synthetic(
    request: Request,
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    count: int = Form(1),
    hire_date: date = Form(...),
    weekly_hours_contract: float = Form(40.0),
    timezone_name: str = Form("UTC"),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        created = workforce_agents_service.generate_synthetic_employees(
            session,
            campaign_id=campaign_id,
            skill_id=skill_id,
            count=count,
            hire_date=hire_date,
            weekly_hours_contract=weekly_hours_contract,
            timezone_name=timezone_name,
        )
        return RedirectResponse(url=f"/workforce?data_source=synthetic&generated={len(created)}", status_code=303)
    except (ValueError, ValidationError) as exc:
        return _render(
            request,
            session,
            current_user,
            errors=[str(exc)],
            status_code=400,
        )


@router.post("/import", dependencies=[Depends(verify_csrf)])
async def workforce_import(
    request: Request,
    file: UploadFile = File(...),
    update_existing: str = Form("true"),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        content = await file.read()
        result = workforce_agents_service.import_real_employees(
            session,
            filename=file.filename or "employees.csv",
            content=content,
            update_existing=update_existing.lower() in {"1", "true", "yes", "on"},
        )
        return RedirectResponse(
            url=f"/workforce?imported={result.imported}&updated={result.updated}&skipped={result.skipped}",
            status_code=303,
        )
    except Exception as exc:
        session.rollback()
        return _render(request, session, current_user, errors=[str(exc)], status_code=400)


@router.post("/{employee_id}/status", dependencies=[Depends(verify_csrf)])
def workforce_status(
    employee_id: int,
    new_status: str = Form(...),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        status = EmployeeStatus(new_status)
    except ValueError:
        return RedirectResponse(url="/workforce?error=Statut+invalide", status_code=303)
    employee = session.get(Employee, employee_id)
    if employee is None:
        return RedirectResponse(url="/workforce?error=Agent+introuvable", status_code=303)
    workforce_agents_service.set_employee_status(session, employee, status)
    return RedirectResponse(url="/workforce", status_code=303)


@router.get("/generate")
def workforce_generate_get():
    """Évite qu'un ancien formulaire en cache ne tombe sur /{employee_id}."""
    return RedirectResponse(
        url="/workforce?error=Le formulaire de génération doit être envoyé en POST. Rechargez la page Workforce puis relancez la génération.",
        status_code=303,
    )


@router.get("/{employee_id}")
def workforce_detail(
    employee_id: int,
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    employee = session.get(Employee, employee_id)
    if employee is None:
        return RedirectResponse(url="/workforce", status_code=303)
    campaign = session.get(Campaign, employee.campaign_id)
    links = list(session.exec(select(EmployeeSkill).where(EmployeeSkill.employee_id == employee.id)).all())
    skills = {skill.id: skill for skill in session.exec(select(Skill).where(Skill.id.in_({link.skill_id for link in links}))).all()}
    absences = list(
        session.exec(
            select(EmployeeAbsence)
            .where(EmployeeAbsence.employee_id == employee.id)
            .order_by(EmployeeAbsence.start_date.desc())
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "workforce/detail.html",
        {
            "active_nav": "workforce",
            "current_user": current_user,
            "employee": employee,
            "campaign": campaign,
            "skills": [skills[link.skill_id] for link in links if link.skill_id in skills],
            "absences": absences,
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )
