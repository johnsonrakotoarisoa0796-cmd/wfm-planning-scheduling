"""Authentification : mot de passe + OTP email, avec sécurité renforcée admin.

Le mode email OTP est prioritaire lorsque Gmail/SMTP est configuré. Le TOTP reste
supporté comme mécanisme de compatibilité si le mode auto doit retomber dessus.
Les administrateurs utilisent en plus deux mots-clés secrets.
"""
import base64
from io import BytesIO
from urllib.parse import quote_plus
import smtplib

import qrcode
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
    generate_totp_secret,
    get_current_user,
    hash_password,
    read_pending_2fa_token,
    totp_provisioning_uri,
    verify_csrf,
    verify_password,
    verify_totp_code,
)
from app.core.templating import templates
from app.models.enums import UserRole
from app.models.user import User
from app.services.email_service import smtp_configured
from app.services.otp_service import issue_email_otp, verify_email_otp

router = APIRouter(tags=["auth"])
settings = get_settings()


def _render_login(
    request: Request,
    *,
    error: str | None = None,
    email: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": error, "email": email},
        status_code=status_code,
    )





def _email_otp_enabled() -> bool:
    mode = settings.otp_delivery_mode.lower().strip()
    if mode == "email":
        return smtp_configured()
    if mode == "totp":
        return False
    return smtp_configured()


def _otp_configuration_error() -> str:
    if settings.otp_delivery_mode.lower().strip() == "email" and not smtp_configured():
        return (
            "La validation par email est activée mais Gmail/SMTP n'est pas configuré. "
            "Renseignez SMTP_USERNAME, SMTP_PASSWORD et SMTP_FROM_EMAIL dans Render."
        )
    return "Impossible d'envoyer le code de vérification par email. Vérifiez la configuration Gmail/SMTP."


def _pending_user(request: Request, session: Session) -> User | None:
    pending_token = request.cookies.get(PENDING_2FA_COOKIE_NAME)
    user_id = read_pending_2fa_token(pending_token) if pending_token else None
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user

def _render_admin_setup(
    request: Request,
    user: User,
    *,
    error: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "auth/setup_admin_security.html",
        {
            "error": error,
            "email": user.email,
            "email_otp": _email_otp_enabled(),
        },
        status_code=status_code,
    )


@router.get("/login")
def login_form(request: Request, session: Session = Depends(get_session)):
    if get_current_user(session=session, session_token=request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse(url="/", status_code=303)
    return _render_login(request)


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    normalized_email = email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized_email)).first()

    if user is None or not verify_password(password, user.hashed_password):
        return _render_login(
            request,
            error="Email ou mot de passe incorrect.",
            email=normalized_email,
            status_code=400,
        )

    if not user.is_active:
        return _render_login(
            request,
            error="Votre compte est en attente d'activation par un administrateur.",
            email=normalized_email,
            status_code=403,
        )

    if _email_otp_enabled():
        try:
            issue_email_otp(session, user)
        except (ValueError, RuntimeError, OSError, smtplib.SMTPException) as exc:
            session.rollback()
            return _render_login(
                request,
                error=str(exc) if isinstance(exc, ValueError) else _otp_configuration_error(),
                email=normalized_email,
                status_code=503,
            )
        next_url = "/login/admin-security" if user.role == UserRole.ADMIN else "/login/verify"
    else:
        if user.role == UserRole.ADMIN and (
            not user.totp_secret
            or not user.admin_keyword1_hash
            or not user.admin_keyword2_hash
        ):
            next_url = "/login/admin-security"
        elif user.totp_secret:
            next_url = "/login/verify"
        else:
            next_url = "/login/setup-2fa"

    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(
        PENDING_2FA_COOKIE_NAME,
        create_pending_2fa_token(user.id),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.pending_2fa_max_age_seconds,
    )
    return response


@router.get("/login/setup-2fa")
def setup_2fa_form(request: Request, session: Session = Depends(get_session)):
    pending_token = request.cookies.get(PENDING_2FA_COOKIE_NAME)
    user_id = read_pending_2fa_token(pending_token) if pending_token else None
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return RedirectResponse(url="/login", status_code=303)
    if user.role == UserRole.ADMIN:
        return RedirectResponse(url="/login/admin-security", status_code=303)

    if not user.totp_secret:
        user.totp_secret = generate_totp_secret()
        session.add(user)
        session.commit()
        session.refresh(user)

    uri = totp_provisioning_uri(user.totp_secret, user.email)
    qr = qrcode.make(uri)
    buffer = BytesIO()
    qr.save(buffer)
    qr_data = base64.b64encode(buffer.getvalue()).decode("ascii")

    return templates.TemplateResponse(
        request,
        "auth/setup_2fa.html",
        {
            "error": None,
            "email": user.email,
            "qr_data": qr_data,
            "manual_secret": user.totp_secret,
        },
    )


