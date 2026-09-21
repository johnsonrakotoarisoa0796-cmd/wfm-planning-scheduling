"""Gestion sécurisée des codes OTP envoyés par email."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlmodel import Session

from app.core.config import get_settings
from app.core.time_utils import utc_now
from app.models.user import User
from app.services.email_service import send_login_otp


def _otp_hash(code: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _clear(user: User) -> None:
    user.email_otp_hash = None
    user.email_otp_expires_at = None
    user.email_otp_requested_at = None
    user.email_otp_attempts = 0


def issue_email_otp(session: Session, user: User, *, force: bool = False) -> None:
    settings = get_settings()
    now = utc_now()

    if not force and user.email_otp_requested_at is not None:
        elapsed = (now - user.email_otp_requested_at).total_seconds()
        if elapsed < settings.email_otp_resend_cooldown_seconds:
            remaining = int(settings.email_otp_resend_cooldown_seconds - elapsed)
            raise ValueError(f"Veuillez patienter encore {max(1, remaining)} seconde(s) avant de renvoyer un code.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    user.email_otp_hash = _otp_hash(code)
    user.email_otp_expires_at = now + timedelta(seconds=settings.email_otp_ttl_seconds)
    user.email_otp_requested_at = now
    user.email_otp_attempts = 0

    session.add(user)
    session.commit()
    try:
        send_login_otp(
            to_email=user.email,
            code=code,
            ttl_minutes=max(1, settings.email_otp_ttl_seconds // 60),
        )
    except Exception:
        session.rollback()
        _clear(user)
        session.add(user)
        session.commit()
        raise


def verify_email_otp(session: Session, user: User, code: str) -> bool:
    settings = get_settings()
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return False

    if not user.email_otp_hash or not user.email_otp_expires_at:
        return False

    if user.email_otp_attempts >= settings.email_otp_max_attempts:
        _clear(user)
        session.add(user)
        session.commit()
        return False

    user.email_otp_attempts += 1
    valid = (
        utc_now() <= user.email_otp_expires_at
        and hmac.compare_digest(user.email_otp_hash, _otp_hash(code))
    )

    if valid:
        _clear(user)
    elif user.email_otp_attempts >= settings.email_otp_max_attempts:
        _clear(user)

    session.add(user)
    session.commit()
    return valid
