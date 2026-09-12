"""Point d'entrée de l'application WFM Planning & Scheduling.

Commit 06 - Add LTF monthly : premier module métier avec une UI complète
(liste filtrable, création, détail). Les routers suivants (stf, daily,
capacity, scheduling, kpi, shrinkage, overtime, reports, settings, dashboard)
seront ajoutés progressivement.
"""

import os
from contextlib import asynccontextmanager

import qrcode
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import engine
from app.core.middleware import CSRFCookieMiddleware
from app.core.security import (
    NotAuthenticatedError,
    generate_totp_secret,
    hash_password,
    require_login,
    require_role,
    totp_provisioning_uri,
)
from app.models.enums import UserRole
from app.models.user import User
from app.routers import auth, daily, ltf, stf

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

        totp_secret = generate_totp_secret()
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
            totp_secret=totp_secret,
        )
        session.add(user)
        session.commit()

    uri = totp_provisioning_uri(totp_secret, email)
    print("=" * 70)
    print(f"[bootstrap] Compte admin créé : {email}")
    print("[bootstrap] Configuration TOTP (à faire immédiatement) :")
    print(f"[bootstrap] Clé manuelle : {totp_secret}")
    print(f"[bootstrap] URI complète : {uri}")
    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make()
    qr.print_ascii()
    print("=" * 70)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_admin_if_configured()
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
app.include_router(ltf.router)
app.include_router(stf.router)
app.include_router(daily.router)


@app.exception_handler(NotAuthenticatedError)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedError):
    """Toute route protégée non authentifiée redirige proprement vers /login
    plutôt que de renvoyer un 401 brut (cohérent avec une appli server-rendered)."""
    return RedirectResponse(url="/login", status_code=303)


@app.get("/health", tags=["system"])
def health_check() -> dict:
    """Endpoint de vérification de santé, utilisé par le health check Render."""
    return {"status": "ok", "service": "wfm-planning-scheduling", "env": settings.env}


@app.get("/", tags=["system"])
def root(current_user: User = Depends(require_login)):
    """Racine temporaire — redirige vers LTF Monthly, seul module de contenu
    existant jusqu'ici. Sera remplacée par le vrai dashboard (commit 13)."""
    return RedirectResponse(url="/ltf", status_code=303)


@app.get("/me", tags=["system"])
def me(current_user: User = Depends(require_login)) -> dict:
    """Vérifie l'authentification courante — utile en attendant une vraie page profil."""
    return {"id": current_user.id, "email": current_user.email, "role": current_user.role.value}


@app.get("/admin/ping", tags=["system"])
def admin_ping(current_user: User = Depends(require_role(UserRole.ADMIN))) -> dict:
    """Endpoint de démonstration RBAC : réservé au rôle admin."""
    return {"message": f"Bonjour {current_user.email}, accès admin confirmé."}

