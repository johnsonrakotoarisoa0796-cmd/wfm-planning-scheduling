"""Tests d'intégration — module Overtime.

Couvre le calcul Required/Available/Gap/OT depuis les intervalles Daily/
Intraday, l'upsert (pas de versioning), la distinction stricte Required/
Actual (§30), et le RBAC (team_lead peut saisir l'Actual OT mais pas créer
un plan).
"""

from datetime import date

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.campaign import Campaign
from app.models.enums import Channel, PeriodType, UserRole
from app.models.overtime import OvertimePlan
from app.models.skill import Skill
from app.models.user import User
from app.schemas.intraday import GenerateIntradayInput, IntervalUpdateInput
from app.schemas.overtime import OvertimeActualInput, OvertimePlanInput
from app.services import intraday_service, kpi_service, overtime_service

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
def understaffed_day(engine, reference_data):
    """Génère une journée d'intervalles où scheduled_hc = 80% du
    required_hc partout — garantit un OT Required > 0 prévisible.

    Retourne des tuples (required_hc, scheduled_hc) en valeurs simples,
    pas les objets ORM (qui seraient détachés une fois la session fermée)."""
    with Session(engine) as session:
        intervals = intraday_service.generate_intraday_forecast(
            session,
            GenerateIntradayInput(
                target_date=date(2026, 9, 15), campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        for interval in intervals:
            intraday_service.update_interval(
                session, interval_id=interval.id,
                data=IntervalUpdateInput(scheduled_hc=round(interval.required_hc * 0.8, 2)),
            )
        return [(i.required_hc, round(i.required_hc * 0.8, 2)) for i in intervals]


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


def _overtime_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "start_date": "2026-09-15", "end_date": "2026-09-15",
        "campaign_id": str(reference_data["campaign_id"]), "skill_id": str(reference_data["skill_id"]),
        "period_type": "daily", "notes": "Test",
    }
    payload.update(overrides)
    return payload


# --- Calcul depuis Daily/Intraday ------------------------------------------------

def test_report_computes_required_and_available_from_intervals(engine, reference_data, understaffed_day):
    with Session(engine) as session:
        report = overtime_service.compute_overtime_report(
            session, start_date=date(2026, 9, 15), end_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        expected_required = sum(required for required, _ in understaffed_day) * 0.5
        expected_available = sum(scheduled for _, scheduled in understaffed_day) * 0.5
        assert report.required_hours == pytest.approx(expected_required)
        assert report.available_hours == pytest.approx(expected_available)
        assert report.ot_required_hours == pytest.approx(kpi_service.overtime_required_hours(expected_required, expected_available))
        assert report.ot_required_hours > 0  # sous-staffe a 80% -> OT necessaire


def test_report_with_no_intervals_returns_zero_not_error(engine, reference_data):
    with Session(engine) as session:
        report = overtime_service.compute_overtime_report(
            session, start_date=date(2099, 1, 1), end_date=date(2099, 1, 1),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert report.required_hours == 0.0
        assert report.ot_required_hours == 0.0
        assert report.daily_breakdown == []


def test_daily_breakdown_has_one_point_per_day_with_data(engine, reference_data, understaffed_day):
    with Session(engine) as session:
        report = overtime_service.compute_overtime_report(
            session, start_date=date(2026, 9, 14), end_date=date(2026, 9, 16),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert len(report.daily_breakdown) == 1
        assert report.daily_breakdown[0].day == date(2026, 9, 15)


# --- Flux HTTP complet -------------------------------------------------------------

def test_analyst_can_create_and_view_overtime_plan(client: TestClient, engine, reference_data, understaffed_day):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")

    response = client.post(
        "/overtime/new", data={**_overtime_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/overtime/1"

    detail = client.get("/overtime/1")
    assert detail.status_code == 200
    assert "OT Required" in detail.text
    assert "Pas encore saisi" in detail.text  # ot_actual_hours pas encore renseigne


# --- Upsert (pas de versioning) --------------------------------------------------

def test_resaving_same_period_updates_in_place(engine, reference_data, understaffed_day):
    with Session(engine) as session:
        first = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 15), end_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.DAILY,
            ),
        )
        second = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 15), end_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.DAILY, notes="Mis a jour",
            ),
        )
        assert first.id == second.id
        all_plans = session.exec(select(OvertimePlan)).all()
        assert len(all_plans) == 1
        assert all_plans[0].notes == "Mis a jour"


