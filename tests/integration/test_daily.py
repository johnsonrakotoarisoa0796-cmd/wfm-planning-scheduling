"""Tests d'intégration — module Daily/Intraday.

Couvre le flux HTTP complet (génération, vue, édition d'intervalle), le
blocage de régénération, et le RBAC (team_lead peut modifier les actuals
mais pas générer une journée).
"""

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.campaign import Campaign
from app.models.enums import Channel, UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.intraday import GenerateIntradayInput, IntervalUpdateInput
from app.services import intraday_service

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


def _day_form_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "target_date": "2026-09-15",
        "campaign_id": str(reference_data["campaign_id"]),
        "skill_id": str(reference_data["skill_id"]),
        "daily_volume": "2000",
        "daily_aht_seconds": "300",
        "service_level_target_pct": "80",
        "answer_time_target_seconds": "20",
        "occupancy_target_pct": "85",
        "shrinkage_pct": "25",
    }
    payload.update(overrides)
    return payload


# --- Génération --------------------------------------------------------------

def test_analyst_can_generate_and_view_day(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")

    response = client.post(
        "/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "/daily/view" in response.headers["location"]

    view = client.get(response.headers["location"])
    assert view.status_code == 200
    # 48 intervalles generes -> 48 liens "Modifier" dans le tableau.
    assert view.text.count("Modifier") == 48


def test_required_hc_varies_with_traffic_across_intervals(engine, reference_data):
    """Verification directe (niveau service) que le required_hc au pic est
    bien superieur a celui de la nuit - la preuve qu'Erlang C tourne
    reellement intervalle par intervalle, pas une valeur plate copiee 48 fois."""
    with Session(engine) as session:
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date="2026-09-15", **reference_data,
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        required_hcs = {i.required_hc for i in intervals}
        assert len(required_hcs) > 1  # pas une seule valeur plate
        peak = max(intervals, key=lambda i: i.forecast_volume)
        trough = min(intervals, key=lambda i: i.forecast_volume)
        assert peak.required_hc > trough.required_hc


def test_generated_intervals_sum_to_daily_volume(engine, reference_data):
    with Session(engine) as session:
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date="2026-09-15", **reference_data,
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        total = sum(i.forecast_volume for i in intervals)
        assert total == pytest.approx(2000, rel=0.001)


def test_regenerating_same_day_is_blocked(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf})

    csrf2 = client.cookies.get("csrf_token")
    response = client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf2})
    assert response.status_code == 400
    assert "existent déjà" in response.text or "existent deja" in response.text


# --- Édition d'intervalle (actuals) --------------------------------------------

def test_editing_interval_records_actuals_and_computes_estimates(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf})

    with Session(engine) as session:
        from app.models.intraday import IntervalForecast
        from sqlmodel import select
        first_interval = session.exec(select(IntervalForecast)).first()
        interval_id = first_interval.id

    csrf2 = client.cookies.get("csrf_token")
    response = client.post(
        f"/daily/interval/{interval_id}/edit",
        data={
            "csrf_token": csrf2, "scheduled_hc": "29",
            "actual_volume": "125", "actual_aht_seconds": "310", "actual_hc": "27",
            "abandoned_contacts": "6",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        updated = session.get(IntervalForecast, interval_id)
        assert updated.scheduled_hc == 29
        assert updated.actual_volume == 125
        assert updated.service_level_pct is not None
        assert updated.occupancy_pct is not None
        assert updated.abandon_rate_pct == pytest.approx(6 / 125 * 100)
        # Gap = actual_hc - required_hc (peut etre negatif si sous-staffe).
        assert updated.staffing_gap == pytest.approx(27 - updated.required_hc)


def test_edit_nonexistent_interval_returns_404(client: TestClient, engine):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get("/daily/interval/999999/edit")
    assert response.status_code == 404


# --- RBAC ------------------------------------------------------------------------

def test_viewer_cannot_generate_day(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/daily/new")
    assert response.status_code == 403


def test_team_lead_cannot_generate_day_but_can_edit_interval(client: TestClient, engine, reference_data):
    analyst = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, analyst["email"], analyst["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf})

    with Session(engine) as session:
        from app.models.intraday import IntervalForecast
        from sqlmodel import select
        interval_id = session.exec(select(IntervalForecast)).first().id

    team_lead_client = TestClient(app)
    team_lead = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(team_lead_client, team_lead["email"], team_lead["secret"])

    denied = team_lead_client.get("/daily/new")
    assert denied.status_code == 403

    allowed = team_lead_client.get(f"/daily/interval/{interval_id}/edit")
    assert allowed.status_code == 200


def test_viewer_cannot_edit_interval(client: TestClient, engine, reference_data):
    analyst = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, analyst["email"], analyst["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf})

    with Session(engine) as session:
        from app.models.intraday import IntervalForecast
        from sqlmodel import select
        interval_id = session.exec(select(IntervalForecast)).first().id

    viewer_client = TestClient(app)
    viewer = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(viewer_client, viewer["email"], viewer["secret"])
    response = viewer_client.get(f"/daily/interval/{interval_id}/edit")
    assert response.status_code == 403


# --- CSRF / validation ----------------------------------------------------------

def test_create_day_without_csrf_is_rejected(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/daily/new", data=_day_form_payload(reference_data))
    assert response.status_code == 400


def test_create_day_rejects_invalid_shrinkage(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _day_form_payload(reference_data, shrinkage_pct="150")
    response = client.post("/daily/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


# --- Résumé journalier / liste -----------------------------------------------------

def test_daily_summary_reflects_actuals(engine, reference_data):
    with Session(engine) as session:
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date="2026-09-15", **reference_data,
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        summary_before = intraday_service.compute_daily_summary(intervals)
        assert summary_before.actual_volume is None  # aucun actual saisi

        intraday_service.update_interval(
            session, interval_id=intervals[0].id,
            data=IntervalUpdateInput(actual_volume=100, actual_aht_seconds=300, actual_hc=10),
        )
        refreshed = intraday_service.list_intervals_for_day(
            session, target_date="2026-09-15",
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        summary_after = intraday_service.compute_daily_summary(refreshed)
        assert summary_after.actual_volume == 100


def test_list_days_groups_by_date_campaign_skill(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/daily/new", data={**_day_form_payload(reference_data), "csrf_token": csrf})

    response = client.get("/daily")
    assert response.status_code == 200
    assert "2026-09-15" in response.text
