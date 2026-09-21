"""Tests d'intégration — module LTF Monthly.

Couvre le flux HTTP complet (création via formulaire, liste filtrée, détail,
RBAC) ainsi que la logique de versioning au niveau service (jamais
d'écrasement — règle §9).
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
from app.models.enums import Channel, ForecastVersionType, UserRole
from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
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


def _make_user(engine, email: str, role: UserRole) -> dict:
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password(TEST_PASSWORD),
            role=role,
            is_active=True,
            totp_secret=secret,
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


def _ltf_form_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "period": "2026-W37",
        "campaign_id": str(reference_data["campaign_id"]),
        "skill_id": str(reference_data["skill_id"]),
        "forecast_volume": "42000",
        "handling_time_seconds": "320",
        "aht_required_seconds": "310",
        "occupancy_required_pct": "85",
        "service_level_target_pct": "80",
        "asa_target_seconds": "20",
        "indoor_shrinkage_pct": "18",
        "outdoor_shrinkage_pct": "7",
        "notes": "Test",
    }
    payload.update(overrides)
    return payload


# --- Flux HTTP complet -----------------------------------------------------

def test_analyst_can_create_and_view_ltf_forecast(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])

    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/ltf/new", data={**_ltf_form_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ltf"

    list_page = client.get("/ltf")
    assert list_page.status_code == 200
    assert "Semaine 37" in list_page.text

    detail_page = client.get("/ltf/1")
    assert detail_page.status_code == 200
    assert "Headcount Required" in detail_page.text


def test_root_redirects_authenticated_user_to_dashboard(client: TestClient, engine):
    # root() redirige vers /dashboard depuis le commit 13 (avant : /ltf,
    # en attendant que le vrai Dashboard existe).
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_ltf_list_requires_login(client: TestClient):
    response = client.get("/ltf", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- RBAC --------------------------------------------------------------------

def test_viewer_cannot_access_new_ltf_form(client: TestClient, engine):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/ltf/new")
    assert response.status_code == 403


def test_viewer_cannot_submit_new_ltf(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post("/ltf/new", data={**_ltf_form_payload(reference_data), "csrf_token": csrf})
    assert response.status_code == 403


def test_viewer_can_still_view_list_without_create_button(client: TestClient, engine):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/ltf")
    assert response.status_code == 200
    assert "+ Nouveau forecast" not in response.text


def test_write_roles_are_admin_and_wfm_analyst_only():
    from app.routers.ltf import WRITE_ROLES
    assert UserRole.TEAM_LEAD not in WRITE_ROLES
    assert UserRole.VIEWER not in WRITE_ROLES
    assert UserRole.ADMIN in WRITE_ROLES
    assert UserRole.WFM_ANALYST in WRITE_ROLES


# --- Validation des entrées ----------------------------------------------------

def test_create_ltf_rejects_shrinkage_sum_over_100(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _ltf_form_payload(reference_data, indoor_shrinkage_pct="60", outdoor_shrinkage_pct="50")
    response = client.post("/ltf/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400
    assert "100" in response.text


def test_create_ltf_rejects_invalid_month(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _ltf_form_payload(reference_data, period="2026-13")
    response = client.post("/ltf/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


def test_create_ltf_without_csrf_token_is_rejected(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/ltf/new", data=_ltf_form_payload(reference_data))
    assert response.status_code == 400


# --- Filtres -------------------------------------------------------------------

def test_ltf_list_filters_by_campaign(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/ltf/new", data={**_ltf_form_payload(reference_data), "csrf_token": csrf})

    matching = client.get(f"/ltf?campaign_id={reference_data['campaign_id']}")
    assert "Semaine 37" in matching.text

    other_campaign_filter = client.get("/ltf?campaign_id=999999")
    assert "Semaine 37" not in other_campaign_filter.text
    assert "Aucun forecast" in other_campaign_filter.text


# --- Versioning (règle §9 : jamais d'écrasement) --------------------------------

def test_creating_second_ltf_for_same_period_does_not_overwrite_first(engine, reference_data):
    with Session(engine) as session:
        first = forecast_service.create_ltf_forecast(
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
        second = forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026, month=9,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                forecast_volume=45000, forecast_aht_seconds=330, aht_required_seconds=310,
                occupancy_required_pct=85, service_level_target_pct=80, asa_target_seconds=20,
                indoor_shrinkage_pct=18, outdoor_shrinkage_pct=7,
            ),
            created_by_user_id=None,
        )

        assert first.id != second.id

        all_ltf = session.exec(select(LTFForecast)).all()
        assert len(all_ltf) == 2
        first_reloaded = session.get(LTFForecast, first.id)
        assert first_reloaded.forecast_volume == 42000

        first_version = session.get(ForecastVersion, first.forecast_version_id)
        second_version = session.get(ForecastVersion, second.forecast_version_id)
        assert first_version.is_current is False
        assert second_version.is_current is True

        current = forecast_service.list_current_ltf_forecasts(session, year=2026)
        assert len(current) == 1
        assert current[0].forecast_volume == 45000

        history = forecast_service.get_ltf_version_history(
            session,
            campaign_id=reference_data["campaign_id"],
            skill_id=reference_data["skill_id"],
            year=2026, month=9,
        )
        assert len(history) == 2


def test_ltf_version_type_is_always_ltf(engine, reference_data):
    with Session(engine) as session:
        ltf = forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026, month=9,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                forecast_volume=1000, forecast_aht_seconds=300, aht_required_seconds=300,
                occupancy_required_pct=85, service_level_target_pct=80, asa_target_seconds=20,
                indoor_shrinkage_pct=10, outdoor_shrinkage_pct=5,
            ),
            created_by_user_id=None,
        )
        version = session.get(ForecastVersion, ltf.forecast_version_id)
        assert version.version_type == ForecastVersionType.LTF


# --- Cohérence mathématique du pipeline de calcul --------------------------------

def test_create_ltf_forecast_pipeline_is_internally_consistent(engine, reference_data):
    """productive_hours x occupancy% doit retomber exactement sur workload_hours
    (Volume x AHT) — sinon required_hc_aggregate et productive_hours auraient
    ete calcules de facon incoherente entre eux."""
    with Session(engine) as session:
        ltf = forecast_service.create_ltf_forecast(
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
        workload_hours = (42000 * 320) / 3600
        assert ltf.productive_hours * 0.85 == pytest.approx(workload_hours, rel=0.001)
        assert ltf.total_shrinkage_pct == pytest.approx(25.0)
        assert ltf.production_hours == pytest.approx(workload_hours, rel=0.001)
        # staffing_gap et overtime restent a 0 : domaine des commits 09/11.
        assert ltf.staffing_gap == 0.0
        assert ltf.overtime_required_hours == 0.0


def test_delete_ltf_with_dependent_stf_requires_and_supports_cascade(engine, reference_data):
    with Session(engine) as session:
        ltf = forecast_service.create_ltf_forecast(
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

        with pytest.raises(ValueError, match="STF"):
            forecast_service.delete_ltf_forecast(session, ltf.id, cascade=False)

        forecast_service.delete_ltf_forecast(session, ltf.id, cascade=True)
        assert session.get(LTFForecast, ltf.id) is None
        assert session.get(STFForecast, stf.id) is None
        assert session.get(ForecastVersion, ltf.forecast_version_id) is None
        assert session.get(ForecastVersion, stf.forecast_version_id) is None
