"""Instance Jinja2Templates partagée par tous les routers.

Un context_processor injecte automatiquement csrf_token dans CHAQUE page
rendue — par exemple le formulaire de déconnexion dans la sidebar en a
besoin sur toutes les pages authentifiées, pas seulement celles qui ont un
formulaire "métier" propre.

IMPORTANT : ce processor n'accède JAMAIS à la base de données directement
(pas d'import du engine global). current_user doit être passé explicitement
par chaque router dans son contexte de template — ces routers dépendent
déjà de require_login/require_role/get_current_user via Depends(), donc
l'objet est disponible sans requête supplémentaire. Un context_processor
qui interrogerait la DB via un engine importé au niveau module
contournerait les dependency_overrides de FastAPI (utilisés par les tests
pour brancher une base de test) et casserait silencieusement l'isolation
des tests.
"""

import os
from datetime import date, timedelta
from zoneinfo import available_timezones

from fastapi.templating import Jinja2Templates
from starlette.requests import Request


def _week_options() -> list[dict]:
    """Semaines ISO autour de la semaine courante pour les sélecteurs WFM."""
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    options = []
    for offset in range(-52, 157):
        monday = current_monday + timedelta(weeks=offset)
        iso = monday.isocalendar()
        sunday = monday + timedelta(days=6)
        options.append(
            {
                "value": f"{iso.year}-W{iso.week:02d}",
                "label": f"W{iso.week:02d} · {monday.strftime('%d/%m/%Y')} → {sunday.strftime('%d/%m/%Y')}",
            }
        )
    return options


def _timezone_options() -> list[str]:
    preferred = [
        "UTC",
        "Africa/Antananarivo",
        "Africa/Nairobi",
        "Europe/Paris",
        "Europe/London",
        "Europe/Berlin",
        "Europe/Madrid",
        "Europe/Amsterdam",
        "America/New_York",
        "America/Chicago",
        "America/Los_Angeles",
        "Asia/Kolkata",
        "Asia/Tokyo",
        "Asia/Singapore",
        "Australia/Sydney",
    ]
    available = available_timezones()
    ordered = [tz for tz in preferred if tz in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


_WEEK_OPTIONS = _week_options()
_TIMEZONE_OPTIONS = _timezone_options()


def _global_context(request: Request) -> dict:
    current_week = date.today().strftime("%G-W%V")
    return {
        # Posé par CSRFCookieMiddleware (app/core/middleware.py), garantit
        # la même valeur que le cookie envoyé au navigateur.
        "csrf_token": getattr(request.state, "csrf_token", ""),
        # Render expose le SHA du commit déployé : il sert à invalider
        # automatiquement le cache navigateur des assets statiques après chaque release.
        "asset_version": os.environ.get("RENDER_GIT_COMMIT", "dev"),
        "week_options": _WEEK_OPTIONS,
        "timezone_options": _TIMEZONE_OPTIONS,
        "current_week": current_week,
    }


templates = Jinja2Templates(directory="app/templates", context_processors=[_global_context])
