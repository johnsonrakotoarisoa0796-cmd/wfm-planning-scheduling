"""Sécurité applicative : hashing, sessions cookie, RBAC, TOTP (2FA), CSRF.

Toute la logique d'authentification et d'autorisation vit ici — les routers
ne font qu'appeler ces fonctions/dépendances, jamais de logique de sécurité
inline dans les routes (même principe de séparation que services/ pour le
métier WFM).

Sessions : jetons signés (itsdangerous), pas de table "sessions" en base —
la révocation immédiate n'est pas supportée en V1 (acceptable pour une
équipe WFM interne de taille réduite ; documenté ici pour une V2).
"""

from __future__ import annotations

import secrets
from typing import Optional

import pyotp
from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.models.enums import UserRole
from app.models.user import User

settings = get_settings()

SESSION_COOKIE_NAME = "session"
PENDING_2FA_COOKIE_NAME = "pending_2fa"
CSRF_COOKIE_NAME = "csrf_token"


class NotAuthenticatedError(Exception):
    """Levée par require_login ; un exception handler la transforme en
    redirection HTTP vers /login (voir app/main.py)."""


# --- Hashing des mots de passe --------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash un mot de passe en clair avec bcrypt."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe en clair contre son hash bcrypt."""
    return _pwd_context.verify(plain_password, hashed_password)


# --- Sessions (jeton signé, sans stockage serveur) ------------------------

_session_serializer = URLSafeTimedSerializer(settings.secret_key, salt="wfm-session")
_pending_serializer = URLSafeTimedSerializer(settings.secret_key, salt="wfm-pending-2fa")


def create_session_token(user_id: int) -> str:
    """Crée un jeton de session signé contenant l'id utilisateur."""
    return _session_serializer.dumps({"user_id": user_id})


def read_session_token(token: str) -> Optional[int]:
    """Décode un jeton de session ; retourne l'user_id, ou None si invalide/expiré."""
    try:
        data = _session_serializer.loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def create_pending_2fa_token(user_id: int) -> str:
    """Jeton temporaire (5 min) pour l'étape intermédiaire entre mot de passe et code TOTP."""
    return _pending_serializer.dumps({"user_id": user_id})


def read_pending_2fa_token(token: str) -> Optional[int]:
    try:
        data = _pending_serializer.loads(token, max_age=settings.pending_2fa_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


# --- TOTP (2FA), obligatoire dès la V1 ------------------------------------

def generate_totp_secret() -> str:
    """Génère un nouveau secret TOTP (base32), à stocker dans User.totp_secret."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    """URI otpauth:// à encoder en QR pour Google Authenticator / Authy / etc."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="WFM Planning & Scheduling")


def verify_totp_code(secret: str, code: str) -> bool:
    """Vérifie un code TOTP à 6 chiffres (tolérance ±1 fenêtre de 30s)."""
    if not code or not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


# --- CSRF (double-submit cookie, sans stockage serveur) -------------------

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def verify_csrf(request: Request) -> None:
    """Dependency à ajouter sur toute route POST qui traite un formulaire HTML.

    Compare le cookie csrf_token à la valeur soumise dans le champ caché du
    formulaire (pattern double-submit). Le cookie lui-même est posé par
    CSRFCookieMiddleware (app/core/middleware.py) sur toute requête, jamais
    par cette fonction.
    """
    form = await request.form()
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    form_value = form.get("csrf_token")
    if not cookie_value or not form_value or cookie_value != form_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSRF token invalide.")


# --- Dépendances d'authentification / RBAC --------------------------------

def get_current_user(
    session: Session = Depends(get_session),
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Optional[User]:
    """Retourne l'utilisateur courant si la session est valide, sinon None.

    Dependency "douce" : ne lève jamais d'exception, à utiliser quand une
    page doit s'afficher différemment selon l'état de connexion sans forcer
    de redirection (ex: navbar).
    """
    if not session_token:
        return None
    user_id = read_session_token(session_token)
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def require_login(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """Exige une session valide ; sinon lève NotAuthenticatedError (-> redirect /login)."""
    if current_user is None:
        raise NotAuthenticatedError()
    return current_user


def require_role(*allowed_roles: UserRole):
    """Factory de dépendance RBAC : n'autorise que les rôles listés.

    Usage : `current_user: User = Depends(require_role(UserRole.ADMIN))`
    """

    def _dependency(current_user: User = Depends(require_login)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé pour votre rôle.",
            )
        return current_user

    return _dependency
