"""Envoi d'emails transactionnels, notamment les OTP de connexion."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def smtp_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.smtp_username
        and settings.smtp_password
        and settings.smtp_from_email
    )


def send_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    settings = get_settings()
    if not smtp_configured():
        raise RuntimeError(
            "L'envoi d'email n'est pas configuré. Renseignez SMTP_USERNAME, "
            "SMTP_PASSWORD et SMTP_FROM_EMAIL dans Render."
        )

    message = EmailMessage()
    message["From"] = (
        f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if settings.smtp_from_name
        else settings.smtp_from_email
    )
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    if settings.smtp_use_tls and settings.smtp_port == 587:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


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
