"""Module Capacity Planning (§31) — projection HC, gap vs Required (LTF).

Lecture ouverte à tout utilisateur connecté ; écriture réservée à
admin/wfm_analyst, comme pour le LTF/STF.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.capacity import CapacityPlan
from app.models.enums import UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.capacity import CapacityPlanInput
from app.services import capacity_service, kpi_service

router = APIRouter(prefix="/capacity", tags=["capacity"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


@router.get("")
def list_capacity(
    request: Request,
    period: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    plans = capacity_service.list_capacity_plans(session, period=period, campaign_id=campaign_id, skill_id=skill_id)
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}

    rows = [
        {
            "plan": p,
            "campaign_name": campaigns_by_id[p.campaign_id].name if p.campaign_id in campaigns_by_id else "?",
            "skill_name": skills_by_id[p.skill_id].name if p.skill_id in skills_by_id else "?",
            "gap": kpi_service.staffing_gap(p.projected_hc, p.required_hc),
            "status": kpi_service.staffing_status(kpi_service.staffing_gap(p.projected_hc, p.required_hc)).value,
        }
        for p in plans
    ]

    return templates.TemplateResponse(
        request,
        "capacity/list.html",
        {
            "active_nav": "capacity",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"period": period, "campaign_id": campaign_id, "skill_id": skill_id},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.get("/new")
def new_capacity_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "capacity/form.html",
        {
            "active_nav": "capacity",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_capacity(
    request: Request,
    period: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    current_hc: float = Form(...),
    hiring: float = Form(0),
    transfers_in: float = Form(0),
    transfers_out: float = Form(0),
    attrition_pct: float = Form(0),
    absenteeism_pct: float = Form(0),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {
        "period": period, "campaign_id": campaign_id, "skill_id": skill_id,
        "current_hc": current_hc, "hiring": hiring, "transfers_in": transfers_in,
        "transfers_out": transfers_out, "attrition_pct": attrition_pct,
        "absenteeism_pct": absenteeism_pct, "notes": notes,
    }
    try:
        payload = CapacityPlanInput(**{**submitted_values, "notes": notes or None})
        plan = capacity_service.upsert_capacity_plan(session, payload, created_by_user_id=current_user.id)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "capacity/form.html",
            {
                "active_nav": "capacity",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/capacity/{plan.id}", status_code=303)


@router.get("/{plan_id}")
def view_capacity(
    plan_id: int,
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    plan = session.get(CapacityPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan de capacité introuvable.")

    campaign = session.get(Campaign, plan.campaign_id)
    skill = session.get(Skill, plan.skill_id)

    current_gap = kpi_service.staffing_gap(plan.current_hc, plan.required_hc)
    projected_gap = kpi_service.staffing_gap(plan.projected_hc, plan.required_hc)

    return templates.TemplateResponse(
        request,
        "capacity/detail.html",
        {
            "active_nav": "capacity",
            "current_user": current_user,
            "plan": plan,
            "campaign": campaign,
            "skill": skill,
            "current_gap": current_gap,
            "current_status": kpi_service.staffing_status(current_gap).value,
            "projected_gap": projected_gap,
            "projected_status": kpi_service.staffing_status(projected_gap).value,
        },
    )
