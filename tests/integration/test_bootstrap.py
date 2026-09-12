"""Tests — bootstrap_admin_if_configured() (app/main.py).

Pensé pour un déploiement Render sans accès shell (plan free) : crée un
compte admin au démarrage si BOOTSTRAP_ADMIN_EMAIL/PASSWORD sont définis.
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.main import bootstrap_admin_if_configured
from app.models.enums import UserRole
from app.models.user import User


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def test_noop_when_env_vars_absent(engine, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    bootstrap_admin_if_configured(db_engine=engine)
    with Session(engine) as session:
        assert session.exec(select(User)).first() is None


def test_noop_when_only_email_set(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@wfm.local")
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    bootstrap_admin_if_configured(db_engine=engine)
    with Session(engine) as session:
        assert session.exec(select(User)).first() is None


def test_creates_admin_when_both_env_vars_set(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@wfm.local")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "SuperSecret123")
    bootstrap_admin_if_configured(db_engine=engine)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "admin@wfm.local")).first()
        assert user is not None
        assert user.role == UserRole.ADMIN
        assert user.is_active is True
        assert user.totp_secret  # un secret a ete genere


def test_is_idempotent_does_not_reset_existing_account(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@wfm.local")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "SuperSecret123")
    bootstrap_admin_if_configured(db_engine=engine)

    with Session(engine) as session:
        first_secret = session.exec(select(User).where(User.email == "admin@wfm.local")).first().totp_secret

    # Deuxieme appel (ex: redemarrage du service) avec le meme email : ne
    # doit ni recreer, ni regenerer le secret TOTP, ni planter sur un
    # doublon d'email.
    bootstrap_admin_if_configured(db_engine=engine)

    with Session(engine) as session:
        users = session.exec(select(User).where(User.email == "admin@wfm.local")).all()
        assert len(users) == 1
        assert users[0].totp_secret == first_secret
