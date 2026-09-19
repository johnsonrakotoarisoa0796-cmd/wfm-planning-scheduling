"""Dashboard (§5) — vue consolidée pour une date/campagne/skill, assemblée
depuis les modules déjà construits. Lecture seule, ouverte à tout
utilisateur connecté."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.skill import Skill
from app.models.user import User
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _reference_data(session: Session, campaign_id: Optional[int] = None) -> tuple[list[Campaign], list[Skill]]:
    campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)).all())  # noqa: E712
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())
    return campaigns, skills


@router.get("")
def view_dashboard(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    target_date = target_date or date.today()
    campaigns, skills = _reference_data(session, campaign_id)

    # Défaut : première campagne/skill disponible, pour ne jamais afficher
    # un tableau vide sans raison si des données existent déjà.
    if campaign_id is None and campaigns:
        campaign_id = campaigns[0].id
        campaigns, skills = _reference_data(session, campaign_id)
    elif campaign_id is not None:
        campaigns, skills = _reference_data(session, campaign_id)

    valid_skill_ids = {s.id for s in skills}
    if skill_id not in valid_skill_ids:
        skill_id = skills[0].id if skills else None

    data = None
    if campaign_id is not None and skill_id is not None:
        data = dashboard_service.build_dashboard(session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id)

    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "active_nav": "dashboard",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {"target_date": target_date, "campaign_id": campaign_id, "skill_id": skill_id},
            "data": data,
        },
    )
