"""Configuration WFM : campagnes et skills opérationnels."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.enums import Channel, UserRole
from app.models.market import Market
from app.models.skill import Skill
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)

CHANNEL_LABELS = {
    Channel.VOICE: "Phone",
    Channel.EMAIL: "Email",
    Channel.CHAT: "Message Us",
    Channel.BACKOFFICE: "Backoffice",
}


def _page_data(session: Session):
    campaigns = list(session.exec(select(Campaign).order_by(Campaign.name)).all())
    skills = list(session.exec(select(Skill).order_by(Skill.campaign_id, Skill.name)).all())
    markets = list(session.exec(select(Market).where(Market.is_active == True).order_by(Market.code)).all())  # noqa: E712
    campaigns_by_id = {c.id: c for c in campaigns}
    markets_by_id = {m.id: m for m in markets}
    rows = [
        {
            "skill": skill,
            "campaign": campaigns_by_id.get(skill.campaign_id),
            "market": markets_by_id.get(skill.market_id) if skill.market_id is not None else None,
            "channel_label": CHANNEL_LABELS.get(skill.channel, skill.channel.value),
        }
        for skill in skills
    ]
    return campaigns, markets, rows


@router.get("")
def settings_page(
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    campaigns, markets, rows = _page_data(session)
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "active_nav": "settings",
            "current_user": current_user,
            "campaigns": campaigns,
            "markets": markets,
            "skill_rows": rows,
            "channel_labels": CHANNEL_LABELS,
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.post("/campaigns", dependencies=[Depends(verify_csrf)])
def create_campaign(
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    name = name.strip()
    code = code.strip().upper()
    if not name or not code:
        return RedirectResponse("/settings?error=Nom+et+code+obligatoires", status_code=303)
    existing = session.exec(select(Campaign).where(Campaign.code == code)).first()
    if existing is not None:
        return RedirectResponse("/settings?error=Code+campagne+déjà+utilisé", status_code=303)
    session.add(Campaign(name=name, code=code, description=description.strip() or None, is_active=True))
    session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/skills", dependencies=[Depends(verify_csrf)])
def create_skill(
    campaign_id: int = Form(...),
    name: str = Form(...),
    channel: Channel = Form(...),
    market_id: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    name = name.strip()
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        return RedirectResponse("/settings?error=Campagne+introuvable", status_code=303)
    if not name:
        return RedirectResponse("/settings?error=Nom+du+skill+obligatoire", status_code=303)
    market_id_value = int(market_id) if market_id.strip() else None
    if market_id_value is not None and session.get(Market, market_id_value) is None:
        return RedirectResponse("/settings?error=Marché+introuvable", status_code=303)
    duplicate = session.exec(
        select(Skill).where(Skill.campaign_id == campaign_id, Skill.name == name)
    ).first()
    if duplicate is not None:
        return RedirectResponse("/settings?error=Skill+déjà+présent+dans+la+campagne", status_code=303)
    session.add(
        Skill(
            campaign_id=campaign_id,
            market_id=market_id_value,
            name=name,
            channel=channel,
            is_active=True,
        )
    )
    session.commit()
    return RedirectResponse("/settings", status_code=303)

@router.post("/demo", dependencies=[Depends(verify_csrf)])
def seed_demo_configuration(
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    """Charge un jeu de données de démonstration multi-marché/multi-canal.

    Idempotent : une campagne ou un skill déjà présent est conservé.
    """
    markets = list(
        session.exec(select(Market).where(Market.is_active == True).order_by(Market.code)).all()  # noqa: E712
    )
    for market in markets:
        code = f"SUP-{market.code}"
        campaign = session.exec(select(Campaign).where(Campaign.code == code)).first()
        if campaign is None:
            campaign = Campaign(
                name=f"Support Client {market.code}",
                code=code,
                description=f"Jeu de démonstration WFM — marché {market.code}.",
                is_active=True,
            )
            session.add(campaign)
            session.commit()
            session.refresh(campaign)

        channels = (
            (Channel.VOICE, "Phone"),
            (Channel.EMAIL, "Email"),
            (Channel.CHAT, "Message Us"),
            (Channel.BACKOFFICE, "Backoffice"),
        )
        for channel, default_name in channels:
            existing = session.exec(
                select(Skill).where(
                    Skill.campaign_id == campaign.id,
                    Skill.channel == channel,
                    Skill.is_active == True,  # noqa: E712
                )
            ).first()
            if existing is not None:
                continue
            session.add(
                Skill(
                    campaign_id=campaign.id,
                    market_id=market.id,
                    name=default_name,
                    channel=channel,
                    is_active=True,
                )
            )
        session.commit()

    return RedirectResponse("/settings", status_code=303)
