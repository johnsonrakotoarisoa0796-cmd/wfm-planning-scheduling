"""Utilitaires de date/heure partagés.

datetime.utcnow() est déprécié depuis Python 3.12 (retourne un datetime
naïf). Toutes les colonnes created_at / imported_at du projet utilisent
utc_now() ci-dessous pour rester timezone-aware.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Retourne l'heure actuelle en UTC, timezone-aware."""
    return datetime.now(timezone.utc)
