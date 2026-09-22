"""Envoi d'emails transactionnels, notamment les OTP de connexion."""
from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from app.core.config import get_settings


def _smtp_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    username = settings.smtp_username.strip()
    # Google affiche les App Passwords avec des espaces pour la lisibilité.
    # Ils sont normalisés ici avant l'authentification SMTP.
    password = "".join(settings.smtp_password.split())
    from_email = settings.smtp_from_email.strip()
    return username, password, from_email


def brevo_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.brevo_api_key.strip()
        and settings.brevo_from_email.strip()
    )


def email_delivery_configured() -> bool:
    provider = get_settings().email_provider.lower().strip()
    if provider == "brevo":
        return brevo_configured()
    return smtp_configured()


def smtp_configuration_error() -> str | None:
    username, password, from_email = _smtp_credentials()
    missing = []
    if not username:
        missing.append("SMTP_USERNAME")
    if not password:
        missing.append("SMTP_PASSWORD")
    if not from_email:
        missing.append("SMTP_FROM_EMAIL")
    return (
        "Variables SMTP manquantes dans Render : " + ", ".join(missing) + "."
        if missing else None
    )


def smtp_configured() -> bool:
    return smtp_configuration_error() is None


def email_delivery_configuration_error() -> str | None:
    settings = get_settings()
    provider = settings.email_provider.lower().strip()
    if provider == "brevo":
        missing = []
        if not settings.brevo_api_key.strip():
            missing.append("BREVO_API_KEY")
        if not settings.brevo_from_email.strip():
            missing.append("BREVO_FROM_EMAIL")
        if missing:
            return "Variables email manquantes dans Render : " + ", ".join(missing) + "."
        return None
    if provider == "smtp":
        return smtp_configuration_error()
    return "EMAIL_PROVIDER doit être 'brevo' ou 'smtp'."


def _send_via_brevo(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None,
) -> None:
    settings = get_settings()
    payload = {
        "sender": {
            "email": settings.brevo_from_email.strip(),
            "name": settings.brevo_from_name or settings.smtp_from_name,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body

    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": settings.brevo_api_key.strip(),
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Brevo API a renvoyé HTTP {response.status}.")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise RuntimeError(
            f"Brevo a refusé l'envoi (HTTP {exc.code}). {detail[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Render n'arrive pas à joindre l'API Brevo en HTTPS. Détail réseau: {exc.reason}"
        ) from exc


def send_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    settings = get_settings()
    provider = settings.email_provider.lower().strip()

    if provider == "brevo":
        config_error = email_delivery_configuration_error()
        if config_error:
            raise RuntimeError(config_error)
        _send_via_brevo(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return

    username, password, from_email = _smtp_credentials()
    config_error = smtp_configuration_error()
    if config_error:
        raise RuntimeError(config_error)

    message = EmailMessage()
    message["From"] = (
        f"{settings.smtp_from_name} <{from_email}>"
        if settings.smtp_from_name
        else from_email
    )
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if settings.smtp_use_tls and settings.smtp_port == 587:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail a refusé l'authentification SMTP. Vérifiez SMTP_USERNAME et SMTP_PASSWORD. "
            f"Code SMTP: {exc.smtp_code}"
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(
            f"Connexion Gmail refusée ({exc.smtp_code}). Vérifiez SMTP_HOST, SMTP_PORT et TLS."
        ) from exc
    except smtplib.SMTPServerDisconnected as exc:
        raise RuntimeError(
            "Gmail a fermé la connexion SMTP avant l'envoi."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(
            f"Gmail SMTP a refusé l'opération ({type(exc).__name__})."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "Render n'arrive pas à joindre Gmail SMTP. Les services Free Render bloquent "
            "les ports SMTP sortants ; utilisez EMAIL_PROVIDER=brevo."
        ) from exc



def send_login_otp(*, to_email: str, code: str, ttl_minutes: int) -> None:
    subject = "Votre code de connexion WFM"
    text_body = (
        "Votre code de connexion WFM Planning & Scheduling est : "
        f"{code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes. "
        "Si vous n'êtes pas à l'origine de cette connexion, ignorez cet email."
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:28px;color:#172033">
      <h2 style="margin-bottom:8px">WFM Planning &amp; Scheduling</h2>
      <p>Votre code de connexion est :</p>
      <div style="font-size:32px;font-weight:800;letter-spacing:8px;text-align:center;padding:20px;border-radius:12px;background:#eef2ff;color:#3156d8">{code}</div>
      <p style="margin-top:18px">Ce code expire dans <strong>{ttl_minutes} minutes</strong>.</p>
      <p style="color:#68758a;font-size:13px">Si vous n'êtes pas à l'origine de cette connexion, ignorez cet email.</p>
    </div>
    """
    send_email(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)



def test_email_delivery(*, send_test_email_to: str) -> None:
    send_email(
        to_email=send_test_email_to,
        subject="Test email — WFM Planning & Scheduling",
        text_body="Test réussi. Le service email WFM peut envoyer les OTP.",
        html_body="<p><strong>Test réussi.</strong> Le service email WFM peut envoyer les OTP.</p>",
    )
