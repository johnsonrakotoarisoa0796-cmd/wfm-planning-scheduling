"""Point d'entrée de l'application WFM Planning & Scheduling.

Commit 01 - Initialize WFM platform : squelette minimal, un endpoint /health
pour le health check Render. Les routers métier (dashboard, ltf, stf, daily,
capacity, scheduling, kpi, shrinkage, overtime, reports, settings, auth)
seront ajoutés progressivement à partir du commit 03.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="WFM Planning & Scheduling",
    description="Plateforme de planification, capacity planning et suivi WFM pour centre de contacts.",
    version="0.1.0",
    debug=not settings.is_production,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health", tags=["system"])
def health_check() -> dict:
    """Endpoint de vérification de santé, utilisé par le health check Render."""
    return {"status": "ok", "service": "wfm-planning-scheduling", "env": settings.env}


@app.get("/", tags=["system"])
def root() -> dict:
    """Racine temporaire — sera remplacée par le dashboard (commit 13)."""
    return {"message": "WFM Planning & Scheduling API. Voir /health et /docs."}
