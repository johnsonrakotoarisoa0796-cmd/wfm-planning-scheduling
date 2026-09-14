"""Module Overtime (§26-§30) — Required OT calculé depuis Daily/Intraday,
Actual OT saisi séparément, jamais confondus.

Création/calcul réservés à admin/wfm_analyst (comme LTF/STF/Capacity) ;
saisie de l'Actual OT ouverte aussi au team_lead (opérationnel, même RBAC
que les actuals Daily/Intraday et Shrinkage).
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.enums import PeriodType, UserRole
from app.models.overtime import OvertimePlan
from app.models.skill import Skill
from app.models.user import User
from app.schemas.overtime import OvertimeActualInput, OvertimePlanInput
from app.services import kpi_service, overtime_service

router = APIRouter(prefix="/overtime", tags=["overtime"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)
ACTUAL_ENTRY_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST, UserRole.TEAM_LEAD)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


@router.get("")
def list_overtime(
    request: Request,
    period_type: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    parsed_period_type = PeriodType(period_type) if period_type else None
    plans = overtime_service.list_overtime_plans(
        session, period_type=parsed_period_type, campaign_id=campaign_id, skill_id=skill_id
    )
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}

    rows = [
        {
            "plan": p,
            "campaign_name": campaigns_by_id[p.campaign_id].name if p.campaign_id in campaigns_by_id else "?",
            "skill_name": skills_by_id[p.skill_id].name if p.skill_id in skills_by_id else "?",
            "variance": kpi_service.overtime_variance(p.ot_required_hours, p.ot_actual_hours) if p.ot_actual_hours is not None else None,
        }
        for p in plans
    ]

    return templates.TemplateResponse(
        request,
        "overtime/list.html",
        {
            "active_nav": "overtime",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"period_type": period_type, "campaign_id": campaign_id, "skill_id": skill_id},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.get("/new")
def new_overtime_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "overtime/form.html",
        {
            "active_nav": "overtime",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_overtime(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    period_type: str = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {
        "start_date": start_date, "end_date": end_date, "campaign_id": campaign_id,
        "skill_id": skill_id, "period_type": period_type, "notes": notes,
    }
    try:
        payload = OvertimePlanInput(**{**submitted_values, "notes": notes or None})
        plan = overtime_service.upsert_overtime_plan(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "overtime/form.html",
            {
                "active_nav": "overtime",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/overtime/{plan.id}", status_code=303)


@router.get("/{plan_id}")
def view_overtime(
    plan_id: int,
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    plan = session.get(OvertimePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan Overtime introuvable.")

    campaign = session.get(Campaign, plan.campaign_id)
    skill = session.get(Skill, plan.skill_id)

    variance = kpi_service.overtime_variance(plan.ot_required_hours, plan.ot_actual_hours) if plan.ot_actual_hours is not None else None

    # Graphique "OT Required by Day" (§29) : recalculé en direct depuis les
    # intervalles actuels pour la plage du plan, pour visualiser la forme
    # jour par jour — les totaux affichés au-dessus restent l'instantané
    # enregistré (peuvent légèrement diverger si les intervalles ont changé
    # depuis, comme pour Capacity Planning).
    range_start, range_end = overtime_service.date_range_from_period_key(plan.period_type, plan.period_key)
    report = overtime_service.compute_overtime_report(
        session, start_date=range_start, end_date=range_end, campaign_id=plan.campaign_id, skill_id=plan.skill_id
    )
    chart_labels = [str(point.day) for point in report.daily_breakdown]
    chart_values = [round(point.ot_required_hours, 1) for point in report.daily_breakdown]

    return templates.TemplateResponse(
        request,
        "overtime/detail.html",
        {
            "active_nav": "overtime",
            "current_user": current_user,
            "plan": plan,
            "campaign": campaign,
            "skill": skill,
            "variance": variance,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "can_enter_actual": current_user.role in ACTUAL_ENTRY_ROLES,
        },
    )


@router.post("/{plan_id}/actual", dependencies=[Depends(verify_csrf)])
def submit_actual_ot(
    plan_id: int,
    request: Request,
    ot_actual_hours: float = Form(...),
    current_user: User = Depends(require_role(*ACTUAL_ENTRY_ROLES)),
    session: Session = Depends(get_session),
):
    plan = session.get(OvertimePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan Overtime introuvable.")

    try:
        overtime_service.update_actual_ot(session, plan_id=plan_id, data=OvertimeActualInput(ot_actual_hours=ot_actual_hours))
    except ValidationError:
        raise HTTPException(status_code=400, detail="Valeur d'OT réel invalide.")

    return RedirectResponse(url=f"/overtime/{plan_id}", status_code=303)