def test_period_key_derivation_for_each_type(engine, reference_data, understaffed_day):
    with Session(engine) as session:
        daily_plan = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 15), end_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.DAILY,
            ),
        )
        weekly_plan = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 14), end_date=date(2026, 9, 20),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.WEEKLY,
            ),
        )
        monthly_plan = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.MONTHLY,
            ),
        )
        assert daily_plan.period_key == "2026-09-15"
        assert weekly_plan.period_key == "2026-W38"
        assert monthly_plan.period_key == "2026-09"
        # Trois plans distincts malgre le meme campaign/skill : granularites differentes.
        assert len({daily_plan.id, weekly_plan.id, monthly_plan.id}) == 3


# --- Required vs Actual (§30) --------------------------------------------------------

def test_actual_ot_never_modifies_required(engine, reference_data, understaffed_day):
    with Session(engine) as session:
        plan = overtime_service.upsert_overtime_plan(
            session, OvertimePlanInput(
                start_date=date(2026, 9, 15), end_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                period_type=PeriodType.DAILY,
            ),
        )
        required_before = plan.required_hours
        ot_required_before = plan.ot_required_hours

        updated = overtime_service.update_actual_ot(
            session, plan_id=plan.id, data=OvertimeActualInput(ot_actual_hours=999)
        )
        assert updated.ot_actual_hours == 999
        assert updated.required_hours == required_before
        assert updated.ot_required_hours == ot_required_before


def test_overtime_variance_computed_correctly(client: TestClient, engine, reference_data, understaffed_day):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/overtime/new", data={**_overtime_payload(reference_data), "csrf_token": csrf})

    csrf2 = client.cookies.get("csrf_token")
    client.post("/overtime/1/actual", data={"csrf_token": csrf2, "ot_actual_hours": "5"})

    with Session(engine) as session:
        plan = session.get(OvertimePlan, 1)
        expected_variance = kpi_service.overtime_variance(plan.ot_required_hours, 5)
        assert kpi_service.overtime_variance(plan.ot_required_hours, plan.ot_actual_hours) == pytest.approx(expected_variance)


# --- RBAC ------------------------------------------------------------------------

def test_viewer_cannot_create_overtime_plan(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/overtime/new")
    assert response.status_code == 403


def test_team_lead_cannot_create_but_can_enter_actual(client: TestClient, engine, reference_data, understaffed_day):
    analyst = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, analyst["email"], analyst["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/overtime/new", data={**_overtime_payload(reference_data), "csrf_token": csrf})

    team_lead_client = TestClient(app)
    team_lead = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(team_lead_client, team_lead["email"], team_lead["secret"])

    denied = team_lead_client.get("/overtime/new")
    assert denied.status_code == 403

    csrf2 = team_lead_client.cookies.get("csrf_token")
    allowed = team_lead_client.post(
        "/overtime/1/actual", data={"csrf_token": csrf2, "ot_actual_hours": "10"}, follow_redirects=False
    )
    assert allowed.status_code == 303


def test_viewer_cannot_enter_actual_ot(client: TestClient, engine, reference_data, understaffed_day):
    analyst = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, analyst["email"], analyst["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/overtime/new", data={**_overtime_payload(reference_data), "csrf_token": csrf})

    viewer_client = TestClient(app)
    viewer = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(viewer_client, viewer["email"], viewer["secret"])
    csrf2 = viewer_client.cookies.get("csrf_token")
    response = viewer_client.post("/overtime/1/actual", data={"csrf_token": csrf2, "ot_actual_hours": "10"})
    assert response.status_code == 403


# --- CSRF ------------------------------------------------------------------------

def test_create_overtime_without_csrf_is_rejected(client: TestClient, engine, reference_data, understaffed_day):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/overtime/new", data=_overtime_payload(reference_data))
    assert response.status_code == 400
