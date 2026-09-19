"""STF client déjà intervalisé."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.client_stf import ClientSTFPlan
from app.models.skill import Skill
from app.models.enums import UserRole
from app.models.intraday import IntervalForecast
from app.models.user import User
from app.services import client_stf_service, intraday_service

router = APIRouter(prefix="/stf-client", tags=["stf-client"])

WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


def _reference_data(session: Session) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(
        session.exec(select(Campaign).where(Campaign.is_active == True)).all()  # noqa: E712
    )
    skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())
    return campaigns, skills


def _week_start_from_input(value: str) -> date:
    if "-W" not in value:
        raise ValueError("Semaine invalide. Utilisez le format YYYY-Www.")
    year, week = value.split("-W", 1)
    return date.fromisocalendar(int(year), int(week), 1)


@router.get("")
def client_stf_page(
    request: Request,
    plan_id: int | None = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns, skills = _reference_data(session)
    plans = list(
        session.exec(
            select(ClientSTFPlan)
            .where(ClientSTFPlan.is_current == True)  # noqa: E712
            .order_by(ClientSTFPlan.week_start_date.desc())
        ).all()
    )

    selected_plan = session.get(ClientSTFPlan, plan_id) if plan_id else (plans[0] if plans else None)
    rows = []
    scorecard = None
    interval_count = 0

    if selected_plan:
        stf_rows = client_stf_service.list_intervals(session, selected_plan.id)
        interval_count = len(stf_rows)
        forecast_intervals: list[IntervalForecast] = []
        by_day = sorted({row.date for row in stf_rows})
        for day in by_day:
            forecast_intervals.extend(
                intraday_service.list_intervals_for_day(
                    session,
                    target_date=day,
                    campaign_id=selected_plan.campaign_id,
                    skill_id=selected_plan.skill_id,
                )
            )
        scorecard = client_stf_service.scorecard(
            forecast_intervals,
            client_rows=stf_rows,
        )
        rows = [
            {
                "date": row.date,
                "start": row.interval_start,
                "end": row.interval_end,
                "volume": row.volume,
                "aht_seconds": row.aht_seconds,
                "occupancy_pct": row.occupancy_pct,
                "required_hc": row.required_hc,
            }
            for row in stf_rows
        ]

    campaign_by_id = {item.id: item for item in campaigns}
    skill_by_id = {item.id: item for item in skills}
    plan_rows = [
        {
            "plan": plan,
            "campaign_name": campaign_by_id.get(plan.campaign_id).name if plan.campaign_id in campaign_by_id else "?",
            "skill_name": skill_by_id.get(plan.skill_id).name if plan.skill_id in skill_by_id else "?",
        }
        for plan in plans
    ]

    return templates.TemplateResponse(
        request,
        "stf/client.html",
        {
            "active_nav": "stf-client",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "plans": plan_rows,
            "selected_plan": selected_plan,
            "rows": rows,
            "scorecard": scorecard,
            "interval_count": interval_count,
            "errors": [],
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.post("/import", dependencies=[Depends(verify_csrf)])
def import_client_stf(
    request: Request,
    period: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    label: str = Form("STF client"),
    notes: str = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    errors: list[str] = []
    try:
        week_start = _week_start_from_input(period)
        raw = file.file.read()
        if (file.filename or "").lower().endswith(".xlsx"):
            rows = client_stf_service.parse_xlsx(raw)
        else:
            content = raw.decode("utf-8-sig")
            rows = client_stf_service.parse_csv(content)
        plan = client_stf_service.create_plan(
            session,
            week_start_date=week_start,
            campaign_id=campaign_id,
            skill_id=skill_id,
            rows=rows,
            label=label or "STF client",
            notes=notes or None,
            created_by_user_id=current_user.id,
        )
        return RedirectResponse(url=f"/stf-client?plan_id={plan.id}", status_code=303)
    except (UnicodeDecodeError, ValueError) as exc:
        errors.append(str(exc))

    campaigns, skills = _reference_data(session)
    plans = list(
        session.exec(
            select(ClientSTFPlan)
            .where(ClientSTFPlan.is_current == True)  # noqa: E712
            .order_by(ClientSTFPlan.week_start_date.desc())
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "stf/client.html",
        {
            "active_nav": "stf-client",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "plans": [{"plan": p, "campaign_name": "?", "skill_name": "?"} for p in plans],
            "selected_plan": None,
            "rows": [],
            "scorecard": None,
            "interval_count": 0,
            "errors": errors,
            "can_edit": True,
        },
        status_code=400,
    )
