"""WFM Control Tower : pilotage intraday, capacity et simulation."""
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
from app.services.wfm_control_tower_service import build_control_tower

router = APIRouter(prefix="/control-tower", tags=["control-tower"])


@router.get("")
def control_tower(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills = list(session.exec(select(Skill).where(Skill.is_active == True).order_by(Skill.name)).all())
    target_date = target_date or date.today()
    data = None
    if campaign_id is not None and skill_id is not None:
        data = build_control_tower(
            session,
            target_date=target_date,
            campaign_id=campaign_id,
            skill_id=skill_id,
        )
    return templates.TemplateResponse(
        request,
        "control_tower/index.html",
        {
            "active_nav": "control-tower",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"target_date": target_date, "campaign_id": campaign_id, "skill_id": skill_id},
            "data": data,
        },
    )
