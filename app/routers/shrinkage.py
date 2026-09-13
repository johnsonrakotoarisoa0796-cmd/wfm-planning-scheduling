"""Module Shrinkage (§23-§25) — enregistrement + rapport indoor/outdoor.

Une seule vue de rapport sert Monthly/Weekly/Daily (§25) : l'utilisateur
choisit une plage de dates, qui peut représenter un mois, une semaine ou
un jour selon ce qu'il sélectionne — inutile de tripler le code pour trois
pages identiques dans leur logique.

Lecture ouverte à tout utilisateur connecté ; enregistrement réservé à
admin/wfm_analyst/team_lead (pilotage opérationnel, même RBAC que la
saisie d'actuals en Daily/Intraday).
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
from app.models.employee import Employee
from app.models.enums import UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.shrinkage import ShrinkageRecordInput
from app.services import shrinkage_service

router = APIRouter(prefix="/shrinkage", tags=["shrinkage"])

RECORD_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST, UserRole.TEAM_LEAD)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill], list[Employee]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    employees = list(session.exec(select(Employee)).all())
    return campaigns, skills, employees


@router.get("")
def shrinkage_report(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    # Par défaut : semaine glissante se terminant aujourd'hui (vue "Weekly").
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=6)

    campaigns, skills, employees = _reference_data(session)
    categories = shrinkage_service.list_active_categories(session)

    records = shrinkage_service.list_shrinkage_records(
        session, start_date=start_date, end_date=end_date, campaign_id=campaign_id, skill_id=skill_id
    )

    summary = None
    if skill_id is not None:
        summary = shrinkage_service.compute_shrinkage_summary(
            session, records, categories, skill_id=skill_id, start_date=start_date, end_date=end_date
        )

    employees_by_id = {e.id: e for e in employees}
    categories_by_id = {c.id: c for c in categories}
    detail_rows = [
        {
            "record": r,
            "employee_name": f"{employees_by_id[r.employee_id].first_name} {employees_by_id[r.employee_id].last_name}"
            if r.employee_id in employees_by_id else "?",
            "category_name": categories_by_id[r.category_id].name if r.category_id in categories_by_id else "?",
        }
        for r in records
    ]

    return templates.TemplateResponse(
        request,
        "shrinkage/report.html",
        {
            "active_nav": "shrinkage",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"start_date": start_date, "end_date": end_date, "campaign_id": campaign_id, "skill_id": skill_id},
            "summary": summary,
            "detail_rows": detail_rows,
            "can_record": current_user.role in RECORD_ROLES,
        },
    )


@router.get("/new")
def new_record_form(
    request: Request,
    current_user: User = Depends(require_role(*RECORD_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills, employees = _reference_data(session)
    categories = shrinkage_service.list_active_categories(session)
    return templates.TemplateResponse(
        request,
        "shrinkage/form.html",
        {
            "active_nav": "shrinkage",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "employees": employees,
            "categories": categories,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_record(
    request: Request,
    employee_id: int = Form(...),
    category_id: int = Form(...),
    record_date: date = Form(...),
    hours: float = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*RECORD_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {
        "employee_id": employee_id, "category_id": category_id, "record_date": record_date,
        "hours": hours, "campaign_id": campaign_id, "skill_id": skill_id, "notes": notes,
    }
    try:
        payload = ShrinkageRecordInput(**{**submitted_values, "notes": notes or None})
        shrinkage_service.record_shrinkage(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills, employees = _reference_data(session)
        categories = shrinkage_service.list_active_categories(session)
        return templates.TemplateResponse(
            request,
            "shrinkage/form.html",
            {
                "active_nav": "shrinkage",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "employees": employees,
                "categories": categories,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(
        url=f"/shrinkage?start_date={record_date}&end_date={record_date}&campaign_id={campaign_id}&skill_id={skill_id}",
        status_code=303,
    )
