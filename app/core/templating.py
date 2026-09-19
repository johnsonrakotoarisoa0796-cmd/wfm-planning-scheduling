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

from fastapi.templating import Jinja2Templates
from starlette.requests import Request


def _global_context(request: Request) -> dict:
    return {
        # Posé par CSRFCookieMiddleware (app/core/middleware.py), garantit
        # la même valeur que le cookie envoyé au navigateur.
        "csrf_token": getattr(request.state, "csrf_token", ""),
        # Render expose le SHA du commit déployé : il sert à invalider
        # automatiquement le cache navigateur des assets statiques après chaque release.
        "asset_version": os.environ.get("RENDER_GIT_COMMIT", "dev"),
    }


templates = Jinja2Templates(directory="app/templates", context_processors=[_global_context])
