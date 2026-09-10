"""Point d'entrée de l'application WFM Planning & Scheduling.

Commit 03 - Add authentication : sessions cookie signées, hashing bcrypt,
TOTP (2FA) obligatoire, RBAC, CSRF. Les routers métier (dashboard, ltf, stf,
daily, capacity, scheduling, kpi, shrinkage, overtime, reports, settings)
seront ajoutés progressivement à partir du commit 06.
"""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.security import NotAuthenticatedError, require_login, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.routers import auth

settings = get_settings()

app = FastAPI(
    title="WFM Planning & Scheduling",
    description="Plateforme de planification, capacity planning et suivi WFM pour centre de contacts.",
    version="0.1.0",
    debug=not settings.is_production,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)


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
def root(current_user: User = Depends(require_login)) -> dict:
    """Racine temporaire — sera remplacée par le dashboard (commit 13)."""
    return {"message": f"Connecte en tant que {current_user.email} ({current_user.role.value}).", "docs": "/docs"}


@app.get("/me", tags=["system"])
def me(current_user: User = Depends(require_login)) -> dict:
    """Vérifie l'authentification courante — utile en attendant une vraie page profil."""
    return {"id": current_user.id, "email": current_user.email, "role": current_user.role.value}


@app.get("/admin/ping", tags=["system"])
def admin_ping(current_user: User = Depends(require_role(UserRole.ADMIN))) -> dict:
    """Endpoint de démonstration RBAC : réservé au rôle admin."""
    return {"message": f"Bonjour {current_user.email}, accès admin confirmé."}

