"""Envoi d'emails transactionnels, notamment les OTP de connexion."""
from __future__ import annotations

import smtplib
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


def smtp_configured() -> bool:
    username, password, from_email = _smtp_credentials()
    return bool(username and password and from_email)


def send_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    settings = get_settings()
    username, password, from_email = _smtp_credentials()
    if not smtp_configured():
        raise RuntimeError(
            "SMTP incomplet : renseignez SMTP_USERNAME, SMTP_PASSWORD et "
            "SMTP_FROM_EMAIL dans Render."
        )

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

    if settings.smtp_use_tls and settings.smtp_port == 587:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
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



def test_smtp_connection(*, send_test_email_to: str | None = None) -> None:
    """Teste la connexion/authentification SMTP et, optionnellement, envoie un email de test."""
    settings = get_settings()
    username, password, from_email = _smtp_credentials()
    if not username or not password or not from_email:
        raise RuntimeError(
            "Configuration SMTP incomplète : SMTP_USERNAME, SMTP_PASSWORD et "
            "SMTP_FROM_EMAIL sont obligatoires."
        )

    def _send(smtp):
        smtp.login(username, password)
        if send_test_email_to:
            message = EmailMessage()
            message["From"] = (
                f"{settings.smtp_from_name} <{from_email}>"
                if settings.smtp_from_name
                else from_email
            )
            message["To"] = send_test_email_to
            message["Subject"] = "Test SMTP — WFM Planning & Scheduling"
            message.set_content(
                "Test SMTP réussi. Le service email WFM peut envoyer les OTP."
            )
            smtp.send_message(message)

    try:
        if settings.smtp_use_tls and settings.smtp_port == 587:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                _send(smtp)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                _send(smtp)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail a refusé l'authentification SMTP (535/534). "
            "Vérifiez l'adresse SMTP_USERNAME et utilisez un App Password Google "
            "de 16 caractères. La validation en deux étapes doit être activée."
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(
            "Impossible de se connecter à smtp.gmail.com. Vérifiez SMTP_HOST/PORT "
            "et la connectivité sortante de Render."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"Gmail SMTP a refusé l'opération : {str(exc)[:220]}") from exc
    except OSError as exc:
        raise RuntimeError(
            "Connexion SMTP impossible depuis Render. Vérifiez SMTP_HOST, SMTP_PORT et le réseau."
        ) from exc
