"""Page Workforce dédiée à chaque campagne."""
from __future__ import annotations

from datetime import date
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
from app.models.user import User
from app.schemas.campaign_workforce import CampaignWorkforcePlanInput
from app.services.campaign_workforce_service import calculate_metrics, get_plan, roster_snapshot, upsert_plan

router = APIRouter(prefix="/campaigns", tags=["campaign-workforce"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _default_period() -> str:
    return date.today().strftime("%Y-%m")


def _campaign_or_404(session: Session, campaign_id: int) -> Campaign:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Campagne introuvable.")
    return campaign


@router.get("/{campaign_id}/workforce")
def campaign_workforce_page(
    request: Request,
    campaign_id: int,
    period: Optional[str] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaign = _campaign_or_404(session, campaign_id)
    selected_period = period or _default_period()
    plan = get_plan(session, campaign_id=campaign_id, period=selected_period)
    roster = roster_snapshot(session, campaign_id=campaign_id, period=selected_period)

    values = {
        "period": selected_period,
        "campaign_id": campaign_id,
        "current_hc": plan.current_hc if plan else float(roster.active_roster_hc),
        "available_hc": plan.available_hc if plan else float(roster.active_roster_hc),
        "long_leave_hc": plan.long_leave_hc if plan else 0,
        "training_hc": plan.training_hc if plan else 0,
        "nesting_hc": plan.nesting_hc if plan else 0,
        "other_unavailable_hc": plan.other_unavailable_hc if plan else 0,
        "attrition_pct": plan.attrition_pct if plan else 0,
        "hiring_hc": plan.hiring_hc if plan else 0,
        "transfers_in_hc": plan.transfers_in_hc if plan else 0,
        "transfers_out_hc": plan.transfers_out_hc if plan else 0,
        "required_hc": plan.required_hc if plan else 0,
        "notes": plan.notes if plan else "",
    }
    metrics = calculate_metrics(plan) if plan else None

    return templates.TemplateResponse(
        request,
        "campaigns/workforce.html",
        {
            "active_nav": "settings",
            "current_user": current_user,
            "campaign": campaign,
            "plan": plan,
            "values": values,
            "metrics": metrics,
            "roster": roster,
            "can_edit": current_user.role in WRITE_ROLES,
            "errors": [],
        },
    )


@router.post("/{campaign_id}/workforce", dependencies=[Depends(verify_csrf)])
def save_campaign_workforce(
    request: Request,
    campaign_id: int,
    period: str = Form(...),
    current_hc: float = Form(...),
    available_hc: float = Form(...),
    long_leave_hc: float = Form(0),
    training_hc: float = Form(0),
    nesting_hc: float = Form(0),
    other_unavailable_hc: float = Form(0),
    attrition_pct: float = Form(0),
    hiring_hc: float = Form(0),
    transfers_in_hc: float = Form(0),
    transfers_out_hc: float = Form(0),
    required_hc: float = Form(0),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted = {
        "period": period,
        "campaign_id": campaign_id,
        "current_hc": current_hc,
        "available_hc": available_hc,
        "long_leave_hc": long_leave_hc,
        "training_hc": training_hc,
        "nesting_hc": nesting_hc,
        "other_unavailable_hc": other_unavailable_hc,
        "attrition_pct": attrition_pct,
        "hiring_hc": hiring_hc,
        "transfers_in_hc": transfers_in_hc,
        "transfers_out_hc": transfers_out_hc,
        "required_hc": required_hc,
        "notes": notes,
    }
    try:
        data = CampaignWorkforcePlanInput(**submitted)
        plan = upsert_plan(session, data, created_by_user_id=current_user.id)
    except (ValidationError, ValueError) as exc:
        campaign = _campaign_or_404(session, campaign_id)
        roster = roster_snapshot(session, campaign_id=campaign_id, period=period)
        errors = [str(item["msg"]) for item in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        metrics = None
        return templates.TemplateResponse(
            request,
            "campaigns/workforce.html",
            {
                "active_nav": "settings",
                "current_user": current_user,
                "campaign": campaign,
                "plan": None,
                "values": submitted,
                "metrics": metrics,
                "roster": roster,
                "can_edit": True,
                "errors": errors,
            },
            status_code=400,
        )

    return RedirectResponse(
        f"/campaigns/{campaign_id}/workforce?period={plan.period}&saved=1",
        status_code=303,
    )
