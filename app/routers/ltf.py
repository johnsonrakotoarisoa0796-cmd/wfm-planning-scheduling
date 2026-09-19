"""Module LTF Monthly (§6-§9) — forecast mensuel, plan de référence long terme.

Lecture ouverte à tout utilisateur connecté ; création réservée à
admin/wfm_analyst (un team_lead ou viewer consulte mais ne modifie pas le
plan de référence).
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
from app.models.forecast import LTFForecast
from app.models.skill import Skill
from app.models.user import User
from app.schemas.ltf import LTFCreateInput
from app.services import forecast_service

router = APIRouter(prefix="/ltf", tags=["ltf"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)

MONTH_LABELS_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


@router.get("")
def list_ltf(
    request: Request,
    year: Optional[int] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    forecasts = forecast_service.list_current_ltf_forecasts(
        session, year=year, campaign_id=campaign_id, skill_id=skill_id
    )
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}

    rows = [
        {
            "forecast": f,
            "month_label": MONTH_LABELS_FR[f.month],
            "campaign_name": campaigns_by_id[f.campaign_id].name if f.campaign_id in campaigns_by_id else "?",
            "skill_name": skills_by_id[f.skill_id].name if f.skill_id in skills_by_id else "?",
        }
        for f in forecasts
    ]

    return templates.TemplateResponse(
        request,
        "ltf/list.html",
        {
            "active_nav": "ltf",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"year": year, "campaign_id": campaign_id, "skill_id": skill_id},
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.get("/new")
def new_ltf_form(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "ltf/form.html",
        {
            "active_nav": "ltf",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
            "month_labels_fr": MONTH_LABELS_FR,
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_ltf(
    request: Request,
    period: str = Form(""),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    forecast_volume: float = Form(...),
    forecast_aht_seconds: float = Form(...),
    aht_required_seconds: float = Form(...),
    occupancy_required_pct: float = Form(...),
    service_level_target_pct: float = Form(...),
    asa_target_seconds: float = Form(...),
    indoor_shrinkage_pct: float = Form(...),
    outdoor_shrinkage_pct: float = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    iso_year = iso_week = None
    raw_period = period.strip()
    try:
        if "-W" in raw_period:
            raw_year, raw_week = raw_period.split("-W", 1)
            iso_year, iso_week = int(raw_year), int(raw_week)
            year = month = None
        elif raw_period:
            raw_year, raw_month = raw_period.split("-", 1)
            year, month = int(raw_year), int(raw_month)
        elif year is None or month is None:
            raise ValueError("La période LTF est obligatoire au format YYYY-Www.")
    except (TypeError, ValueError):
        iso_year = iso_week = None
        if not raw_period:
            year = month = None

    submitted_values = {
        "period": raw_period,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "year": year,
        "month": month,
        "campaign_id": campaign_id,
        "skill_id": skill_id,
        "forecast_volume": forecast_volume,
        "forecast_aht_seconds": forecast_aht_seconds,
        "aht_required_seconds": aht_required_seconds,
        "occupancy_required_pct": occupancy_required_pct,
        "service_level_target_pct": service_level_target_pct,
        "asa_target_seconds": asa_target_seconds,
        "indoor_shrinkage_pct": indoor_shrinkage_pct,
        "outdoor_shrinkage_pct": outdoor_shrinkage_pct,
        "notes": notes,
    }

    try:
        payload = LTFCreateInput(
            iso_year=iso_year,
            iso_week=iso_week,
            year=year,
            month=month,
            campaign_id=campaign_id,
            skill_id=skill_id,
            forecast_volume=forecast_volume,
            forecast_aht_seconds=forecast_aht_seconds,
            aht_required_seconds=aht_required_seconds,
            occupancy_required_pct=occupancy_required_pct,
            service_level_target_pct=service_level_target_pct,
            asa_target_seconds=asa_target_seconds,
            indoor_shrinkage_pct=indoor_shrinkage_pct,
            outdoor_shrinkage_pct=outdoor_shrinkage_pct,
            notes=notes or None,
        )
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "ltf/form.html",
            {
                "active_nav": "ltf",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": submitted_values,
                "month_labels_fr": MONTH_LABELS_FR,
            },
            status_code=400,
        )

    forecast_service.create_ltf_forecast(session, payload, created_by_user_id=current_user.id)
    return RedirectResponse(url="/ltf", status_code=303)


@router.get("/{ltf_id}")
def view_ltf(
    ltf_id: int,
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    ltf = session.get(LTFForecast, ltf_id)
    if ltf is None:
        raise HTTPException(status_code=404, detail="Forecast LTF introuvable.")

    campaign = session.get(Campaign, ltf.campaign_id)
    skill = session.get(Skill, ltf.skill_id)
    history = forecast_service.get_ltf_version_history(
        session, campaign_id=ltf.campaign_id, skill_id=ltf.skill_id, year=ltf.year, month=ltf.month
    )
    stf_weeks = forecast_service.get_stf_forecasts_for_ltf_version(session, ltf.forecast_version_id)

    return templates.TemplateResponse(
        request,
        "ltf/detail.html",
        {
            "active_nav": "ltf",
            "current_user": current_user,
            "ltf": ltf,
            "month_label": MONTH_LABELS_FR[ltf.month],
            "campaign": campaign,
            "skill": skill,
            "history": history,
            "stf_weeks": stf_weeks,
        },
    )