@router.post("/login/setup-2fa", dependencies=[Depends(verify_csrf)])
def setup_2fa_submit(
    request: Request,
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    pending_token = request.cookies.get(PENDING_2FA_COOKIE_NAME)
    user_id = read_pending_2fa_token(pending_token) if pending_token else None
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return RedirectResponse(url="/login", status_code=303)
    if user.role == UserRole.ADMIN:
        return RedirectResponse(url="/login/admin-security", status_code=303)
    if not user.totp_secret:
        return RedirectResponse(url="/login/setup-2fa", status_code=303)

    if not verify_totp_code(user.totp_secret, code.strip()):
        return templates.TemplateResponse(
            request,
            "auth/setup_2fa.html",
            {"error": "Code invalide. Vérifiez l'authenticator puis réessayez.", "email": user.email},
            status_code=400,
        )

    return _finish_login(user, request)


@router.get("/login/admin-security")
def admin_security_form(request: Request, session: Session = Depends(get_session)):
    user = _pending_user(request, session)
    if user is None or user.role != UserRole.ADMIN:
        return RedirectResponse(url="/login", status_code=303)

    needs_setup = not user.admin_keyword1_hash or not user.admin_keyword2_hash
    if needs_setup:
        return _render_admin_setup(request, user)

    return templates.TemplateResponse(
        request,
        "auth/verify_2fa.html",
        {
            "error": request.query_params.get("error"),
            "email": user.email,
            "is_admin": True,
            "email_otp": _email_otp_enabled(),
            "otp_ttl_minutes": max(1, settings.email_otp_ttl_seconds // 60),
            "resent": request.query_params.get("resent") == "1",
        },
    )


@router.post("/login/admin-security", dependencies=[Depends(verify_csrf)])
def admin_security_submit(
    request: Request,
    code: str = Form(...),
    keyword1: str = Form(""),
    keyword2: str = Form(""),
    new_keyword1: str = Form(""),
    new_keyword2: str = Form(""),
    session: Session = Depends(get_session),
):
    user = _pending_user(request, session)
    if user is None or user.role != UserRole.ADMIN:
        return RedirectResponse(url="/login", status_code=303)

    needs_setup = not user.admin_keyword1_hash or not user.admin_keyword2_hash

    if needs_setup:
        key1 = new_keyword1.strip()
        key2 = new_keyword2.strip()
        if len(key1) < 4 or len(key2) < 4:
            return _render_admin_setup(
                request, user,
                error="Les deux mots-clés doivent contenir au moins 4 caractères.",
                status_code=400,
            )
        if key1.casefold() == key2.casefold():
            return _render_admin_setup(
                request, user,
                error="Les deux mots-clés doivent être différents.",
                status_code=400,
            )
        if _email_otp_enabled():
            if not verify_email_otp(session, user, code):
                return _render_admin_setup(
                    request, user,
                    error="Code email invalide, expiré ou trop de tentatives.",
                    status_code=400,
                )
        elif not user.totp_secret or not verify_totp_code(user.totp_secret, code.strip()):
            return _render_admin_setup(
                request, user,
                error="Code TOTP invalide ou expiré.",
                status_code=400,
            )

        user.admin_keyword1_hash = hash_password(key1.casefold())
        user.admin_keyword2_hash = hash_password(key2.casefold())
        session.add(user)
        session.commit()
        return _finish_login(user, request)

    valid_key1 = verify_password(keyword1.strip().casefold(), user.admin_keyword1_hash)
    valid_key2 = verify_password(keyword2.strip().casefold(), user.admin_keyword2_hash)
    if not (valid_key1 and valid_key2):
        return templates.TemplateResponse(
            request,
            "auth/verify_2fa.html",
            {
                "error": "Un ou plusieurs mots-clés administrateur sont incorrects.",
                "email": user.email,
                "is_admin": True,
                "email_otp": _email_otp_enabled(),
            },
            status_code=400,
        )

    if _email_otp_enabled():
        if not verify_email_otp(session, user, code):
            return templates.TemplateResponse(
                request,
                "auth/verify_2fa.html",
                {
                    "error": "Code email invalide, expiré ou trop de tentatives.",
                    "email": user.email,
                    "is_admin": True,
                    "email_otp": True,
                    "otp_ttl_minutes": max(1, settings.email_otp_ttl_seconds // 60),
                },
                status_code=400,
            )
    elif not user.totp_secret or not verify_totp_code(user.totp_secret, code.strip()):
        return templates.TemplateResponse(
            request,
            "auth/verify_2fa.html",
            {"error": "Code TOTP invalide ou expiré.", "email": user.email, "is_admin": True, "email_otp": False},
            status_code=400,
        )

    return _finish_login(user, request)


@router.get("/register")
def register_form(request: Request, session: Session = Depends(get_session)):
    if get_current_user(session=session, session_token=request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"error": None, "success": None, "email": None},
    )


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    session: Session = Depends(get_session),
):
    normalized_email = email.strip().lower()
    if not normalized_email:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Adresse email obligatoire.", "success": None, "email": ""},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Le mot de passe doit contenir au moins 8 caractères.", "success": None, "email": normalized_email},
            status_code=400,
        )
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Les deux mots de passe ne correspondent pas.", "success": None, "email": normalized_email},
            status_code=400,
        )

    existing = session.exec(select(User).where(User.email == normalized_email)).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Un compte existe déjà avec cette adresse email.", "success": None, "email": normalized_email},
            status_code=400,
        )

    user = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        role=UserRole.VIEWER,
        is_active=False,
        totp_secret=None,
    )
    session.add(user)
    session.commit()
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {
            "error": None,
            "success": "Votre demande a été enregistrée. Un administrateur doit activer votre compte.",
            "email": normalized_email,
        },
    )


def _finish_login(user: User, request: Request):
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
    response.delete_cookie(PENDING_2FA_COOKIE_NAME)
    return response
