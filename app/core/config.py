"""Configuration centralisée de l'application.

Toutes les valeurs métier configurables (heures de travail, durée d'intervalle,
etc.) passent par ici plutôt que d'être codées en dur dans les services
(règle §19 / §38 du cahier des charges).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres de l'application, lus depuis l'environnement ou un fichier .env."""

    # Environnement
    env: str = "development"
    secret_key: str = "change-me-in-production"

    # Base de données (Supabase / PostgreSQL)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/wfm"

    # Règles métier par défaut (paramétrables, jamais codées en dur ailleurs)
    daily_hours: float = 8.0
    weekly_hours: float = 40.0
    working_days: int = 5
    interval_minutes: int = 30
    default_timezone: str = "UTC"
    summer_operating_start: str = "07:00"
    summer_operating_end: str = "01:00"
    winter_operating_start: str = "08:00"
    winter_operating_end: str = "02:00"

    # Défauts WFM utilisés uniquement lorsqu'aucun paramètre hebdomadaire
    # explicite n'existe encore pour le couple campagne/skill.
    default_aht_seconds: float = 300.0
    default_occupancy_pct: float = 85.0
    default_service_level_target_pct: float = 80.0
    default_answer_time_target_seconds: float = 20.0
    default_shrinkage_pct: float = 0.0

    # Email / OTP
    otp_delivery_mode: str = "auto"  # email, totp, auto
    email_provider: str = "brevo"  # brevo, smtp
    brevo_api_key: str = ""
    brevo_from_email: str = ""
    brevo_from_name: str = "WFM Planning & Scheduling"
    email_otp_ttl_seconds: int = 10 * 60
    email_otp_resend_cooldown_seconds: int = 60
    email_otp_max_attempts: int = 5
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "WFM Planning & Scheduling"
    smtp_use_tls: bool = True

    # Sécurité / sessions
    session_max_age_seconds: int = 60 * 60 * 12  # 12h
    pending_2fa_max_age_seconds: int = 60 * 5  # 5 min, cf. §8
    secure_cookies: bool = True  # False uniquement en dev local (http)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance mise en cache des paramètres de l'application."""
    return Settings()
