"""Recrutement, formation, nesting et ramp-up."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.recruitment import RecruitmentPlan, RecruitmentRampWeek
from app.models.enums import UserRole
from app.models.skill import Skill
from app.models.user import User
from app.services.recruitment_service import create_recruitment_plan, list_ramp_weeks, project_ramp, progress_snapshot, update_progress

router = APIRouter(prefix="/recruitment", tags=["recruitment"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _reference_data(session: Session):
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True).order_by(Skill.campaign_id, Skill.name)).all())
    return campaigns, skills


@router.get("")
def recruitment_page(
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}
    plans = list(session.exec(select(RecruitmentPlan).order_by(RecruitmentPlan.start_date.desc())).all())
    rows = []
    for plan in plans:
        weeks = list_ramp_weeks(session, plan.id)
        rows.append({
            "plan": plan,
            "weeks": project_ramp(
                plan,
                weeks,
                concurrency_factor=(
                    float(skills_by_id[plan.skill_id].concurrency_factor)
                    if plan.skill_id in skills_by_id else 1.0
                ),
            ),
            "progress": progress_snapshot(plan),
            "campaign": campaigns_by_id.get(plan.campaign_id),
            "skill": skills_by_id.get(plan.skill_id),
        })
    return templates.TemplateResponse(
        request,
        "recruitment/index.html",
        {
            "active_nav": "recruitment",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "plans": rows,
            "can_edit": current_user.role in WRITE_ROLES,
            "errors": [],
        },
    )


@router.get("/new")
def recruitment_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "recruitment/form.html",
        {
            "active_nav": "recruitment",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_recruitment(
    request: Request,
    cohort_name: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    start_date: date = Form(...),
    headcount: int = Form(...),
    weekly_hours_contract: float = Form(40),
    training_weeks: int = Form(2),
    nesting_weeks: int = Form(2),
    training_aht_seconds: float = Form(...),
    training_occupancy_pct: float = Form(...),
    nesting_aht_seconds: float = Form(...),
    nesting_occupancy_pct: float = Form(...),
    nesting_capacity_factor_pct: float = Form(...),
    production_aht_seconds: float = Form(...),
    production_occupancy_pct: float = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        campaign = session.get(Campaign, campaign_id)
        skill = session.get(Skill, skill_id)
        if campaign is None or skill is None or skill.campaign_id != campaign_id:
            raise ValueError("Le skill doit appartenir à la campagne choisie.")
        plan = create_recruitment_plan(
            session,
            cohort_name=cohort_name,
            campaign_id=campaign_id,
            skill_id=skill_id,
            start_date=start_date,
            headcount=headcount,
            weekly_hours_contract=weekly_hours_contract,
            training_weeks=training_weeks,
            nesting_weeks=nesting_weeks,
            training_aht_seconds=training_aht_seconds,
            training_occupancy_pct=training_occupancy_pct,
            nesting_aht_seconds=nesting_aht_seconds,
            nesting_occupancy_pct=nesting_occupancy_pct,
            nesting_capacity_factor_pct=nesting_capacity_factor_pct,
            production_aht_seconds=production_aht_seconds,
            production_occupancy_pct=production_occupancy_pct,
            created_by=current_user.id,
            notes=notes,
        )
        return RedirectResponse(f"/recruitment#plan-{plan.id}", status_code=303)
    except ValueError as exc:
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "recruitment/form.html",
            {
                "active_nav": "recruitment",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": [str(exc)],
                "values": dict(
                    cohort_name=cohort_name, campaign_id=campaign_id, skill_id=skill_id,
                    start_date=start_date, headcount=headcount, weekly_hours_contract=weekly_hours_contract,
                    training_weeks=training_weeks, nesting_weeks=nesting_weeks,
                    training_aht_seconds=training_aht_seconds, training_occupancy_pct=training_occupancy_pct,
                    nesting_aht_seconds=nesting_aht_seconds, nesting_occupancy_pct=nesting_occupancy_pct,
                    nesting_capacity_factor_pct=nesting_capacity_factor_pct,
                    production_aht_seconds=production_aht_seconds, production_occupancy_pct=production_occupancy_pct,
                    notes=notes,
                ),
            },
            status_code=400,
        )


@router.post("/{plan_id}/progress", dependencies=[Depends(verify_csrf)])
def update_recruitment_progress(
    plan_id: int,
    recruited_hc: int = Form(...),
    training_hc: int = Form(...),
    nesting_hc: int = Form(...),
    production_hc: int = Form(...),
    exited_hc: int = Form(...),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    plan = session.get(RecruitmentPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Cohorte de recrutement introuvable.")
    try:
        update_progress(
            session,
            plan,
            recruited_hc=recruited_hc,
            training_hc=training_hc,
            nesting_hc=nesting_hc,
            production_hc=production_hc,
            exited_hc=exited_hc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(f"/recruitment#plan-{plan_id}", status_code=303)


@router.post("/{plan_id}/weeks/{week_id}", dependencies=[Depends(verify_csrf)])
def update_ramp_week(
    plan_id: int,
    week_id: int,
    aht_seconds: float = Form(...),
    occupancy_pct: float = Form(...),
    capacity_factor_pct: float = Form(...),
    stage: str = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    row = session.get(RecruitmentRampWeek, week_id)
    if row is None or row.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Semaine de ramp-up introuvable.")
    if aht_seconds <= 0 or not 0 <= occupancy_pct <= 100 or not 0 <= capacity_factor_pct <= 100:
        raise HTTPException(status_code=400, detail="AHT, occupancy et facteur de capacité sont invalides.")
    if stage not in {"training", "nesting", "production"}:
        raise HTTPException(status_code=400, detail="Étape de ramp-up invalide.")
    row.aht_seconds = aht_seconds
    row.occupancy_pct = occupancy_pct
    row.capacity_factor_pct = capacity_factor_pct
    row.stage = stage
    row.notes = notes.strip() or None
    session.add(row)
    session.commit()
    return RedirectResponse(f"/recruitment#plan-{plan_id}", status_code=303)
