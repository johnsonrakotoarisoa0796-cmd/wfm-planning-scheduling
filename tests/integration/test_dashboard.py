"""Tests d'intégration — Dashboard (§5).

Vérifie que le service assemble correctement les données déjà produites
par les autres modules (aucun nouveau calcul), et que les sections
optionnelles (KPI actuals, capacity) apparaissent/disparaissent selon ce
qui a été saisi ailleurs.
"""

from datetime import date

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app, bootstrap_shrinkage_categories
from app.models.campaign import Campaign
from app.models.enums import Channel, UserRole
from app.models.skill import Skill
from app.models.user import User
from app.schemas.capacity import CapacityPlanInput
from app.schemas.intraday import GenerateIntradayInput, IntervalUpdateInput
from app.schemas.ltf import LTFCreateInput
from app.services import capacity_service, dashboard_service, forecast_service, intraday_service

TEST_PASSWORD = "mot-de-passe-solide-123"


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    bootstrap_shrinkage_categories(db_engine=engine)
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


def test_dashboard_requires_login(client: TestClient):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_without_ltf_or_intervals_shows_warnings(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get(
        f"/dashboard?target_date=2026-09-15&campaign_id={reference_data['campaign_id']}&skill_id={reference_data['skill_id']}"
    )
    assert response.status_code == 200
    assert "Aucun LTF actif" in response.text
    assert "Aucun intervalle" in response.text


# --- build_dashboard() : assemblage correct -----------------------------------------

def test_dashboard_prefers_weekly_ltf_for_selected_date(engine, reference_data):
    with Session(engine) as session:
        forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                iso_year=2026, iso_week=38,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                forecast_volume=12000, forecast_aht_seconds=300, aht_required_seconds=290,
                occupancy_required_pct=85, service_level_target_pct=80, asa_target_seconds=20,
                indoor_shrinkage_pct=10, outdoor_shrinkage_pct=5,
            ),
            created_by_user_id=None,
        )
        data = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert data.has_ltf is True
        assert data.monthly_paid_hours is not None


def test_dashboard_data_with_only_ltf_no_intervals(engine, reference_data):
    with Session(engine) as session:
        forecast_service.create_ltf_forecast(
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
        data = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert data.has_ltf is True
        assert data.has_intervals is False
        assert data.kpi_rows == []  # pas d'intervalles -> pas de SL/Occupancy/AHT/ASA
        assert data.monthly_paid_hours is not None  # vient du LTF, dispo sans intervalles


def test_dashboard_kpi_rows_appear_once_actuals_recorded(engine, reference_data):
    with Session(engine) as session:
        forecast_service.create_ltf_forecast(
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
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date=date(2026, 9, 15), campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )

        # Sans actuals : has_intervals True mais pas de lignes KPI (rien a moyenner).
        data_before = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert data_before.has_intervals is True
        assert data_before.kpi_rows == []

        for interval in intervals:
            intraday_service.update_interval(
                session, interval_id=interval.id,
                data=IntervalUpdateInput(
                    scheduled_hc=round(interval.required_hc * 0.9, 1),
                    actual_volume=max(interval.forecast_volume, 1),
                    actual_aht_seconds=310, actual_hc=round(interval.required_hc * 0.85, 1),
                ),
            )

        data_after = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        labels = {row.label for row in data_after.kpi_rows}
        assert {"Service Level", "Occupancy", "AHT", "ASA"}.issubset(labels)
        assert data_after.forecast_accuracy_pct is not None
        assert data_after.staffing.actual_hc is not None
        assert data_after.staffing.gap is not None


def test_dashboard_capacity_snapshot_appears_when_plan_exists(engine, reference_data):
    with Session(engine) as session:
        forecast_service.create_ltf_forecast(
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

        data_before = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert data_before.capacity is None

        capacity_service.upsert_capacity_plan(
            session,
            CapacityPlanInput(
                period="2026-09", campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                current_hc=30, hiring=3, transfers_in=0, transfers_out=1, attrition_pct=4, absenteeism_pct=2,
            ),
            created_by_user_id=None,
        )

        data_after = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert data_after.capacity is not None
        assert data_after.capacity.current_hc == 30


def test_dashboard_kpi_status_reflects_target_gap(engine, reference_data):
    """Un Service Level tres en-dessous de la cible doit ressortir en
    'critical', pas juste affiche sans jugement (§5 : vert/orange/rouge)."""
    with Session(engine) as session:
        forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026, month=9,
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                forecast_volume=42000, forecast_aht_seconds=320, aht_required_seconds=310,
                occupancy_required_pct=85, service_level_target_pct=95, asa_target_seconds=20,
                indoor_shrinkage_pct=18, outdoor_shrinkage_pct=7,
            ),
            created_by_user_id=None,
        )
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date=date(2026, 9, 15), campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=95, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        # Sous-staffe severement -> service level reel tres bas.
        for interval in intervals:
            intraday_service.update_interval(
                session, interval_id=interval.id,
                data=IntervalUpdateInput(
                    actual_volume=max(interval.forecast_volume, 1), actual_aht_seconds=310,
                    actual_hc=max(round(interval.required_hc * 0.3, 1), 1),
                ),
            )

        data = dashboard_service.build_dashboard(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        sl_row = next(row for row in data.kpi_rows if row.label == "Service Level")
        assert sl_row.status == "critical"


# --- Racine -------------------------------------------------------------------------

def test_root_redirects_to_dashboard(client: TestClient, engine):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
