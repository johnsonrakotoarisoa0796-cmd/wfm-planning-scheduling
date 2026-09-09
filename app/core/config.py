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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance mise en cache des paramètres de l'application."""
    return Settings()
