"""Authentification : login (email + mot de passe) puis vérification TOTP,
et logout. Aucune inscription libre en V1 — les comptes sont créés par un
administrateur via app/scripts/create_admin.py (ou une future page Settings
> Utilisateurs réservée au rôle admin).

Le jeton CSRF est géré globalement par CSRFCookieMiddleware et injecté dans
chaque template par le context_processor de app/core/templating.py — les
routes ci-dessous n'ont plus besoin de le manipuler explicitement.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import (
    PENDING_2FA_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_pending_2fa_token,
    create_session_token,
    get_current_user,
    read_pending_2fa_token,
    verify_csrf,
    verify_password,
    verify_totp_code,
)
from app.core.templating import templates
from app.models.user import User

router = APIRouter(tags=["auth"])
settings = get_settings()


@router.get("/login")
def login_form(request: Request, session: Session = Depends(get_session)):
    if get_current_user(session=session, session_token=request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"error": None, "email": None})


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    user = session.exec(select(User).where(User.email == email)).first()

    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Email ou mot de passe incorrect.", "email": email},
            status_code=400,
        )

    response = RedirectResponse(url="/login/verify", status_code=303)
    response.set_cookie(
        PENDING_2FA_COOKIE_NAME,
        create_pending_2fa_token(user.id),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.pending_2fa_max_age_seconds,
    )
    return response


@router.get("/login/verify")
def verify_2fa_form(request: Request):
    pending_token = request.cookies.get(PENDING_2FA_COOKIE_NAME)
    if not pending_token or read_pending_2fa_token(pending_token) is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "auth/verify_2fa.html", {"error": None})


@router.post("/login/verify", dependencies=[Depends(verify_csrf)])
def verify_2fa_submit(
    request: Request,
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    pending_token = request.cookies.get(PENDING_2FA_COOKIE_NAME)
    user_id = read_pending_2fa_token(pending_token) if pending_token else None

    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    user = session.get(User, user_id)

    if user is None or not user.is_active or not user.totp_secret or not verify_totp_code(user.totp_secret, code):
        return templates.TemplateResponse(
            request,
            "auth/verify_2fa.html",
            {"error": "Code invalide ou expiré."},
            status_code=400,
        )

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(PENDING_2FA_COOKIE_NAME)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return response


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
