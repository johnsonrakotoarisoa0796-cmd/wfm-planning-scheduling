"""Board hebdomadaire type Teleopti : lecture consolidée du planning."""
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
from app.services.wfm_control_tower_service import build_week_board

router = APIRouter(prefix="/schedule-board", tags=["schedule-board"])


@router.get("")
def schedule_board(
    request: Request,
    week: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True).order_by(Skill.name)).all())
    today = date.today()
    if week:
        try:
            year_text, week_text = week.split("-W", 1)
            week_start = date.fromisocalendar(int(year_text), int(week_text), 1)
        except (ValueError, TypeError):
            week_start = today - __import__("datetime").timedelta(days=today.weekday())
    else:
        week_start = today - __import__("datetime").timedelta(days=today.weekday())
    week_days = [week_start + timedelta(days=i) for i in range(5)]
    rows = []
    if campaign_id is not None and skill_id is not None:
        rows = build_week_board(session, week_start=week_start, campaign_id=campaign_id, skill_id=skill_id)
    return templates.TemplateResponse(
        request,
        "schedule_board/index.html",
        {
            "active_nav": "schedule-board",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"week": f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}", "campaign_id": campaign_id, "skill_id": skill_id},
            "rows": rows,
            "week_start": week_start,
            "week_days": week_days,
        },
    )
