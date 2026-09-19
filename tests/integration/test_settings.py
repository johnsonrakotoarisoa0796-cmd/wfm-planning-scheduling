from datetime import date
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import pyotp

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app, bootstrap_markets
from app.models.campaign import Campaign
from app.models.enums import UserRole
from app.models.skill import Skill, Channel
from app.models.user import User

TEST_PASSWORD = "mot-de-passe-solide-123"


def _make_user(engine):
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(
            email="admin-settings@wfm.local",
            hashed_password=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
            totp_secret=secret,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.email, secret


def _login(client: TestClient, email: str, secret: str):
    client.get("/login")
    csrf = client.cookies.get("csrf_token")
    client.post("/login", data={"email": email, "password": TEST_PASSWORD, "csrf_token": csrf}, follow_redirects=False)
    client.get("/login/verify")
    csrf2 = client.cookies.get("csrf_token")
    client.post("/login/verify", data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf2}, follow_redirects=False)


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    bootstrap_markets(db_engine=engine)
    return engine


def test_settings_allows_campaign_and_skill_creation():
    engine = _setup()
    email, secret = _make_user(engine)

    def _override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        with TestClient(app) as client:
            _login(client, email, secret)
            csrf = client.cookies.get("csrf_token")

            campaign_response = client.post(
                "/settings/campaigns",
                data={
                    "csrf_token": csrf,
                    "name": "Support Client UK",
                    "code": "SUP-UK",
                    "description": "UK",
                },
                follow_redirects=False,
            )
            assert campaign_response.status_code == 303

            with Session(engine) as session:
                campaign = session.exec(select(Campaign).where(Campaign.code == "SUP-UK")).one()
                market = session.exec(select(__import__("app.models.market", fromlist=["Market"]).Market).where(
                    __import__("app.models.market", fromlist=["Market"]).Market.code == "UK"
                )).one()

            skill_response = client.post(
                "/settings/skills",
                data={
                    "csrf_token": client.cookies.get("csrf_token"),
                    "campaign_id": str(campaign.id),
                    "name": "Email",
                    "channel": "email",
                    "market_id": str(market.id),
                },
                follow_redirects=False,
            )
            assert skill_response.status_code == 303

            with Session(engine) as session:
                skill = session.exec(select(Skill).where(Skill.name == "Email")).one()
                assert skill.channel == Channel.EMAIL
                assert skill.market_id == market.id

            page = client.get("/settings")
            assert page.status_code == 200
            assert "Support Client UK" in page.text
            assert "Email" in page.text
    finally:
        app.dependency_overrides.clear()
