"""Point d'entrée de l'application WFM Planning & Scheduling.

Commit 06 - Add LTF monthly : premier module métier avec une UI complète
(liste filtrable, création, détail). Les routers suivants (stf, daily,
capacity, scheduling, kpi, shrinkage, overtime, reports, settings, dashboard)
seront ajoutés progressivement.
"""

import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import engine
from app.core.middleware import CSRFCookieMiddleware
from app.core.templating import templates
from app.core.security import (
    NotAuthenticatedError,
    hash_password,
    require_login,
    require_role,
)
from app.models.campaign import Campaign
from app.models.market import Market
from app.models.employee import Employee, EmployeeSkill
from app.models.enums import Channel, EmployeeStatus, ShrinkageType, UserRole
from app.models.shrinkage import ShrinkageCategory
from app.models.skill import Skill
from app.models.user import User
from app.routers import agent_portal, ai, auth, capacity, campaign_workforce, client_stf, compliance, control_tower, daily, dashboard, forecast_lab, guide, imports, ltf, markets, overtime, recruitment, schedule_board, scheduling, settings as settings_router, stf, shrinkage

settings = get_settings()


def bootstrap_admin_if_configured(*, db_engine=None) -> None:
    """Crée un compte admin au démarrage si BOOTSTRAP_ADMIN_EMAIL et
    BOOTSTRAP_ADMIN_PASSWORD sont définis en variables d'environnement et
    qu'aucun utilisateur n'existe encore avec cet email.

    Pensé pour un déploiement Render sans accès shell (plan free) : les
    identifiants TOTP s'affichent dans les logs applicatifs (Render
    Dashboard > Logs), consultables sans terminal. Idempotent — ne recrée
    ni ne réinitialise rien si le compte existe déjà, donc sans danger de
    laisser les variables en place après le premier démarrage (on peut
    aussi les retirer une fois le compte créé, par hygiène).
    """
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL")
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if not email or not password:
        return

    db_engine = db_engine or engine

    with Session(db_engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing is not None:
            return

        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
            totp_secret=None,
        )
        session.add(user)
        session.commit()

    print("=" * 70)
    print(f"[bootstrap] Compte admin créé : {email}")
    print("[bootstrap] Le 2FA sera configuré par l'utilisateur lors de sa première connexion.")
    print("=" * 70)


def bootstrap_reset_admin_security_if_configured(*, db_engine=None) -> None:
    """Efface les deux mots-clés admin et génère un nouveau secret TOTP.

    Utilisé uniquement pour une récupération d'accès déclenchée explicitement
    par la variable RESET_ADMIN_SECURITY_EMAIL. Tant que cette variable reste
    définie, chaque démarrage réinitialise à nouveau les mots-clés : retirez-la
    immédiatement après avoir créé les deux nouveaux mots-clés.
    """
    email = os.environ.get("RESET_ADMIN_SECURITY_EMAIL", "").strip().lower()
    if not email:
        return

    db_engine = db_engine or engine

    from app.core.security import generate_totp_secret

    with Session(db_engine) as session:
        user = session.exec(
            select(User).where(User.email == email, User.role == UserRole.ADMIN)
        ).first()
        if user is None:
            print(
                f"[bootstrap] RESET_ADMIN_SECURITY_EMAIL={email} : "
                "aucun compte admin trouvé, rien à faire."
            )
            return

        user.admin_keyword1_hash = None
        user.admin_keyword2_hash = None
        user.totp_secret = generate_totp_secret()
        user.email_otp_hash = None
        user.email_otp_expires_at = None
        user.email_otp_requested_at = None
        user.email_otp_attempts = 0
        session.add(user)
        session.commit()
        session.refresh(user)

        totp_secret = user.totp_secret

    print("=" * 70)
    print(f"[bootstrap] Sécurité admin réinitialisée pour : {email}")
    print(f"[bootstrap] Nouveau secret TOTP : {totp_secret}")
    print("[bootstrap] Pendant cette récupération, connectez-vous puis créez")
    print("[bootstrap] deux nouveaux mots-clés admin avec le code TOTP.")
    print("[bootstrap] RETIREZ RESET_ADMIN_SECURITY_EMAIL après la création.")
    print("=" * 70)


