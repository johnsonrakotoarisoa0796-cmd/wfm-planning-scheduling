"""Forecast Lab : accuracy, bias et reforecast run-rate."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.skill import Skill
from app.models.user import User
from app.services import forecast_lab_service

router = APIRouter(prefix="/forecast-lab", tags=["forecast-lab"])


@router.get("")
def forecast_lab(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=30))
    target = target_date or date.today()

    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())

    metrics = None
    reforecast = None
    rows = []
    if campaign_id is not None and skill_id in {s.id for s in skills}:
        intervals = forecast_lab_service.list_intervals(
            session, start_date=start, end_date=end, campaign_id=campaign_id, skill_id=skill_id
        )
        metrics = forecast_lab_service.compute_metrics(intervals)
        reforecast = forecast_lab_service.suggest_reforecast(
            session, target_date=target, campaign_id=campaign_id, skill_id=skill_id
        )
        daily = {}
        for row in intervals:
            item = daily.setdefault(row.date, {"forecast": 0.0, "actual": 0.0, "has_actual": False})
            item["forecast"] += row.forecast_volume
            if row.actual_volume is not None:
                item["actual"] += row.actual_volume
                item["has_actual"] = True
        rows = [
            {"date": key, **value}
            for key, value in sorted(daily.items(), reverse=True)
        ]

    return templates.TemplateResponse(
        request,
        "forecast_lab/index.html",
        {
            "active_nav": "forecast-lab",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {
                "start_date": start,
                "end_date": end,
                "target_date": target,
                "campaign_id": campaign_id,
                "skill_id": skill_id,
            },
            "metrics": metrics,
            "reforecast": reforecast,
            "rows": rows,
        },
    )
