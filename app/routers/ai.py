"""WFM Copilot : reporting, planning et scheduling assistés par IA."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select
from starlette.responses import RedirectResponse

from app.core.database import get_session
from app.core.security import require_login
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.skill import Skill
from app.models.user import User
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("")
def ai_page(
    request: Request,
    target_date: Optional[date] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns = list(
        session.exec(
            select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)  # noqa: E712
        ).all()
    )
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())
    if skill_id not in {skill.id for skill in skills}:
        skill_id = skills[0].id if skills else None

    return templates.TemplateResponse(
        request,
        "ai/index.html",
        {
            "active_nav": "ai",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {
                "target_date": target_date or date.today(),
                "campaign_id": campaign_id,
                "skill_id": skill_id,
            },
            "mode": "report",
            "engine": "free",
            "user_request": "",
            "answer": None,
            "snapshot": None,
            "error": None,
            "ai_status": ai_service.ai_status(),
        },
    )


@router.post("/ask")
def ask_ai(
    request: Request,
    mode: str = Form("report"),
    engine: str = Form("free"),
    target_date: date = Form(...),
    campaign_id: Optional[int] = Form(None),
    skill_id: Optional[int] = Form(None),
    user_request: str = Form(""),
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    allowed_modes = {"copilot", "report", "planning", "scheduling"}
    allowed_engines = {"free", "ai"}
    if mode not in allowed_modes:
        mode = "report"
    if engine not in allowed_engines:
        engine = "free"
    if engine == "ai" and not ai_service.ai_enabled():
        engine = "free"

    campaigns = list(
        session.exec(
            select(Campaign).where(Campaign.is_active == True).order_by(Campaign.name)  # noqa: E712
        ).all()
    )
    skills_query = select(Skill).where(Skill.is_active == True)
    if campaign_id is not None:
        skills_query = skills_query.where(Skill.campaign_id == campaign_id)
    skills = list(session.exec(skills_query.order_by(Skill.name)).all())

    answer = None
    snapshot = None
    error = None
    if skill_id is not None and skill_id not in {skill.id for skill in skills}:
        error = "Le skill sélectionné ne correspond pas à la campagne."
    else:
        try:
            snapshot = ai_service.build_wfm_snapshot(
                session,
                target_date=target_date,
                campaign_id=campaign_id,
                skill_id=skill_id,
                days=7,
            )
            if engine == "free":
                answer = ai_service.build_free_analysis(
                    mode=mode,
                    user_request=user_request,
                    snapshot=snapshot,
                )
            else:
                system_prompt, user_prompt = ai_service.build_ai_instruction(
                    mode,
                    user_request,
                    snapshot,
                )
                answer = ai_service.ask_ai(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
        except ai_service.AIError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"Analyse IA impossible : {exc}"

    return templates.TemplateResponse(
        request,
        "ai/index.html",
        {
            "active_nav": "ai",
            "current_user": current_user,
            "campaigns": campaigns,
            "skills": skills,
            "filters": {
                "target_date": target_date,
                "campaign_id": campaign_id,
                "skill_id": skill_id,
            },
            "mode": mode,
            "engine": engine,
            "user_request": user_request,
            "answer": answer,
            "snapshot": snapshot,
            "error": error,
            "ai_status": ai_service.ai_status(),
        },
    )
