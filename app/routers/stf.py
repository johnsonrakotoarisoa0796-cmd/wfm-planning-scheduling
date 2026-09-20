"""Module STF Weekly (§8) — réajustement hebdomadaire du LTF.

Lecture ouverte à tout utilisateur connecté ; création réservée à
admin/wfm_analyst, comme pour le LTF.
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
from app.models.enums import UserRole
from app.models.forecast import STFForecast
from app.models.skill import Skill
from app.models.user import User
from app.schemas.stf import STFCreateInput
from app.services import forecast_service, weekly_intraday_service

router = APIRouter(prefix="/stf", tags=["stf"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


@router.get("")
def list_stf(
    request: Request,
    iso_year: Optional[int] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    forecasts = forecast_service.list_current_stf_forecasts(
        session, iso_year=iso_year, campaign_id=campaign_id, skill_id=skill_id
    )
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}

    rows = [
        {
            "forecast": f,
            "campaign_name": campaigns_by_id[f.campaign_id].name if f.campaign_id in campaigns_by_id else "?",
            "skill_name": skills_by_id[f.skill_id].name if f.skill_id in skills_by_id else "?",
        }
        for f in forecasts
    ]

    return templates.TemplateResponse(
        request,
        "stf/list.html",
        {
            "active_nav": "stf",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"iso_year": iso_year, "campaign_id": campaign_id, "skill_id": skill_id},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.get("/new")
def new_stf_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "stf/form.html",
        {
            "active_nav": "stf",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_stf(
    request: Request,
    period: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    volume: float = Form(...),
    aht_seconds: float = Form(...),
    occupancy_pct: float = Form(...),
    shrinkage_pct: float = Form(...),
    service_level_target_pct: float = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    submitted_values = {
        "period": period,
        "campaign_id": campaign_id,
        "skill_id": skill_id,
        "volume": volume,
        "aht_seconds": aht_seconds,
        "occupancy_pct": occupancy_pct,
        "shrinkage_pct": shrinkage_pct,
        "service_level_target_pct": service_level_target_pct,
        "notes": notes,
    }

    try:
        iso_year_str, iso_week_str = period.split("-W")
        payload = STFCreateInput(
            iso_year=int(iso_year_str),
            iso_week=int(iso_week_str),
            campaign_id=campaign_id,
            skill_id=skill_id,
            volume=volume,
            aht_seconds=aht_seconds,
            occupancy_pct=occupancy_pct,
            shrinkage_pct=shrinkage_pct,
            service_level_target_pct=service_level_target_pct,
            notes=notes or None,
        )
        stf = forecast_service.create_stf_forecast(session, payload, created_by_user_id=current_user.id)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "stf/form.html",
            {
                "active_nav": "stf",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/stf/{stf.id}", status_code=303)


@router.post("/{stf_id}/disperse", dependencies=[Depends(verify_csrf)])
def disperse_stf(
    stf_id: int,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    stf = session.get(STFForecast, stf_id)
    if stf is None:
        raise HTTPException(status_code=404, detail="Forecast STF introuvable.")
    return RedirectResponse(
        url=f"/daily/from-stf/{stf.id}",
        status_code=303,
    )


@router.get("/{stf_id}")
def view_stf(
    stf_id: int,
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    stf = session.get(STFForecast, stf_id)
    if stf is None:
        raise HTTPException(status_code=404, detail="Forecast STF introuvable.")

    campaign = session.get(Campaign, stf.campaign_id)
    skill = session.get(Skill, stf.skill_id)

    week_start = stf.week_start_date
    parent_ltf = forecast_service.get_current_weekly_ltf_forecast(
        session,
        iso_year=stf.iso_year,
        iso_week=stf.iso_week,
        campaign_id=stf.campaign_id,
        skill_id=stf.skill_id,
    )
    if parent_ltf is None:
        parent_ltf = forecast_service.get_current_ltf_forecast(
            session,
            year=week_start.year,
            month=week_start.month,
            campaign_id=stf.campaign_id,
            skill_id=stf.skill_id,
        )
    comparison = forecast_service.compare_ltf_stf(parent_ltf, stf) if parent_ltf else None

    history = forecast_service.get_stf_version_history(
        session, campaign_id=stf.campaign_id, skill_id=stf.skill_id, iso_year=stf.iso_year, iso_week=stf.iso_week
    )

    return templates.TemplateResponse(
        request,
        "stf/detail.html",
        {
            "active_nav": "stf",
            "current_user": current_user,
            "stf": stf,
            "campaign": campaign,
            "skill": skill,
            "parent_ltf": parent_ltf,
            "comparison": comparison,
            "history": history,
        },
    )