def bootstrap_reset_totp_if_configured(*, db_engine=None) -> None:
    """Régénère le secret TOTP d'un utilisateur existant au démarrage si
    RESET_TOTP_EMAIL est défini en variable d'environnement.

    Le secret TOTP n'est affiché qu'une seule fois, dans les logs au moment
    du bootstrap admin ou de create_admin.py. S'il est perdu (logs Render
    expirés, QR jamais scanné, changement de téléphone), aucun code ne peut
    plus jamais être validé pour ce compte — il n'existait jusqu'ici aucun
    moyen de le récupérer sans accès direct à la base de données.

    ATTENTION : contrairement aux autres bootstraps, celui-ci N'EST PAS
    idempotent au sens "sans danger de laisser la variable en place" — il
    régénère un nouveau secret à CHAQUE démarrage tant que RESET_TOTP_EMAIL
    reste défini. Retirez la variable dès que le nouveau secret a été
    capturé dans les logs, avant le prochain redéploiement/redémarrage.
    """
    email = os.environ.get("RESET_TOTP_EMAIL")
    if not email:
        return

    db_engine = db_engine or engine

    with Session(db_engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            print(f"[bootstrap] RESET_TOTP_EMAIL={email} : aucun utilisateur trouvé, rien à faire.")
            return

        user.totp_secret = None
        session.add(user)
        session.commit()

    print("=" * 70)
    print(f"[bootstrap] 2FA réinitialisé pour : {email}")
    print("[bootstrap] Le nouvel enrôlement sera effectué par l'utilisateur lors de sa prochaine connexion.")
    print("[bootstrap] Retirez RESET_TOTP_EMAIL des variables d'environnement Render.")
    print("=" * 70)


def bootstrap_demo_data_if_configured(*, db_engine=None) -> None:
    """Crée une campagne + skill + quelques employés de démonstration au
    démarrage si BOOTSTRAP_DEMO_DATA=true est défini ET qu'aucune campagne
    n'existe encore en base.

    Même logique que bootstrap_admin_if_configured : pensé pour un
    déploiement Render sans accès shell, où `python -m
    app.scripts.seed_demo_data` n'est pas exécutable directement.
    Idempotent — ne recrée rien si une campagne existe déjà (y compris une
    créée manuellement depuis l'app une fois le module Settings disponible).
    """
    if os.environ.get("BOOTSTRAP_DEMO_DATA", "").lower() not in ("1", "true", "yes"):
        return

    db_engine = db_engine or engine

    with Session(db_engine) as session:
        existing = session.exec(select(Campaign)).first()
        if existing is not None:
            return

        campaign = Campaign(name="Support Client FR", code="SUP-FR")
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        france = session.exec(select(Market).where(Market.code == "FR")).first()
        skill = Skill(
            campaign_id=campaign.id,
            market_id=france.id if france is not None else None,
            name="Voix Niveau 1",
            channel=Channel.VOICE,
        )
        session.add(skill)
        session.commit()
        session.refresh(skill)

        demo_employees = [
            ("EMP001", "Alice", "Randrianasolo"),
            ("EMP002", "Bao", "Rakoto"),
            ("EMP003", "Chris", "Andria"),
        ]
        for code, first_name, last_name in demo_employees:
            employee = Employee(
                employee_code=code,
                first_name=first_name,
                last_name=last_name,
                campaign_id=campaign.id,
                hire_date=date(2025, 1, 1),
                status=EmployeeStatus.ACTIVE,
            )
            session.add(employee)
            session.commit()
            session.refresh(employee)
            session.add(EmployeeSkill(employee_id=employee.id, skill_id=skill.id, is_primary=True))
        session.commit()

        campaign_name, campaign_code = campaign.name, campaign.code
        skill_name, skill_channel = skill.name, skill.channel.value

    print("=" * 70)
    print(f"[bootstrap] Campagne de démo créée : {campaign_name} (code={campaign_code})")
    print(f"[bootstrap] Skill de démo créée : {skill_name} ({skill_channel})")
    print(f"[bootstrap] {len(demo_employees)} employés de démo créés et rattachés au skill")
    print("=" * 70)


def bootstrap_markets(*, db_engine=None) -> None:
    """Crée les marchés standards utilisés par le centre de contacts."""
    db_engine = db_engine or engine
    defaults = [
        ("FR", "France", "fr", "Europe/Paris"),
        ("UK", "United Kingdom", "en", "Europe/London"),
        ("DE", "Germany", "de", "Europe/Berlin"),
        ("IN", "India", "en", "Asia/Kolkata"),
        ("ES", "Spain", "es", "Europe/Madrid"),
        ("JP", "Japan", "ja", "Asia/Tokyo"),
        ("NL", "Netherlands", "nl", "Europe/Amsterdam"),
    ]
    with Session(db_engine) as session:
        existing = {item.code for item in session.exec(select(Market)).all()}
        created = 0
        for code, name, language_code, timezone_name in defaults:
            if code in existing:
                continue
            session.add(
                Market(
                    code=code,
                    name=name,
                    language_code=language_code,
                    timezone_name=timezone_name,
                    is_active=True,
                )
            )
            created += 1
        if created:
            session.commit()


def bootstrap_operational_configuration(*, db_engine=None) -> None:
    """Crée la configuration WFM standard manquante sans écraser l'existant.

    Idempotent : ajoute uniquement les campagnes/skills standards absents.
    """
    db_engine = db_engine or engine
    standard_markets = ["FR", "UK", "DE", "IN", "ES", "JP", "NL"]
    standard_channels = (
        (Channel.VOICE, "Phone"),
        (Channel.EMAIL, "Email"),
        (Channel.CHAT, "Message Us"),
        (Channel.BACKOFFICE, "Backoffice"),
    )

    with Session(db_engine) as session:
        markets_by_code = {
            market.code: market
            for market in session.exec(
                select(Market).where(
                    Market.code.in_(standard_markets),
                    Market.is_active == True,  # noqa: E712
                )
            ).all()
        }
        created_campaigns = 0
        created_skills = 0

        for market_code in standard_markets:
            market = markets_by_code.get(market_code)
            if market is None:
                continue

            campaign_code = f"SUP-{market_code}"
            campaign = session.exec(
                select(Campaign).where(Campaign.code == campaign_code)
            ).first()
            if campaign is None:
                campaign = Campaign(
                    name=f"Support Client {market_code}",
                    code=campaign_code,
                    description=f"Campagne WFM standard — marché {market_code}.",
                    is_active=True,
                )
                session.add(campaign)
                session.commit()
                session.refresh(campaign)
                created_campaigns += 1

            for channel, skill_name in standard_channels:
                exists = session.exec(
                    select(Skill).where(
                        Skill.campaign_id == campaign.id,
                        Skill.channel == channel,
                        Skill.is_active == True,  # noqa: E712
                    )
                ).first()
                if exists is not None:
                    continue

                session.add(
                    Skill(
                        campaign_id=campaign.id,
                        market_id=market.id,
                        name=skill_name,
                        channel=channel,
                        is_active=True,
                    )
                )
                created_skills += 1

        if created_skills:
            session.commit()

    if created_campaigns or created_skills:
        print(
            f"[bootstrap] Configuration WFM ajoutée : "
            f"{created_campaigns} campagnes, {created_skills} skills."
        )


def bootstrap_shrinkage_categories(*, db_engine=None) -> None:
    """Crée les catégories Shrinkage par défaut (§23) si aucune n'existe
    encore — Indoor (Break, Meeting, Personal Time, Outage, Project,
    Training) et Outdoor (Leave, Absenteeism).

    Contrairement au bootstrap admin/démo, ceci s'exécute TOUJOURS (pas de
    variable d'environnement) : ce sont des catégories de référence
    standard qu'un déploiement réel voudrait dès le départ, pas des
    données de démonstration à activer explicitement. L'administrateur
    pourra les modifier plus tard depuis une page Settings dédiée (pas
    encore construite) — ce bootstrap ne fait que poser un point de
    départ raisonnable, idempotent.
    """
    db_engine = db_engine or engine

    with Session(db_engine) as session:
        existing = session.exec(select(ShrinkageCategory)).first()
        if existing is not None:
            return

        default_categories = [
            ("Break", ShrinkageType.INDOOR, "BREAK"),
            ("Meeting", ShrinkageType.INDOOR, "MEETING"),
            ("Personal Time", ShrinkageType.INDOOR, "PERSONAL"),
            ("Outage", ShrinkageType.INDOOR, "OUTAGE"),
            ("Project", ShrinkageType.INDOOR, "PROJECT"),
            ("Training", ShrinkageType.INDOOR, "TRAINING"),
            ("Leave", ShrinkageType.OUTDOOR, "LEAVE"),
            ("Absenteeism", ShrinkageType.OUTDOOR, "ABSENTEEISM"),
        ]
        for name, shrinkage_type, code in default_categories:
            session.add(ShrinkageCategory(name=name, type=shrinkage_type, code=code))
        session.commit()

    print(f"[bootstrap] {len(default_categories)} catégories Shrinkage par défaut créées.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_admin_if_configured()
    bootstrap_reset_totp_if_configured()
    bootstrap_reset_admin_security_if_configured()
    bootstrap_demo_data_if_configured()
    bootstrap_markets()
    bootstrap_operational_configuration()
    bootstrap_shrinkage_categories()
    yield


app = FastAPI(
    title="WFM Planning & Scheduling",
    description="Plateforme de planification, capacity planning et suivi WFM pour centre de contacts.",
    version="0.1.0",
    debug=not settings.is_production,
    lifespan=lifespan,
)

app.add_middleware(CSRFCookieMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(ai.router)
app.include_router(dashboard.router)
app.include_router(ltf.router)
app.include_router(stf.router)
app.include_router(client_stf.router)
app.include_router(markets.router)
app.include_router(settings_router.router)
app.include_router(daily.router)
app.include_router(capacity.router)
app.include_router(campaign_workforce.router)
app.include_router(control_tower.router)
app.include_router(compliance.router)
app.include_router(agent_portal.router)
app.include_router(forecast_lab.router)
app.include_router(imports.router)
app.include_router(schedule_board.router)
app.include_router(guide.router)
app.include_router(shrinkage.router)
app.include_router(overtime.router)
app.include_router(recruitment.router)
app.include_router(scheduling.router)


@app.exception_handler(NotAuthenticatedError)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedError):
    """Toute route protégée non authentifiée redirige proprement vers /login
    plutôt que de renvoyer un 401 brut (cohérent avec une appli server-rendered)."""
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(Exception)
async def application_error_handler(request: Request, exc: Exception):
    """Retourne une page lisible au lieu d'un écran blanc sur erreur applicative."""
    print(f"[application-error] {request.method} {request.url.path}: {exc!r}")
    error_detail = None if settings.is_production else f"{type(exc).__name__}: {exc}"
    return templates.TemplateResponse(
        request,
        "error.html",
        {"error_detail": error_detail},
        status_code=500,
        headers={"Cache-Control": "no-store"},
    )

@app.get("/health", tags=["system"])
def health_check() -> dict:
    """Endpoint de vérification de santé, utilisé par le health check Render."""
    return {"status": "ok", "service": "wfm-planning-scheduling", "env": settings.env}


@app.get("/", tags=["system"])
def root(current_user: User = Depends(require_login)):
    """Redirige vers le Dashboard (§5), comme promis depuis le commit 06."""
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/me", tags=["system"])
def me(current_user: User = Depends(require_login)) -> dict:
    """Vérifie l'authentification courante — utile en attendant une vraie page profil."""
    return {"id": current_user.id, "email": current_user.email, "role": current_user.role.value}


@app.get("/admin/ping", tags=["system"])
def admin_ping(current_user: User = Depends(require_role(UserRole.ADMIN))) -> dict:
    """Endpoint de démonstration RBAC : réservé au rôle admin."""
    return {"message": f"Bonjour {current_user.email}, accès admin confirmé."}

