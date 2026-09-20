"""Module Daily/Intraday (§10) — granularité 30 minutes, Erlang C par intervalle.

Lecture ouverte à tout utilisateur connecté ; génération réservée à
admin/wfm_analyst. La saisie des actuals (planning réel, volumes réels)
est ouverte aussi au team_lead, qui pilote l'opérationnel au jour le jour
sans nécessairement construire les forecasts long terme.
"""

from datetime import date as DateType
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
from app.models.market import Market
from app.models.intraday import IntervalForecast
from app.models.skill import Skill
from app.models.user import User
from app.schemas.intraday import GenerateIntradayInput, IntervalUpdateInput, WeeklyDispersionInput
from app.services import channel_service, client_stf_service, intraday_service, weekly_intraday_service

router = APIRouter(prefix="/daily", tags=["daily"])

GENERATE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)
UPDATE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST, UserRole.TEAM_LEAD)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


@router.get("")
def list_days(
    request: Request,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    days = intraday_service.list_days_with_intervals(session, campaign_id=campaign_id, skill_id=skill_id)
    campaigns, skills = _reference_data(session)
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {s.id: s for s in skills}

    rows = [
        {
            **day,
            "campaign_name": campaigns_by_id[day["campaign_id"]].name if day["campaign_id"] in campaigns_by_id else "?",
            "skill_name": skills_by_id[day["skill_id"]].name if day["skill_id"] in skills_by_id else "?",
        }
        for day in days
    ]

    return templates.TemplateResponse(
        request,
        "daily/list.html",
        {
            "active_nav": "daily",
            "current_user": current_user,
            "rows": rows,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"campaign_id": campaign_id, "skill_id": skill_id},
            "can_generate": current_user.role in GENERATE_ROLES,
        },
    )


