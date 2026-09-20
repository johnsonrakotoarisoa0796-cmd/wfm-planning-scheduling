"""Configuration WFM : campagnes et skills opérationnels."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.models.campaign import Campaign
from app.models.campaign_workforce import CampaignWorkforcePlan
from app.models.employee import Employee
from app.models.enums import Channel, UserRole
from app.models.market import Market
from app.models.skill import Skill
from app.models.user import User
from app.models.weekly_parameters import WeeklyWFMParameter
from app.services.weekly_parameter_service import upsert_weekly_parameters
from app.services.campaign_workforce_service import calculate_metrics

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
    workforce_rows = list(
        session.exec(
            select(CampaignWorkforcePlan).order_by(
                CampaignWorkforcePlan.campaign_id,
                CampaignWorkforcePlan.period.desc(),
            )
        ).all()
    )
    workforce_by_campaign = {}
    for plan in workforce_rows:
        workforce_by_campaign.setdefault(
            plan.campaign_id,
            {"plan": plan, "metrics": calculate_metrics(plan)},
        )

    weekly_rows_raw = list(
        session.exec(
            select(WeeklyWFMParameter).order_by(
                WeeklyWFMParameter.iso_year.desc(),
                WeeklyWFMParameter.iso_week.desc(),
                WeeklyWFMParameter.campaign_id,
                WeeklyWFMParameter.skill_id,
            )
        ).all()
    )
    campaigns_by_id = {c.id: c for c in campaigns}
    skills_by_id = {row["skill"].id: row["skill"] for row in rows}
    users = list(session.exec(select(User).order_by(User.email)).all()) if current_user.role == UserRole.ADMIN else []
    employees = list(session.exec(select(Employee).order_by(Employee.last_name, Employee.first_name)).all()) if current_user.role == UserRole.ADMIN else []
    weekly_rows = [
        {
            "row": row,
            "campaign_name": campaigns_by_id.get(row.campaign_id).name if row.campaign_id in campaigns_by_id else "—",
            "skill_name": skills_by_id.get(row.skill_id).name if row.skill_id in skills_by_id else "—",
        }
        for row in weekly_rows_raw
    ]
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
            "weekly_rows": weekly_rows,
            "workforce_by_campaign": workforce_by_campaign,
            "users": users,
            "employees": employees,
        },
    )



@router.post("/weekly-parameters", dependencies=[Depends(verify_csrf)])
def save_weekly_parameters(
    period: str = Form(...),
    campaign_id: int = Form(...),
    skill_id: int = Form(...),
    aht_seconds: float = Form(...),
    occupancy_pct: float = Form(...),
    service_level_target_pct: float = Form(...),
    answer_time_target_seconds: float = Form(...),
    shrinkage_pct: float = Form(...),
    interval_minutes: int = Form(30),
    notes: str = Form(""),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        if "-W" not in period:
            raise ValueError("La semaine doit être au format YYYY-Www.")
        year_text, week_text = period.split("-W", 1)
        iso_year, iso_week = int(year_text), int(week_text)
        campaign = session.get(Campaign, campaign_id)
        skill = session.get(Skill, skill_id)
        if campaign is None or skill is None or skill.campaign_id != campaign_id:
            raise ValueError("Le skill doit appartenir à la campagne sélectionnée.")
        upsert_weekly_parameters(
            session,
            iso_year=iso_year,
            iso_week=iso_week,
            campaign_id=campaign_id,
            skill_id=skill_id,
            aht_seconds=aht_seconds,
            occupancy_pct=occupancy_pct,
            service_level_target_pct=service_level_target_pct,
            answer_time_target_seconds=answer_time_target_seconds,
            shrinkage_pct=shrinkage_pct,
            interval_minutes=interval_minutes,
            notes=notes,
        )
    except ValueError as exc:
        return RedirectResponse(f"/settings?error={str(exc).replace(' ', '+')}", status_code=303)
    return RedirectResponse("/settings", status_code=303)

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


@router.post("/user-agent-link", dependencies=[Depends(verify_csrf)])
def link_user_to_employee(
    user_id: int = Form(...),
    employee_id: str = Form(""),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    session: Session = Depends(get_session),
):
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse("/settings?error=Utilisateur+introuvable", status_code=303)
    employee_id_value = int(employee_id) if employee_id.strip() else None
    if employee_id_value is not None and session.get(Employee, employee_id_value) is None:
        return RedirectResponse("/settings?error=Agent+introuvable", status_code=303)
    user.employee_id = employee_id_value
    session.add(user)
    session.commit()
    return RedirectResponse("/settings", status_code=303)




@router.post("/admin-security", dependencies=[Depends(verify_csrf)])
def update_admin_security(
    keyword1: str = Form(...),
    keyword2: str = Form(...),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    session: Session = Depends(get_session),
):
    key1 = keyword1.strip()
    key2 = keyword2.strip()

    if len(key1) < 4 or len(key2) < 4:
        return RedirectResponse(
            "/settings?error=Les+deux+mots-clés+doivent+contenir+au+moins+4+caractères#users",
            status_code=303,
        )
    if len(key1) > 64 or len(key2) > 64:
        return RedirectResponse(
            "/settings?error=Les+deux+mots-clés+doivent+contenir+au+maximum+64+caractères#users",
            status_code=303,
        )
    if key1.casefold() == key2.casefold():
        return RedirectResponse(
            "/settings?error=Les+deux+mots-clés+doivent+être+différents#users",
            status_code=303,
        )

    from app.core.security import hash_password

    current_user.admin_keyword1_hash = hash_password(key1.casefold())
    current_user.admin_keyword2_hash = hash_password(key2.casefold())
    session.add(current_user)
    session.commit()
    return RedirectResponse("/settings?error=Mots-clés+admin+mis+à+jour#users", status_code=303)

@router.post("/users/{user_id}", dependencies=[Depends(verify_csrf)])
def manage_user(
    user_id: int,
    action: str = Form(...),
    role: str = Form("viewer"),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    session: Session = Depends(get_session),
):
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse("/settings?error=Utilisateur+introuvable", status_code=303)

    error = None

    if action == "activate":
        user.is_active = True
    elif action == "deactivate":
        if user.id == current_user.id:
            error = "Vous ne pouvez pas désactiver votre propre compte admin."
        elif user.role == UserRole.ADMIN:
            active_admins = session.exec(
                select(User).where(User.role == UserRole.ADMIN, User.is_active == True)  # noqa: E712
            ).all()
            if len(active_admins) <= 1:
                error = "Impossible de désactiver le dernier administrateur actif."
            else:
                user.is_active = False
        else:
            user.is_active = False
    elif action == "role":
        try:
            new_role = UserRole(role)
        except ValueError:
            error = "Rôle utilisateur invalide."
        else:
            if user.id == current_user.id and new_role != UserRole.ADMIN:
                error = "Vous ne pouvez pas retirer votre propre rôle admin."
            elif user.role == UserRole.ADMIN and new_role != UserRole.ADMIN:
                active_admins = session.exec(
                    select(User).where(User.role == UserRole.ADMIN, User.is_active == True)  # noqa: E712
                ).all()
                if len(active_admins) <= 1:
                    error = "Impossible de retirer le dernier administrateur actif."
                else:
                    user.role = new_role
            else:
                user.role = new_role
    elif action == "reset_2fa":
        user.totp_secret = None
    else:
        error = "Action utilisateur inconnue."

    if error:
        return RedirectResponse(f"/settings?error={error.replace(' ', '+')}", status_code=303)

    session.add(user)
    session.commit()
    return RedirectResponse("/settings", status_code=303)
