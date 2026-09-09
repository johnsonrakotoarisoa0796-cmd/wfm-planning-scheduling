"""Connexion à la base PostgreSQL (Supabase) via SQLModel.

Les modèles (User, Campaign, ForecastVersion, ...) seront ajoutés à l'étape
suivante (commit 02 - Add database models), avec la première migration
Alembic. Ce module ne fait que fournir l'engine et la session — aucune
logique métier ici.
"""

from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping évite les connexions mortes côté Supabase après veille.
engine = create_engine(
    settings.database_url,
    echo=not settings.is_production,
    pool_pre_ping=True,
)


def get_session() -> Generator[Session, None, None]:
    """Dependency FastAPI fournissant une session DB par requête."""
    with Session(engine) as session:
        yield session
