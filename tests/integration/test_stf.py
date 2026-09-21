"""Tests d'intégration — module STF Weekly.

Couvre le flux HTTP complet, la dépendance obligatoire à un LTF actif, le
versioning hebdomadaire, et le RBAC.
"""

from datetime import date, time

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.campaign import Campaign
from app.models.enums import Channel, ForecastVersionType, UserRole
from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
from app.models.intraday import IntervalForecast
from app.models.skill import Skill
from app.models.user import User
from app.schemas.ltf import LTFCreateInput
from app.schemas.stf import STFCreateInput
from app.services import forecast_service

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
    """LTF de septembre 2026 déjà en base — la semaine ISO 37 tombe dedans."""
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
        user = User(
            email=email, hashed_password=hash_password(TEST_PASSWORD),
            role=role, is_active=True, totp_secret=secret,
            admin_keyword1_hash=hash_password("admin-key-one") if role == UserRole.ADMIN else None,
            admin_keyword2_hash=hash_password("admin-key-two") if role == UserRole.ADMIN else None,
        )
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


def _stf_form_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "period": "2026-W37",  # tombe en septembre 2026
        "campaign_id": str(reference_data["campaign_id"]),
        "skill_id": str(reference_data["skill_id"]),
        "volume": "44500",
        "aht_seconds": "335",
        "occupancy_pct": "86",
        "shrinkage_pct": "28",
        "service_level_target_pct": "80",
        "notes": "Pic saisonnier",
    }
    payload.update(overrides)
    return payload


# --- Dépendance obligatoire à un LTF actif --------------------------------------

def test_create_stf_fails_without_active_ltf(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post("/stf/new", data={**_stf_form_payload(reference_data), "csrf_token": csrf})
    assert response.status_code == 400
    assert "LTF" in response.text


def test_create_stf_succeeds_with_active_ltf(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/stf/new", data={**_stf_form_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/stf/1"


def test_stf_detail_shows_ltf_comparison(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/stf/new", data={**_stf_form_payload(reference_data), "csrf_token": csrf})

    detail = client.get("/stf/1")
    assert detail.status_code == 200
    assert "LTF vs STF" in detail.text
    assert "Adjustment" in detail.text


def test_ltf_detail_shows_linked_stf_week(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/stf/new", data={**_stf_form_payload(reference_data), "csrf_token": csrf})

    ltf_detail = client.get(f"/ltf/{existing_ltf.id}")
    assert "Réajustements STF liés" in ltf_detail.text
    assert "Semaine 37" in ltf_detail.text


# --- RBAC ------------------------------------------------------------------------

def test_viewer_cannot_create_stf(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/stf/new")
    assert response.status_code == 403


def test_stf_list_requires_login(client: TestClient):
    response = client.get("/stf", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- CSRF / validation -------------------------------------------------------------

def test_create_stf_without_csrf_is_rejected(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/stf/new", data=_stf_form_payload(reference_data))
    assert response.status_code == 400


def test_create_stf_rejects_invalid_week(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _stf_form_payload(reference_data, period="2026-W99")
    response = client.post("/stf/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


# --- Versioning (§9) -----------------------------------------------------------------

def test_creating_second_stf_for_same_week_does_not_overwrite_first(engine, reference_data, existing_ltf):
    with Session(engine) as session:
        first = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026, iso_week=37,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                volume=44500, aht_seconds=335, occupancy_pct=86, shrinkage_pct=28,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )
        second = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026, iso_week=37,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                volume=47000, aht_seconds=340, occupancy_pct=87, shrinkage_pct=29,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )

        assert first.id != second.id
        all_stf = session.exec(select(STFForecast)).all()
        assert len(all_stf) == 2
        assert session.get(STFForecast, first.id).volume == 44500

        first_version = session.get(ForecastVersion, first.forecast_version_id)
        second_version = session.get(ForecastVersion, second.forecast_version_id)
        assert first_version.is_current is False
        assert second_version.is_current is True

        current = forecast_service.list_current_stf_forecasts(session, iso_year=2026)
        assert len(current) == 1
        assert current[0].volume == 47000


def test_stf_parent_version_points_to_ltf(engine, reference_data, existing_ltf):
    with Session(engine) as session:
        stf = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026, iso_week=37,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                volume=44500, aht_seconds=335, occupancy_pct=86, shrinkage_pct=28,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )
        stf_version = session.get(ForecastVersion, stf.forecast_version_id)
        assert stf_version.version_type == ForecastVersionType.STF
        assert stf_version.parent_version_id == existing_ltf.forecast_version_id


# --- Filtres -----------------------------------------------------------------------

def test_stf_list_filters_by_iso_year(client: TestClient, engine, reference_data, existing_ltf):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/stf/new", data={**_stf_form_payload(reference_data), "csrf_token": csrf})

    matching = client.get("/stf?iso_year=2026")
    assert "Semaine 37" in matching.text

    other_year = client.get("/stf?iso_year=2030")
    assert "Semaine 37" not in other_year.text
    assert "Aucun forecast" in other_year.text


def test_delete_stf_with_intraday_requires_and_supports_cascade(engine, reference_data, existing_ltf):
    with Session(engine) as session:
        stf = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026, iso_week=37,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                volume=44500, aht_seconds=335, occupancy_pct=86, shrinkage_pct=28,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )
        interval = IntervalForecast(
            date=date(2026, 9, 7),
            interval_start=time(10, 0),
            interval_end=time(10, 30),
            campaign_id=reference_data["campaign_id"],
            skill_id=reference_data["skill_id"],
            forecast_volume=100,
            forecast_aht_seconds=335,
            required_hc=2,
        )
        session.add(interval)
        session.commit()

        with pytest.raises(ValueError, match="Daily/Intraday"):
            forecast_service.delete_stf_forecast(session, stf.id, cascade=False)

        forecast_service.delete_stf_forecast(session, stf.id, cascade=True)
        assert session.get(STFForecast, stf.id) is None
        assert session.get(ForecastVersion, stf.forecast_version_id) is None
        assert session.exec(select(IntervalForecast)).first() is None
        assert session.get(LTFForecast, existing_ltf.id) is not None
