"""Module LTF Weekly (§6-§9) — forecast hebdomadaire, plan de référence long terme.

Lecture ouverte à tout utilisateur connecté ; création réservée à
admin/wfm_analyst (un team_lead ou viewer consulte mais ne modifie pas le
plan de référence).
"""

from datetime import date
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.enums import UserRole
from app.models.forecast import ForecastVersion, LTFForecast
from app.models.skill import Skill
from app.models.user import User
from app.schemas.ltf import LTFCreateInput
from app.services import channel_service, forecast_service, weekly_intraday_service

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
    handling_time_seconds: float = Form(...),
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
        normalized_period = raw_period.upper()
        if normalized_period.startswith("W") and normalized_period[1:].isdigit():
            iso_year = date.today().isocalendar().year
            iso_week = int(normalized_period[1:])
            year = month = None
        elif normalized_period.isdigit() and 1 <= int(normalized_period) <= 53:
            # Certains navigateurs (notamment selon leur implémentation de
            # <input type="week">) peuvent renvoyer uniquement le numéro de
            # semaine. Dans ce cas, on utilise l'année ISO courante.
            iso_year = date.today().isocalendar().year
            iso_week = int(normalized_period)
            year = month = None
        elif "-W" in normalized_period:
            raw_year, raw_week = normalized_period.split("-W", 1)
            iso_year, iso_week = int(raw_year), int(raw_week)
            year = month = None
        elif normalized_period:
            raw_year, raw_month = normalized_period.split("-", 1)
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
        "forecast_aht_seconds": handling_time_seconds,
        "handling_time_seconds": handling_time_seconds,
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
            forecast_aht_seconds=handling_time_seconds,
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



@router.get("/{ltf_id}/edit")
def edit_ltf_form(
    ltf_id: int,
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    ltf = session.get(LTFForecast, ltf_id)
    if ltf is None:
        raise HTTPException(status_code=404, detail="Forecast LTF introuvable.")
    version = session.get(ForecastVersion, ltf.forecast_version_id)
    if version is None or not version.is_current:
        raise HTTPException(status_code=400, detail="Seule la version LTF courante peut être rectifiée.")

    campaigns, skills = _reference_data(session)
    period = (
        f"{ltf.iso_year}-W{ltf.iso_week:02d}"
        if ltf.iso_year is not None and ltf.iso_week is not None
        else f"{ltf.year:04d}-{ltf.month:02d}"
    )
    values = {
        "period": period,
        "campaign_id": ltf.campaign_id,
        "skill_id": ltf.skill_id,
        "forecast_volume": ltf.forecast_volume,
        "forecast_aht_seconds": ltf.forecast_aht_seconds,
        "handling_time_seconds": ltf.forecast_aht_seconds,
        "aht_required_seconds": ltf.aht_required_seconds,
        "occupancy_required_pct": ltf.occupancy_required_pct,
        "service_level_target_pct": ltf.service_level_target_pct,
        "asa_target_seconds": ltf.asa_target_seconds,
        "indoor_shrinkage_pct": ltf.indoor_shrinkage_pct,
        "outdoor_shrinkage_pct": ltf.outdoor_shrinkage_pct,
        "notes": version.notes or "",
    }
    return templates.TemplateResponse(
        request,
        "ltf/form.html",
        {
            "active_nav": "ltf",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": values,
            "month_labels_fr": MONTH_LABELS_FR,
            "editing": True,
            "form_action": f"/ltf/{ltf_id}/edit",
        },
    )


@router.post("/{ltf_id}/edit", dependencies=[Depends(verify_csrf)])
def edit_ltf(
    ltf_id: int,
    request: Request,
    period: str = Form(""),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    forecast_volume: float = Form(...),
    handling_time_seconds: float = Form(...),
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
    ltf = session.get(LTFForecast, ltf_id)
    if ltf is None:
        raise HTTPException(status_code=404, detail="Forecast LTF introuvable.")
    current_version = session.get(ForecastVersion, ltf.forecast_version_id)
    if current_version is None or not current_version.is_current:
        raise HTTPException(status_code=400, detail="Seule la version LTF courante peut être rectifiée.")

    expected_period = (
        f"{ltf.iso_year}-W{ltf.iso_week:02d}"
        if ltf.iso_year is not None and ltf.iso_week is not None
        else f"{ltf.year:04d}-{ltf.month:02d}"
    )
    if period.strip().upper() != expected_period.upper() or campaign_id != ltf.campaign_id or skill_id != ltf.skill_id:
        raise HTTPException(
            status_code=400,
            detail="La période, la campagne et le skill ne peuvent pas être modifiés lors d'une rectification.",
        )

    raw_period = period.strip().upper()
    iso_year = iso_week = None
    if "-W" in raw_period:
        raw_year, raw_week = raw_period.split("-W", 1)
        iso_year, iso_week = int(raw_year), int(raw_week)
        year = month = None
    elif raw_period.startswith("W") and raw_period[1:].isdigit():
        iso_year, iso_week = date.today().isocalendar().year, int(raw_period[1:])
        year = month = None
    elif raw_period.isdigit():
        iso_year, iso_week = date.today().isocalendar().year, int(raw_period)
        year = month = None
    else:
        raw_year, raw_month = raw_period.split("-", 1)
        year, month = int(raw_year), int(raw_month)

    payload = LTFCreateInput(
        iso_year=iso_year,
        iso_week=iso_week,
        year=year,
        month=month,
        campaign_id=campaign_id,
        skill_id=skill_id,
        forecast_volume=forecast_volume,
        forecast_aht_seconds=handling_time_seconds,
        aht_required_seconds=aht_required_seconds,
        occupancy_required_pct=occupancy_required_pct,
        service_level_target_pct=service_level_target_pct,
        asa_target_seconds=asa_target_seconds,
        indoor_shrinkage_pct=indoor_shrinkage_pct,
        outdoor_shrinkage_pct=outdoor_shrinkage_pct,
        notes=notes or None,
    )
    forecast_service.create_ltf_forecast(session, payload, created_by_user_id=current_user.id)
    return RedirectResponse(url="/ltf?success=Forecast+LTF+rectifié+%3A+ancienne+version+conservée", status_code=303)


@router.post("/{ltf_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_ltf(
    ltf_id: int,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        forecast_service.delete_ltf_forecast(session, ltf_id)
    except ValueError as exc:
        return RedirectResponse(f"/ltf?error={quote_plus(str(exc))}", status_code=303)
    return RedirectResponse("/ltf?success=LTF+supprimé+ou+version+précédente+restaurée", status_code=303)

@router.post("/{ltf_id}/disperse", dependencies=[Depends(verify_csrf)])
def disperse_ltf(
    ltf_id: int,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    ltf = session.get(LTFForecast, ltf_id)
    if ltf is None:
        raise HTTPException(status_code=404, detail="Forecast LTF introuvable.")
    try:
        weekly_intraday_service.disperse_ltf(session, ltf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        url=f"/daily?campaign_id={ltf.campaign_id}&skill_id={ltf.skill_id}",
        status_code=303,
    )


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
            "concurrency_factor": channel_service.concurrency_for_channel(skill.channel),
            "contact_handling_hours": ltf.forecast_volume * ltf.forecast_aht_seconds / 3600.0,
            "agent_workload_hours": channel_service.normalized_workload_hours(ltf.forecast_volume, ltf.forecast_aht_seconds, skill.channel),
            "campaign": campaign,
            "skill": skill,
            "history": history,
            "stf_weeks": stf_weeks,
        },
    )
