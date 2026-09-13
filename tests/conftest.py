"""Configuration pytest globale.

IMPORTANT : ces variables d'environnement doivent être posées avant le tout
premier import d'un module app.* dans la session de test — get_settings()
est mis en cache (lru_cache), donc le premier appel fige la config pour
toute la suite. C'est pourquoi ceci vit dans conftest.py (chargé par pytest
avant la collecte des modules de test) plutôt que dans un fixture normal.

SECURE_COOKIES=false est nécessaire car le TestClient FastAPI communique en
http:// (pas https://) : un cookie marqué Secure ne serait jamais renvoyé
par le client, cassant silencieusement toute vérification CSRF/session en
test. En production (Render, toujours https), le défaut Settings reste True.
"""

import os

os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_pytest_default.db")
os.environ.setdefault("ENV", "test")

# Les bootstraps inconditionnels au démarrage (ex: bootstrap_shrinkage_categories
# dans app/main.py, qui ne dépend d'aucune variable d'environnement) touchent
# directement le moteur par défaut (app.core.database.engine) — y compris
# pendant les tests, puisque TestClient déclenche le lifespan FastAPI à
# chaque fixture `with TestClient(app) as client:`. Sans ce create_all, ces
# bootstraps échoueraient sur "no such table" dès le premier test utilisant
# TestClient, avant même que le moteur de test propre à chaque fixture
# n'entre en jeu (dependency_overrides ne s'applique qu'aux dépendances de
# route, jamais au code de lifespan).
import app.models  # noqa: E402  (enregistre tous les modèles sur SQLModel.metadata)
from app.core.database import engine as _default_test_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

SQLModel.metadata.create_all(_default_test_engine)