@router.get("/new")
def new_day_form(
    request: Request,
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    return templates.TemplateResponse(
        request,
        "daily/form.html",
        {
            "active_nav": "daily",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "errors": [],
            "values": {},
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_day(
    request: Request,
    target_date: DateType = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    timezone_name: str = Form(""),
    daily_volume: float = Form(...),
    daily_aht_seconds: float = Form(...),
    service_level_target_pct: float = Form(...),
    answer_time_target_seconds: float = Form(...),
    occupancy_target_pct: float = Form(...),
    shrinkage_pct: float = Form(...),
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
    session: Session = Depends(get_session),
):
    effective_timezone = timezone_name.strip()
    if not effective_timezone:
        skill = session.get(Skill, skill_id)
        if skill is not None and skill.market_id is not None:
            market = session.get(Market, skill.market_id)
            effective_timezone = market.timezone_name if market is not None else "UTC"
        else:
            effective_timezone = "UTC"

    submitted_values = {
        "target_date": target_date, "campaign_id": campaign_id, "skill_id": skill_id,
        "timezone_name": effective_timezone,
        "daily_volume": daily_volume, "daily_aht_seconds": daily_aht_seconds,
        "service_level_target_pct": service_level_target_pct,
        "answer_time_target_seconds": answer_time_target_seconds,
        "occupancy_target_pct": occupancy_target_pct, "shrinkage_pct": shrinkage_pct,
    }
    try:
        payload = GenerateIntradayInput(**submitted_values)
        intraday_service.generate_intraday_forecast(session, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        campaigns, skills = _reference_data(session)
        return templates.TemplateResponse(
            request,
            "daily/form.html",
            {
                "active_nav": "daily",
                "current_user": current_user,
                "campaigns": campaigns,
                "skills": skills,
                "errors": errors,
                "values": submitted_values,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/daily/view?target_date={target_date}&campaign_id={campaign_id}&skill_id={skill_id}", status_code=303)



@router.get("/from-stf/{stf_id}")
def disperse_from_stf_form(
    stf_id: int,
    request: Request,
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
    session: Session = Depends(get_session),
):
    from datetime import timedelta
    from app.models.forecast import STFForecast

    stf = session.get(STFForecast, stf_id)
    if stf is None:
        raise HTTPException(status_code=404, detail="Forecast STF introuvable.")

    campaign = session.get(Campaign, stf.campaign_id)
    skill = session.get(Skill, stf.skill_id)
    weights = [13.0, 14.0, 16.0, 17.0, 14.0, 13.0, 13.0]
    intraday_profile_pct = intraday_service.default_intraday_window_profile_pct()
    intraday_slots = [
        "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
        "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
        "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30",
        "22:00", "22:30", "23:00", "23:30", "00:00", "00:30", "01:00", "01:30", "02:00",
    ]
    days = [
        ("Lundi", stf.week_start_date + timedelta(days=0), weights[0]),
        ("Mardi", stf.week_start_date + timedelta(days=1), weights[1]),
        ("Mercredi", stf.week_start_date + timedelta(days=2), weights[2]),
        ("Jeudi", stf.week_start_date + timedelta(days=3), weights[3]),
        ("Vendredi", stf.week_start_date + timedelta(days=4), weights[4]),
        ("Samedi", stf.week_start_date + timedelta(days=5), weights[5]),
        ("Dimanche", stf.week_start_date + timedelta(days=6), weights[6]),
    ]
    return templates.TemplateResponse(
        request,
        "daily/from_stf.html",
        {
            "active_nav": "daily",
            "current_user": current_user,
            "stf": stf,
            "campaign": campaign,
            "skill": skill,
            "days": days,
            "weights": weights,
            "total_weight": sum(weights),
            "daily_volumes": [stf.volume * w / 100.0 for w in weights],
            "intraday_profile_pct": intraday_profile_pct,
            "intraday_slots": intraday_slots,
            "errors": [],
        },
    )


@router.post("/from-stf/{stf_id}", dependencies=[Depends(verify_csrf)])
def disperse_from_stf_action(
    stf_id: int,
    request: Request,
    monday_pct: float = Form(...),
    tuesday_pct: float = Form(...),
    wednesday_pct: float = Form(...),
    thursday_pct: float = Form(...),
    friday_pct: float = Form(...),
    saturday_pct: float = Form(...),
    sunday_pct: float = Form(...),
    intraday_profile_pct: list[float] = Form(...),
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
    session: Session = Depends(get_session),
):
    from datetime import timedelta
    from app.models.forecast import STFForecast

    stf = session.get(STFForecast, stf_id)
    if stf is None:
        raise HTTPException(status_code=404, detail="Forecast STF introuvable.")

    intraday_slots = [
        "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
        "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
        "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30",
        "22:00", "22:30", "23:00", "23:30", "00:00", "00:30", "01:00", "01:30", "02:00",
    ]
    values = {
        "monday_pct": monday_pct,
        "tuesday_pct": tuesday_pct,
        "wednesday_pct": wednesday_pct,
        "thursday_pct": thursday_pct,
        "friday_pct": friday_pct,
        "saturday_pct": saturday_pct,
        "sunday_pct": sunday_pct,
        "intraday_profile_pct": intraday_profile_pct,
    }

    try:
        payload = WeeklyDispersionInput(**values)
        payload.validate_total()
        weekly_intraday_service.disperse_stf_with_weights(session, stf, payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        weights = [monday_pct, tuesday_pct, wednesday_pct, thursday_pct, friday_pct, saturday_pct, sunday_pct]
        days = [
            ("Lundi", stf.week_start_date + timedelta(days=0), monday_pct),
            ("Mardi", stf.week_start_date + timedelta(days=1), tuesday_pct),
            ("Mercredi", stf.week_start_date + timedelta(days=2), wednesday_pct),
            ("Jeudi", stf.week_start_date + timedelta(days=3), thursday_pct),
            ("Vendredi", stf.week_start_date + timedelta(days=4), friday_pct),
            ("Samedi", stf.week_start_date + timedelta(days=5), saturday_pct),
            ("Dimanche", stf.week_start_date + timedelta(days=6), sunday_pct),
        ]
        return templates.TemplateResponse(
            request,
            "daily/from_stf.html",
            {
                "active_nav": "daily",
                "current_user": current_user,
                "stf": stf,
                "campaign": session.get(Campaign, stf.campaign_id),
                "skill": session.get(Skill, stf.skill_id),
                "days": days,
                "weights": weights,
                "total_weight": sum(weights),
                "daily_volumes": [stf.volume * w / 100.0 for w in weights],
                "intraday_profile_pct": intraday_profile_pct,
                "intraday_slots": intraday_slots,
                "errors": errors,
            },
            status_code=400,
        )

    return RedirectResponse(
        url=f"/daily?campaign_id={stf.campaign_id}&skill_id={stf.skill_id}&generated=1",
        status_code=303,
    )

@router.get("/view")
def view_day(
    request: Request,
    target_date: DateType,
    campaign_id: int,
    skill_id: int,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    raw_intervals = intraday_service.list_intervals_for_day(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    if not raw_intervals:
        raise HTTPException(status_code=404, detail="Aucun intervalle pour cette date/campagne/skill.")

    client_plan = client_stf_service.current_plan(
        session,
        target_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    client_rows = (
        client_stf_service.list_intervals(session, client_plan.id)
        if client_plan is not None
        else []
    )
    intervals = (
        client_stf_service.effective_intervals(raw_intervals, client_rows)
        if client_rows
        else raw_intervals
    )

    campaign = session.get(Campaign, campaign_id)
    skill = session.get(Skill, skill_id)
    summary = intraday_service.compute_daily_summary(intervals)
    channel_name = channel_service.channel_label(skill.channel) if skill else "Phone"
    channel_concurrency = channel_service.concurrency_for_channel(skill.channel) if skill else 1.0

    return templates.TemplateResponse(
        request,
        "daily/view.html",
        {
            "active_nav": "daily",
            "current_user": current_user,
            "target_date": target_date,
            "campaign": campaign,
            "skill": skill,
            "intervals": intervals,
            "summary": summary,
            "channel_name": channel_name,
            "channel_concurrency": channel_concurrency,
            "client_stf_active": bool(client_rows),
            "can_update": current_user.role in UPDATE_ROLES,
        },
    )


@router.get("/interval/{interval_id}/edit")
def edit_interval_form(
    interval_id: int,
    request: Request,
    current_user: User = Depends(require_role(*UPDATE_ROLES)),
    session: Session = Depends(get_session),
):
    interval = session.get(IntervalForecast, interval_id)
    if interval is None:
        raise HTTPException(status_code=404, detail="Intervalle introuvable.")

    return templates.TemplateResponse(
        request,
        "daily/interval_edit.html",
        {
            "active_nav": "daily",
            "current_user": current_user,
            "interval": interval,
            "errors": [],
        },
    )


@router.post("/interval/{interval_id}/edit", dependencies=[Depends(verify_csrf)])
def edit_interval_submit(
    interval_id: int,
    request: Request,
    scheduled_hc: Optional[float] = Form(None),
    actual_volume: Optional[float] = Form(None),
    actual_aht_seconds: Optional[float] = Form(None),
    actual_talk_time_seconds: Optional[float] = Form(None),
    actual_hold_time_seconds: Optional[float] = Form(None),
    actual_acw_seconds: Optional[float] = Form(None),
    actual_hc: Optional[float] = Form(None),
    abandoned_contacts: Optional[float] = Form(None),
    current_user: User = Depends(require_role(*UPDATE_ROLES)),
    session: Session = Depends(get_session),
):
    interval = session.get(IntervalForecast, interval_id)
    if interval is None:
        raise HTTPException(status_code=404, detail="Intervalle introuvable.")

    try:
        payload = IntervalUpdateInput(
            scheduled_hc=scheduled_hc,
            actual_volume=actual_volume,
            actual_aht_seconds=actual_aht_seconds,
            actual_talk_time_seconds=actual_talk_time_seconds,
            actual_hold_time_seconds=actual_hold_time_seconds,
            actual_acw_seconds=actual_acw_seconds,
            actual_hc=actual_hc,
            abandoned_contacts=abandoned_contacts,
        )
        intraday_service.update_interval(session, interval_id=interval_id, data=payload)
    except (ValidationError, ValueError) as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        return templates.TemplateResponse(
            request,
            "daily/interval_edit.html",
            {
                "active_nav": "daily",
                "current_user": current_user,
                "interval": interval,
                "errors": errors,
            },
            status_code=400,
        )

    return RedirectResponse(
        url=f"/daily/view?target_date={interval.date}&campaign_id={interval.campaign_id}&skill_id={interval.skill_id}",
        status_code=303,
    )
