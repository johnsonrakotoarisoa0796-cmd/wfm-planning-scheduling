"""Tests — bootstrap_admin_if_configured() (app/main.py).

Pensé pour un déploiement Render sans accès shell (plan free) : crée un
compte admin au démarrage si BOOTSTRAP_ADMIN_EMAIL/PASSWORD sont définis.
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.main import bootstrap_admin_if_configured, bootstrap_demo_data_if_configured
from app.models.campaign import Campaign
from app.models.enums import UserRole
from app.models.skill import Skill
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


# --- bootstrap_demo_data_if_configured -----------------------------------------

def test_demo_data_noop_when_env_var_absent(engine, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_DEMO_DATA", raising=False)
    bootstrap_demo_data_if_configured(db_engine=engine)
    with Session(engine) as session:
        assert session.exec(select(Campaign)).first() is None


def test_demo_data_noop_when_env_var_falsy(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DEMO_DATA", "false")
    bootstrap_demo_data_if_configured(db_engine=engine)
    with Session(engine) as session:
        assert session.exec(select(Campaign)).first() is None


def test_demo_data_creates_campaign_and_skill_when_enabled(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DEMO_DATA", "true")
    bootstrap_demo_data_if_configured(db_engine=engine)
    with Session(engine) as session:
        campaign = session.exec(select(Campaign)).first()
        assert campaign is not None
        assert campaign.code == "SUP-FR"
        skill = session.exec(select(Skill).where(Skill.campaign_id == campaign.id)).first()
        assert skill is not None


def test_demo_data_is_idempotent_no_duplicate_campaign(engine, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_DEMO_DATA", "true")
    bootstrap_demo_data_if_configured(db_engine=engine)
    bootstrap_demo_data_if_configured(db_engine=engine)
    with Session(engine) as session:
        campaigns = session.exec(select(Campaign)).all()
        assert len(campaigns) == 1


def test_demo_data_skips_if_campaign_already_exists_manually(engine, monkeypatch):
    # Une campagne creee autrement (ex: future page Settings) ne doit pas
    # etre dupliquee par le bootstrap au redemarrage suivant.
    with Session(engine) as session:
        session.add(Campaign(name="Deja la", code="EXIST"))
        session.commit()

    monkeypatch.setenv("BOOTSTRAP_DEMO_DATA", "true")
    bootstrap_demo_data_if_configured(db_engine=engine)

    with Session(engine) as session:
        campaigns = session.exec(select(Campaign)).all()
        assert len(campaigns) == 1
        assert campaigns[0].code == "EXIST"
