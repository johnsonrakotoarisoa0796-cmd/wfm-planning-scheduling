"""Middleware CSRF.

Le formulaire de déconnexion apparaît dans la sidebar sur TOUTE page
authentifiée, pas seulement celles avec un formulaire "métier" — il faut
donc qu'un jeton CSRF existe et soit cohérent (même valeur en cookie et
dans le HTML) pour n'importe quelle page rendue, pas seulement celles où un
router pense à l'initialiser explicitement.

Ce middleware pose le cookie une seule fois si absent, et rend la valeur
disponible via request.state.csrf_token pour le context_processor Jinja
(app/core/templating.py) : le template et le cookie utilisent alors
toujours exactement la même valeur, par construction.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import CSRF_COOKIE_NAME, generate_csrf_token

settings = get_settings()


class CSRFCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)
        token = existing_token or generate_csrf_token()
        request.state.csrf_token = token

        response = await call_next(request)

        if not existing_token:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                token,
                httponly=True,
                secure=settings.secure_cookies,
                samesite="lax",
            )
        return response
