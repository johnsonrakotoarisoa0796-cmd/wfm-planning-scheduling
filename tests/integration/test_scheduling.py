"""Tests d'intégration — module Scheduling.

Couvre l'upsert d'affectation (un agent = un planning par jour), le
calcul d'impact des pauses avec de vraies affectations (y compris le
scénario dramatique où plusieurs agents partent en pause en même temps),
et le RBAC.
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
from app.models.employee import Employee, EmployeeSkill, EmployeeAbsence
from app.models.enums import Channel, EmployeeStatus, UserRole
from app.models.schedule import ScheduleEntry
from app.models.skill import Skill
from app.models.user import User
from app.schemas.scheduling import ScheduleEntryInput, ShiftInput
from app.services import auto_scheduler_service, intraday_service, scheduling_service
from app.schemas.intraday import GenerateIntradayInput

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

        employee_ids = []
        for i in range(3):
            emp = Employee(
                employee_code=f"EMP00{i}", first_name=f"Prenom{i}", last_name="Nom",
                campaign_id=campaign.id, hire_date=date(2025, 1, 1), status=EmployeeStatus.ACTIVE,
            )
            session.add(emp)
            session.commit()
            session.refresh(emp)
            session.add(EmployeeSkill(employee_id=emp.id, skill_id=skill.id, is_primary=(i == 0)))
            session.commit()
            employee_ids.append(emp.id)

        shift = scheduling_service.create_shift(
            session, ShiftInput(name="Matin", start_time=time(9, 0), end_time=time(18, 0), break_minutes=15, lunch_minutes=60)
        )

        return {
            "campaign_id": campaign.id, "skill_id": skill.id,
            "employee_ids": employee_ids, "shift_id": shift.id,
        }


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


def test_planner_page_renders_without_template_error(client: TestClient, engine):
    user = _make_user(engine, "admin@wfm.local", UserRole.ADMIN)
    _login(client, user["email"], user["secret"])
    response = client.get("/scheduling/planner")
    assert response.status_code == 200
    assert "Planner de staffing" in response.text
    assert "Sélectionnez une campagne et un skill" in response.text


# --- Shifts ------------------------------------------------------------------------

def test_analyst_can_create_shift(client: TestClient, engine):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/scheduling/shifts",
        data={"csrf_token": csrf, "name": "Nuit", "start_time": "17:00", "end_time": "02:00", "break_minutes": "15", "lunch_minutes": "60"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    list_page = client.get("/scheduling/shifts")
    assert "Nuit" in list_page.text


def test_viewer_cannot_create_shift(client: TestClient, engine):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/scheduling/shifts",
        data={"csrf_token": csrf, "name": "Nuit", "start_time": "17:00", "end_time": "02:00"},
    )
    assert response.status_code == 403


# --- Absences ------------------------------------------------------------------------

def test_viewer_can_view_absences_page(client: TestClient, engine):
    user = _make_user(engine, "viewer-absences@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/scheduling/absences")
    assert response.status_code == 200
    assert "Absences & congés" in response.text


def test_analyst_can_create_absence(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst-absences@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/scheduling/absences",
        data={
            "csrf_token": csrf,
            "employee_id": str(reference_data["employee_ids"][0]),
            "start_date": "2026-09-21",
            "end_date": "2026-09-23",
            "absence_type": "paid_leave",
            "paid": "true",
            "notes": "Congé annuel",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        absence = session.exec(select(EmployeeAbsence)).first()
        assert absence is not None
        assert absence.employee_id == reference_data["employee_ids"][0]
        assert absence.absence_type == "paid_leave"
        assert absence.paid is True
        assert absence.notes == "Congé annuel"

    page = client.get("/scheduling/absences")
    assert page.status_code == 200
    assert "Congé annuel" in page.text


def test_viewer_cannot_create_absence(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer-create-absence@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/scheduling/absences",
        data={
            "csrf_token": csrf,
            "employee_id": str(reference_data["employee_ids"][0]),
            "start_date": "2026-09-21",
            "end_date": "2026-09-23",
            "absence_type": "paid_leave",
            "paid": "true",
        },
    )
    assert response.status_code == 403


def test_absence_overlap_is_rejected_by_route(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst-overlap@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    first = client.post(
        "/scheduling/absences",
        data={
            "csrf_token": csrf,
            "employee_id": str(reference_data["employee_ids"][0]),
            "start_date": "2026-09-21",
            "end_date": "2026-09-23",
            "absence_type": "availability",
            "paid": "false",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303
    second = client.post(
        "/scheduling/absences",
        data={
            "csrf_token": csrf,
            "employee_id": str(reference_data["employee_ids"][0]),
            "start_date": "2026-09-22",
            "end_date": "2026-09-24",
            "absence_type": "paid_leave",
            "paid": "true",
        },
    )
    assert second.status_code == 400
    assert "Une absence existe déjà" in second.text


# --- Upsert d'affectation ------------------------------------------------------------

def test_resaving_same_employee_same_day_updates_in_place(engine, reference_data):
    with Session(engine) as session:
        first = scheduling_service.upsert_schedule_entry(
            session, ScheduleEntryInput(
                employee_id=reference_data["employee_ids"][0], entry_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                shift_id=reference_data["shift_id"],
            ),
        )
        second = scheduling_service.upsert_schedule_entry(
            session, ScheduleEntryInput(
                employee_id=reference_data["employee_ids"][0], entry_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                shift_id=reference_data["shift_id"], break_start=time(10, 0), break_end=time(10, 15),
            ),
        )
        assert first.id == second.id
        all_entries = session.exec(select(ScheduleEntry)).all()
        assert len(all_entries) == 1
        assert all_entries[0].break_start == time(10, 0)


def test_day_off_requires_no_shift(engine, reference_data):
    with Session(engine) as session:
        entry = scheduling_service.upsert_schedule_entry(
            session, ScheduleEntryInput(
                employee_id=reference_data["employee_ids"][0], entry_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                is_day_off=True,
            ),
        )
        assert entry.is_day_off is True
        assert entry.shift_id is None


def test_shift_required_unless_day_off():
    with pytest.raises(ValueError):
        ScheduleEntryInput(
            employee_id=1, entry_date=date(2026, 9, 15), campaign_id=1, skill_id=1,
            is_day_off=False, shift_id=None,
        )


# --- Impact des pauses (scénario réel) -----------------------------------------------

def test_break_impact_shows_understaffing_when_all_on_break_together(engine, reference_data):
    """Les 3 agents du meme shift partent en pause en meme temps a 10h ->
    l'intervalle 10:00-10:30 doit tomber a 0 agent disponible apres pause,
    alors qu'il y en a 3 juste avant/apres (§34)."""
    with Session(engine) as session:
        for emp_id in reference_data["employee_ids"]:
            scheduling_service.upsert_schedule_entry(
                session, ScheduleEntryInput(
                    employee_id=emp_id, entry_date=date(2026, 9, 15),
                    campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                    shift_id=reference_data["shift_id"],
                    break_start=time(10, 0), break_end=time(10, 15),
                    lunch_start=time(12, 0), lunch_end=time(13, 0),
                ),
            )

        report = scheduling_service.compute_break_impact(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        by_start = {p.interval_start: p for p in report}

        assert by_start[time(9, 30)].available_before_break == 3
        assert by_start[time(9, 30)].available_after_break == 3  # pas encore en pause

        assert by_start[time(10, 0)].available_before_break == 3
        assert by_start[time(10, 0)].available_after_break == 0  # tous en pause

        assert by_start[time(10, 30)].available_after_break == 3  # pause terminee


def test_break_impact_includes_required_hc_from_daily_forecast(engine, reference_data):
    """Si un forecast Daily/Intraday existe deja pour ce jour, le rapport
    d'impact des pauses doit reprendre son Required HC (pas 0)."""
    with Session(engine) as session:
        intraday_service.generate_intraday_forecast(
            session, GenerateIntradayInput(
                target_date=date(2026, 9, 15), campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                daily_volume=2000, daily_aht_seconds=300,
                service_level_target_pct=80, answer_time_target_seconds=20,
                occupancy_target_pct=85, shrinkage_pct=25,
            ),
        )
        report = scheduling_service.compute_break_impact(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert any(p.required_hc > 0 for p in report)


def test_break_impact_without_any_forecast_defaults_required_to_zero(engine, reference_data):
    with Session(engine) as session:
        report = scheduling_service.compute_break_impact(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert all(p.required_hc == 0.0 for p in report)


def test_day_off_employee_excluded_from_break_impact(engine, reference_data):
    with Session(engine) as session:
        scheduling_service.upsert_schedule_entry(
            session, ScheduleEntryInput(
                employee_id=reference_data["employee_ids"][0], entry_date=date(2026, 9, 15),
                campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
                is_day_off=True,
            ),
        )
        report = scheduling_service.compute_break_impact(
            session, target_date=date(2026, 9, 15),
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        )
        assert all(p.available_before_break == 0 for p in report)


# --- RBAC / CSRF ---------------------------------------------------------------------

def test_viewer_cannot_create_schedule_entry(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/scheduling/new")
    assert response.status_code == 403


def test_viewer_can_view_break_report(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/scheduling/breaks")
    assert response.status_code == 200


def test_create_schedule_entry_without_csrf_is_rejected(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.post("/scheduling/new", data={
        "employee_id": str(reference_data["employee_ids"][0]), "entry_date": "2026-09-15",
        "campaign_id": str(reference_data["campaign_id"]), "skill_id": str(reference_data["skill_id"]),
        "shift_id": str(reference_data["shift_id"]),
    })
    assert response.status_code == 400


def test_auto_scheduler_generates_week_with_breaks_and_days_off(engine, reference_data):
    from datetime import timedelta

    with Session(engine) as session:
        for employee_id in reference_data["employee_ids"]:
            session.add(EmployeeSkill(
                employee_id=employee_id,
                skill_id=reference_data["skill_id"],
                is_primary=(employee_id == reference_data["employee_ids"][0]),
            ))
        session.commit()

        monday = date(2026, 9, 14)
        for offset in range(7):
            intraday_service.generate_intraday_forecast(
                session,
                GenerateIntradayInput(
                    target_date=monday + timedelta(days=offset),
                    campaign_id=reference_data["campaign_id"],
                    skill_id=reference_data["skill_id"],
                    daily_volume=1500,
                    daily_aht_seconds=300,
                    service_level_target_pct=80,
                    answer_time_target_seconds=20,
                    occupancy_target_pct=85,
                    shrinkage_pct=10,
                ),
            )

        result = auto_scheduler_service.generate_schedule(
            session,
            week_start_date=monday,
            campaign_id=reference_data["campaign_id"],
            skill_id=reference_data["skill_id"],
        )

        assert result.entries
        work_entries = [item.entry for item in result.entries if not item.entry.is_day_off]
        assert work_entries
        assert all(entry.break2_start is not None for entry in work_entries)
        assert all(entry.lunch_start is not None for entry in work_entries)
        assert len(result.coverage) == 7

        entries = session.exec(select(ScheduleEntry)).all()
        assert len(entries) == 21
        assert {entry.date for entry in entries} == {monday + timedelta(days=i) for i in range(7)}


def test_schedule_generator_page_is_available(client: TestClient, engine):
    user = _make_user(engine, "scheduler@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get("/scheduling/generate")
    assert response.status_code == 200
    assert "Generate Schedule" in response.text
