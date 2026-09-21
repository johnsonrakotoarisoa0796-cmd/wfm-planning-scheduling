"""Tests d'intégration — module Capacity Planning.

Couvre la dépendance obligatoire à un LTF actif, l'upsert (pas de
versioning — suivi opérationnel), le calcul de gap, et le RBAC.
"""

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.campaign import Campaign
from app.models.capacity import CapacityPlan
from app.models.enums import Channel, UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.capacity import CapacityPlanInput
from app.schemas.ltf import LTFCreateInput
from app.services import capacity_service, forecast_service

TEST_PASSWORD = "mot-de-passe-solide-123"


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(engine):
    def _override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def reference_data(engine):
    with Session(engine) as session:
        campaign = Campaign(name="Support Client FR", code="SUP-FR")
        session.add(campaign)
        session.commit()
        session.refresh(campaign)
        skill = Skill(campaign_id=campaign.id, name="Voix Niveau 1", channel=Channel.VOICE)
        session.add(skill)
        session.commit()
        session.refresh(skill)
        return {"campaign_id": campaign.id, "skill_id": skill.id}


@pytest.fixture()
def existing_ltf(engine, reference_data):
    with Session(engine) as session:
        return forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026, month=9,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                forecast_volume=42000, forecast_aht_seconds=320, aht_required_seconds=310,
                occupancy_required_pct=85, service_level_target_pct=80, asa_target_seconds=20,
                indoor_shrinkage_pct=18, outdoor_shrinkage_pct=7,
            ),
            created_by_user_id=None,
        )


def _make_user(engine, email: str, role: UserRole) -> dict:
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(email=email, hashed_password=hash_password(TEST_PASSWORD), role=role, is_active=True, totp_secret=secret,
            admin_keyword1_hash=hash_password("admin-key-one") if role == UserRole.ADMIN else None,
            admin_keyword2_hash=hash_password("admin-key-two") if role == UserRole.ADMIN else None)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"email": user.email, "secret": secret}


def _login(client: TestClient, email: str, secret: str) -> None:
    client.get("/login")
    csrf = client.cookies.get("csrf_token")
    step1 = client.post(
        "/login",
        data={"email": email, "password": TEST_PASSWORD, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert step1.status_code == 303
    if step1.headers.get("location") == "/login/admin-security":
        page = client.get("/login/admin-security")
        csrf2 = client.cookies.get("csrf_token")
        client.post(
            "/login/admin-security",
            data={
                "code": pyotp.TOTP(secret).now(),
                "keyword1": "admin-key-one",
                "keyword2": "admin-key-two",
                "csrf_token": csrf2,
            },
            follow_redirects=False,
        )
    else:
        client.get("/login/verify")
        csrf2 = client.cookies.get("csrf_token")
        client.post(
            "/login/verify",
            data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf2},
            follow_redirects=False,
        )


def _plan_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "period": "2026-09",
        "campaign_id": str(reference_data["campaign_id"]),
        "skill_id": str(reference_data["skill_id"]),
        "current_hc": "25",
        "hiring": "5",
        "transfers_in": "2",
        "transfers_out": "3",
        "attrition_pct": "5",
        "absenteeism_pct": "3",
        "notes": "Test",
    }
    payload.update(overrides)
    return payload


# --- Dépendance obligatoire à un LTF actif --------------------------------------

def test_create_plan_fails_without_active_ltf(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post("/capacity/new", data={**_plan_payload(reference_data), "csrf_token": csrf})
    assert response.status_code == 400
    assert "LTF" in response.text


def test_create_plan_succeeds_with_active_ltf(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/capacity/new", data={**_plan_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/capacity/1"


def test_plan_detail_shows_gap_and_status(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/capacity/new", data={**_plan_payload(reference_data), "csrf_token": csrf})

    detail = client.get("/capacity/1")
    assert detail.status_code == 200
    assert "Gap actuel" in detail.text
    assert "Gap projeté" in detail.text


# --- Upsert (pas de versioning) --------------------------------------------------

def test_resaving_same_period_updates_in_place_no_duplicate(engine, reference_data, existing_ltf):
    with Session(engine) as session:
        first = capacity_service.upsert_capacity_plan(
            session,
            CapacityPlanInput(
                period="2026-09", campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                current_hc=25, hiring=5, transfers_in=2, transfers_out=3,
                attrition_pct=5, absenteeism_pct=3,
            ),
            created_by_user_id=None,
        )
        second = capacity_service.upsert_capacity_plan(
            session,
            CapacityPlanInput(
                period="2026-09", campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                current_hc=27, hiring=6, transfers_in=1, transfers_out=2,
                attrition_pct=4, absenteeism_pct=2,
            ),
            created_by_user_id=None,
        )
        assert first.id == second.id  # meme ligne mise a jour, pas une nouvelle

        all_plans = session.exec(select(CapacityPlan)).all()
        assert len(all_plans) == 1
        assert all_plans[0].current_hc == 27


def test_projected_hc_and_required_hc_are_computed_correctly(engine, reference_data, existing_ltf):
    with Session(engine) as session:
        plan = capacity_service.upsert_capacity_plan(
            session,
            CapacityPlanInput(
                period="2026-09", campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                current_hc=25, hiring=5, transfers_in=2, transfers_out=3,
                attrition_pct=5, absenteeism_pct=3,
            ),
            created_by_user_id=None,
        )
        assert plan.required_hc == pytest.approx(existing_ltf.headcount_required)
        # Future HC = 25 + 5 + 2 - 3 - (25*0.05 + 25*0.03) = 29 - 2.0 = 27.0
        assert plan.projected_hc == pytest.approx(27.0)


# --- RBAC ------------------------------------------------------------------------

def test_viewer_cannot_create_plan(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/capacity/new")
    assert response.status_code == 403


def test_capacity_list_requires_login(client: TestClient):
    response = client.get("/capacity", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- CSRF / validation ----------------------------------------------------------

def test_create_plan_without_csrf_is_rejected(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/capacity/new", data=_plan_payload(reference_data))
    assert response.status_code == 400


def test_create_plan_rejects_invalid_period_format(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _plan_payload(reference_data, period="Septembre-2026")
    response = client.post("/capacity/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


# --- Filtres -----------------------------------------------------------------------

def test_capacity_list_filters_by_campaign(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/capacity/new", data={**_plan_payload(reference_data), "csrf_token": csrf})

    matching = client.get(f"/capacity?campaign_id={reference_data['campaign_id']}")
    assert "2026-09" in matching.text

    other = client.get("/capacity?campaign_id=999999")
    assert "Aucun plan" in other.text
