"""Envoi d'emails transactionnels, notamment les OTP de connexion.

Le transport Brevo est privilégié en production. La délivrabilité vers Yahoo,
Outlook et Hotmail dépend aussi de l'authentification DNS du domaine expéditeur
(SPF/DKIM/DMARC) et de la réputation du domaine.
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Domains personnels/gratuits fréquemment utilisés pour recevoir des messages.
# Ils ne conviennent pas comme domaine expéditeur Brevo en production :
# Brevo demande un domaine que l'expéditeur contrôle et authentifie.
_FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.fr",
    "ymail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "aol.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
}


def _smtp_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    username = settings.smtp_username.strip()
    # Google affiche les App Passwords avec des espaces pour la lisibilité.
    # Ils sont normalisés ici avant l'authentification SMTP.
    password = "".join(settings.smtp_password.split())
    from_email = settings.smtp_from_email.strip()
    return username, password, from_email


def sender_domain(email_address: str) -> str:
    """Retourne le domaine d'une adresse email, normalisé en minuscules."""
    _, parsed = parseaddr(email_address.strip())
    address = parsed or email_address.strip()
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def is_free_email_domain(email_address: str) -> bool:
    return sender_domain(email_address) in _FREE_EMAIL_DOMAINS


def sender_configuration_error(*, provider: str, from_email: str, production: bool) -> str | None:
    """Valide la configuration expéditeur sans jamais vérifier le DNS côté Python."""
    if not from_email.strip():
        return f"{'BREVO_FROM_EMAIL' if provider == 'brevo' else 'SMTP_FROM_EMAIL'} est obligatoire."

    address = parseaddr(from_email.strip())[1]
    if not address or "@" not in address or sender_domain(address) == "":
        return "L'adresse expéditeur email est invalide."

    if production and is_free_email_domain(address):
        variable = "BREVO_FROM_EMAIL" if provider == "brevo" else "SMTP_FROM_EMAIL"
        return (
            f"{variable} ne doit pas utiliser un domaine email gratuit "
            f"({sender_domain(address)}). Utilisez une adresse sur votre propre domaine "
            "et authentifiez ce domaine avec SPF, DKIM et DMARC."
        )
    return None


def brevo_configured() -> bool:
    settings = get_settings()
    return not bool(email_delivery_configuration_error())


def email_delivery_configured() -> bool:
    return email_delivery_configuration_error() is None


def smtp_configuration_error() -> str | None:
    settings = get_settings()
    username, password, from_email = _smtp_credentials()
    missing = []
    if not username:
        missing.append("SMTP_USERNAME")
    if not password:
        missing.append("SMTP_PASSWORD")
    if not from_email:
        missing.append("SMTP_FROM_EMAIL")
    if missing:
        return "Variables SMTP manquantes dans Render : " + ", ".join(missing) + "."

    sender_error = sender_configuration_error(
        provider="smtp",
        from_email=from_email,
        production=settings.is_production,
    )
    return sender_error


def smtp_configured() -> bool:
    return smtp_configuration_error() is None


def email_delivery_configuration_error() -> str | None:
    settings = get_settings()
    provider = settings.email_provider.lower().strip()

    if provider == "brevo":
        if not settings.brevo_api_key.strip():
            return "Variables email manquantes dans Render : BREVO_API_KEY."
        if not settings.brevo_from_email.strip():
            return "Variables email manquantes dans Render : BREVO_FROM_EMAIL."

        sender_error = sender_configuration_error(
            provider="brevo",
            from_email=settings.brevo_from_email,
            production=settings.is_production,
        )
        if sender_error:
            return sender_error
        return None

    if provider == "smtp":
        return smtp_configuration_error()

    return "EMAIL_PROVIDER doit être 'brevo' ou 'smtp'."


def _brevo_payload(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None,
) -> dict:
    settings = get_settings()
    payload = {
        "sender": {
            "email": settings.brevo_from_email.strip(),
            "name": settings.brevo_from_name or settings.smtp_from_name,
        },
        "to": [{"email": to_email.strip()}],
        "subject": subject,
        "textContent": text_body,
        # Tag transactionnel utile pour retrouver les OTP dans Brevo.
        "tags": ["wfm-otp"],
    }

    reply_to = settings.brevo_reply_to_email.strip()
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    if html_body:
        payload["htmlContent"] = html_body
    return payload


def _send_via_brevo(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None,
) -> None:
    settings = get_settings()
    payload = _brevo_payload(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

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
            raw = response.read().decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Brevo API a renvoyé HTTP {response.status}.")

            message_id = None
            try:
                data = json.loads(raw) if raw else {}
                message_id = data.get("messageId")
            except json.JSONDecodeError:
                data = {}

            # Brevo accepte la demande avant la livraison finale. Le messageId
            # permet ensuite de suivre Delivered/Blocked/Bounce dans Brevo.
            logger.info(
                "OTP email accepté par Brevo: recipient=%s message_id=%s",
                to_email.strip(),
                message_id or "unknown",
            )
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise RuntimeError(
            f"Brevo a refusé l'envoi (HTTP {exc.code}). {detail[:500]}"
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
    message["X-Auto-Response-Suppress"] = "All"
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
            "Le serveur SMTP a refusé l'authentification. Vérifiez SMTP_USERNAME et SMTP_PASSWORD. "
            f"Code SMTP: {exc.smtp_code}"
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(
            f"Connexion SMTP refusée ({exc.smtp_code}). Vérifiez SMTP_HOST, SMTP_PORT et TLS."
        ) from exc
    except smtplib.SMTPServerDisconnected as exc:
        raise RuntimeError(
            "Le serveur SMTP a fermé la connexion avant l'envoi."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(
            f"Le serveur SMTP a refusé l'opération ({type(exc).__name__})."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "Render n'arrive pas à joindre le serveur SMTP. Pour le plan Free Render, "
            "utilisez EMAIL_PROVIDER=brevo et l'API HTTPS Brevo."
        ) from exc


def send_login_otp(*, to_email: str, code: str, ttl_minutes: int) -> None:
    subject = "Code de vérification — WFM Planning & Scheduling"
    text_body = (
        "Votre code de vérification WFM Planning & Scheduling est : "
        f"{code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes. "
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
    )
    html_body = f"""
    <html>
      <body style="font-family:Arial,sans-serif;margin:0;padding:24px;background:#f6f8fb;color:#172033">
        <div style="max-width:560px;margin:auto;background:#fff;padding:28px;border:1px solid #e7ebf2;border-radius:12px">
          <h2 style="margin:0 0 14px">WFM Planning &amp; Scheduling</h2>
          <p>Votre code de vérification est :</p>
          <p style="font-size:30px;font-weight:700;letter-spacing:8px;text-align:center;padding:18px;background:#eef2ff;border-radius:10px">{code}</p>
          <p>Ce code expire dans <strong>{ttl_minutes} minutes</strong>.</p>
          <p style="font-size:13px;color:#68758a">Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
        </div>
      </body>
    </html>
    """
    send_email(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)


def test_email_delivery(*, send_test_email_to: str) -> None:
    send_email(
        to_email=send_test_email_to,
        subject="Test email — WFM Planning & Scheduling",
        text_body="Test réussi. Le service email WFM peut envoyer les OTP.",
        html_body="<p><strong>Test réussi.</strong> Le service email WFM peut envoyer les OTP.</p>",
    )
