"""Agent Hub : planning personnel et demandes self-service."""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.agent_request import AgentRequest
from app.models.employee import Employee
from app.models.user import User
from app.models.enums import UserRole
from app.services import agent_portal_service

router = APIRouter(prefix="/agent", tags=["agent-portal"])
MANAGER_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST, UserRole.TEAM_LEAD)


@router.get("")
def agent_home(
    request: Request,
    target_date: date | None = None,
    employee_id: int | None = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    employee = agent_portal_service.linked_employee(session, current_user)
    if employee is None and current_user.role in MANAGER_ROLES and employee_id is not None:
        employee = session.get(Employee, employee_id)
    if employee is None:
        return templates.TemplateResponse(
            request,
            "agent/index.html",
            {"active_nav": "agent", "current_user": current_user, "employee": None, "rows": [], "requests": [], "errors": ["Votre compte n'est pas encore lié à un agent. Un administrateur peut le faire depuis Configuration."]},
        )

    target_date = target_date or date.today()
    start = target_date - timedelta(days=target_date.weekday())
    rows = agent_portal_service.list_agent_schedule(
        session, employee_id=employee.id, start_date=start, end_date=start + timedelta(days=13)
    )
    requests = agent_portal_service.list_requests(session, employee_id=employee.id)
    return templates.TemplateResponse(
        request,
        "agent/index.html",
        {
            "active_nav": "agent",
            "current_user": current_user,
            "employee": employee,
            "rows": rows,
            "requests": requests,
            "errors": [],
        },
    )


@router.post("/requests", dependencies=[Depends(verify_csrf)])
def create_request(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    employee = agent_portal_service.linked_employee(session, current_user)
    if employee is None:
        raise ValueError("Compte non lié à un agent.")
    try:
        agent_portal_service.create_time_off_request(
            session,
            employee_id=employee.id,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "agent/index.html",
            {
                "active_nav": "agent",
                "current_user": current_user,
                "employee": employee,
                "rows": agent_portal_service.list_agent_schedule(session, employee.id, date.today(), date.today() + timedelta(days=13)),
                "requests": agent_portal_service.list_requests(session, employee.id),
                "errors": [str(exc)],
            },
            status_code=400,
        )
    return RedirectResponse("/agent", status_code=303)


@router.get("/requests")
def manage_requests(
    request: Request,
    current_user: User = Depends(require_role(*MANAGER_ROLES)),
    session: Session = Depends(get_session),
):
    items = agent_portal_service.list_requests(session, status="pending")
    employees = {employee.id: employee for employee in session.exec(select(Employee)).all()}
    return templates.TemplateResponse(
        request,
        "agent/requests.html",
        {"active_nav": "agent", "current_user": current_user, "items": items, "employees": employees},
    )


@router.post("/requests/{request_id}/review", dependencies=[Depends(verify_csrf)])
def review_request(
    request_id: int,
    decision: str = Form(...),
    current_user: User = Depends(require_role(*MANAGER_ROLES)),
    session: Session = Depends(get_session),
):
    agent_portal_service.review_request(
        session, request_id=request_id, reviewer_id=current_user.id, decision=decision
    )
    return RedirectResponse("/agent/requests", status_code=303)
