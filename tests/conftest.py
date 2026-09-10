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
