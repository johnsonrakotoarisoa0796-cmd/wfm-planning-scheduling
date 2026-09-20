"""Interface Compliance & Weekly Coverage."""
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
from app.models.enums import UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.compliance import CompliancePolicyInput
from app.services import compliance_service

router = APIRouter(prefix="/compliance", tags=["compliance"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _page(
    request: Request,
    session: Session,
    current_user: User,
    *,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    week: Optional[str] = None,
    errors: list[str] | None = None,
    report=None,
    values: Optional[dict] = None,
    status_code: int = 200,
):
    campaigns = list(
        session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all()  # noqa: E712
    )
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())
    policies = compliance_service.list_policies(session, campaign_id=campaign_id)
    policy = compliance_service.get_policy(session, campaign_id=campaign_id, skill_id=skill_id) if campaign_id else None

    if values is None and policy is not None:
        values = {
            "campaign_id": policy.campaign_id,
            "skill_id": policy.skill_id or "",
            "name": policy.name,
            "max_consecutive_work_days": policy.max_consecutive_work_days,
            "max_daily_hours": policy.max_daily_hours,
            "max_weekly_hours": policy.max_weekly_hours,
            "max_weekly_overtime_hours": policy.max_weekly_overtime_hours,
            "min_rest_hours": policy.min_rest_hours,
            "weekly_coverage_target_pct": policy.weekly_coverage_target_pct,
            "notes": policy.notes or "",
        }

    try:
        week_start = (
            date.fromisocalendar(*[int(x) for x in (week.split("-W") if week and "-W" in week else [])])
            if week and "-W" in week
            else date.today() - timedelta(days=date.today().weekday())
        )
        if week and "-W" in week:
            year_text, week_text = week.split("-W", 1)
            week_start = date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError):
        week_start = date.today() - timedelta(days=date.today().weekday())
        week = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"

    if not week:
        week = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"

    return templates.TemplateResponse(
        request,
        "compliance/index.html",
        {
            "active_nav": "compliance",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "policies": policies,
            "policy": policy,
            "filters": {"campaign_id": campaign_id, "skill_id": skill_id, "week": week},
            "values": values or {},
            "errors": errors or [],
            "report": report,
            "can_edit": current_user.role in WRITE_ROLES,
        },
        status_code=status_code,
    )


@router.get("")
def compliance_page(
    request: Request,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    week: Optional[str] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    report = None
    errors = []
    if campaign_id is not None and skill_id is not None and week:
        try:
            year_text, week_text = week.split("-W", 1)
            week_start = date.fromisocalendar(int(year_text), int(week_text), 1)
            report = compliance_service.evaluate_week(
                session,
                week_start_date=week_start,
                campaign_id=campaign_id,
                skill_id=skill_id,
            )
        except (ValueError, TypeError) as exc:
            errors = [str(exc)]
    return _page(
        request, session, current_user,
        campaign_id=campaign_id, skill_id=skill_id, week=week,
        errors=errors, report=report,
    )


@router.post("/policy", dependencies=[Depends(verify_csrf)])
def save_policy(
    request: Request,
    campaign_id: int = Form(...),
    skill_id: str = Form(""),
    name: str = Form("Standard WFM"),
    max_consecutive_work_days: int = Form(5),
    max_daily_hours: float = Form(10),
    max_weekly_hours: float = Form(48),
    max_weekly_overtime_hours: float = Form(8),
    min_rest_hours: float = Form(11),
    weekly_coverage_target_pct: float = Form(95),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    values = {
        "campaign_id": campaign_id,
        "skill_id": int(skill_id) if skill_id.strip() else None,
        "name": name,
        "max_consecutive_work_days": max_consecutive_work_days,
        "max_daily_hours": max_daily_hours,
        "max_weekly_hours": max_weekly_hours,
        "max_weekly_overtime_hours": max_weekly_overtime_hours,
        "min_rest_hours": min_rest_hours,
        "weekly_coverage_target_pct": weekly_coverage_target_pct,
        "notes": notes,
    }
    try:
        payload = CompliancePolicyInput(**values)
        compliance_service.upsert_policy(
            session, payload, created_by_user_id=current_user.id
        )
    except (ValidationError, ValueError) as exc:
        errors = [str(item["msg"]) for item in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        return _page(
            request, session, current_user,
            campaign_id=campaign_id, skill_id=values["skill_id"],
            week=request.query_params.get("week"),
            errors=errors, values=values, status_code=400,
        )
    return RedirectResponse(
        url=f"/compliance?campaign_id={campaign_id}"
            + (f"&skill_id={values['skill_id']}" if values["skill_id"] else ""),
        status_code=303,
    )


@router.get("/check")
def check_week(
    request: Request,
    week: str,
    campaign_id: int,
    skill_id: int,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    year_text, week_text = week.split("-W", 1)
    report = compliance_service.evaluate_week(
        session,
        week_start_date=date.fromisocalendar(int(year_text), int(week_text), 1),
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    return _page(
        request, session, current_user,
        campaign_id=campaign_id, skill_id=skill_id, week=week,
        report=report,
    )
