"""Tests d'intégration — module Shrinkage.

Couvre l'enregistrement, le calcul du résumé (Paid Hours basé sur
l'effectif actif du skill, pas le HC théorique d'un forecast), la
répartition par catégorie, et le RBAC (team_lead peut enregistrer, comme
pour les actuals Daily/Intraday).
"""

from datetime import date

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app, bootstrap_shrinkage_categories
from app.models.campaign import Campaign
from app.models.employee import Employee, EmployeeSkill
from app.models.enums import Channel, EmployeeStatus, ShrinkageType, UserRole
from app.models.skill import Skill
from app.models.shrinkage import ShrinkageCategory
from app.models.user import User
from app.schemas.shrinkage import ShrinkageRecordInput
from app.services import shrinkage_service

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
    """Campagne + skill + 2 employés actifs rattachés (pour un calcul de
    Paid Hours prévisible : 2 employés x 8h x jours ouvrés)."""
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
        for i in range(2):
            emp = Employee(
                employee_code=f"EMP00{i}", first_name=f"Prenom{i}", last_name="Nom",
                campaign_id=campaign.id, hire_date=date(2025, 1, 1), status=EmployeeStatus.ACTIVE,
            )
            session.add(emp)
            session.commit()
            session.refresh(emp)
            session.add(EmployeeSkill(employee_id=emp.id, skill_id=skill.id, is_primary=True))
            employee_ids.append(emp.id)
        session.commit()

        categories = {c.code: c.id for c in session.exec(select(ShrinkageCategory)).all()}

        return {
            "campaign_id": campaign.id, "skill_id": skill.id,
            "employee_ids": employee_ids, "categories": categories,
        }


def _make_user(engine, email: str, role: UserRole) -> dict:
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(email=email, hashed_password=hash_password(TEST_PASSWORD), role=role, is_active=True, totp_secret=secret)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"email": user.email, "secret": secret}


def _login(client: TestClient, email: str, secret: str) -> None:
    client.get("/login")
    csrf = client.cookies.get("csrf_token")
    client.post("/login", data={"email": email, "password": TEST_PASSWORD, "csrf_token": csrf}, follow_redirects=False)
    client.get("/login/verify")
    csrf2 = client.cookies.get("csrf_token")
    client.post("/login/verify", data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf2}, follow_redirects=False)


def _record_payload(reference_data: dict, **overrides) -> dict:
    payload = {
        "employee_id": str(reference_data["employee_ids"][0]),
        "category_id": str(reference_data["categories"]["BREAK"]),
        "record_date": "2026-09-08",  # mardi
        "hours": "1.0",
        "campaign_id": str(reference_data["campaign_id"]),
        "skill_id": str(reference_data["skill_id"]),
        "notes": "Test",
    }
    payload.update(overrides)
    return payload


# --- Enregistrement --------------------------------------------------------------

def test_team_lead_can_record_shrinkage(client: TestClient, engine, reference_data):
    user = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    response = client.post(
        "/shrinkage/new", data={**_record_payload(reference_data), "csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303


def test_recorded_shrinkage_appears_in_report(client: TestClient, engine, reference_data):
    user = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    client.post("/shrinkage/new", data={**_record_payload(reference_data), "csrf_token": csrf})

    report = client.get(
        f"/shrinkage?start_date=2026-09-07&end_date=2026-09-13&skill_id={reference_data['skill_id']}"
    )
    assert report.status_code == 200
    assert "Test" in report.text  # la note
    assert "BREAK" in report.text


def test_viewer_cannot_record_shrinkage(client: TestClient, engine, reference_data):
    user = _make_user(engine, "viewer@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])
    response = client.get("/shrinkage/new")
    assert response.status_code == 403


def test_shrinkage_report_requires_login(client: TestClient):
    response = client.get("/shrinkage", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- Calcul du résumé --------------------------------------------------------------

def test_summary_paid_hours_based_on_active_employee_count(engine, reference_data):
    """2 employes actifs x 8h x 5 jours ouvres (semaine du 7 au 13 sept
    2026 inclut un week-end) = 80h de Paid Hours."""
    with Session(engine) as session:
        shrinkage_service.record_shrinkage(session, ShrinkageRecordInput(
            employee_id=reference_data["employee_ids"][0],
            category_id=reference_data["categories"]["BREAK"],
            record_date=date(2026, 9, 8), hours=2.0,
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        ))
        shrinkage_service.record_shrinkage(session, ShrinkageRecordInput(
            employee_id=reference_data["employee_ids"][1],
            category_id=reference_data["categories"]["LEAVE"],
            record_date=date(2026, 9, 9), hours=8.0,
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        ))

        records = shrinkage_service.list_shrinkage_records(
            session, start_date=date(2026, 9, 7), end_date=date(2026, 9, 13), skill_id=reference_data["skill_id"]
        )
        categories = shrinkage_service.list_active_categories(session)
        summary = shrinkage_service.compute_shrinkage_summary(
            session, records, categories, skill_id=reference_data["skill_id"],
            start_date=date(2026, 9, 7), end_date=date(2026, 9, 13),
        )

        assert summary.paid_hours == pytest.approx(80.0)  # 2 x 8 x 5
        assert summary.indoor_hours == pytest.approx(2.0)
        assert summary.outdoor_hours == pytest.approx(8.0)
        assert summary.total_hours == pytest.approx(10.0)
        assert summary.total_pct == pytest.approx(10.0 / 80.0 * 100)
        assert summary.available_hours == pytest.approx(70.0)
        assert summary.by_category_hours["BREAK"] == pytest.approx(2.0)
        assert summary.by_category_hours["LEAVE"] == pytest.approx(8.0)


def test_summary_only_counts_employees_linked_to_the_skill(engine, reference_data):
    """Un employe non rattache au skill (pas d'EmployeeSkill) ne doit pas
    compter dans le Paid Hours, meme s'il appartient a la meme campagne."""
    with Session(engine) as session:
        outsider = Employee(
            employee_code="EMPOUT", first_name="Horsdu", last_name="Skill",
            campaign_id=reference_data["campaign_id"], hire_date=date(2025, 1, 1), status=EmployeeStatus.ACTIVE,
        )
        session.add(outsider)
        session.commit()

        records = shrinkage_service.list_shrinkage_records(
            session, start_date=date(2026, 9, 7), end_date=date(2026, 9, 13), skill_id=reference_data["skill_id"]
        )
        categories = shrinkage_service.list_active_categories(session)
        summary = shrinkage_service.compute_shrinkage_summary(
            session, records, categories, skill_id=reference_data["skill_id"],
            start_date=date(2026, 9, 7), end_date=date(2026, 9, 13),
        )
        # Toujours 2 employes rattaches (l'outsider n'a pas d'EmployeeSkill) -> 80h.
        assert summary.paid_hours == pytest.approx(80.0)


def test_report_without_skill_filter_shows_no_summary(client: TestClient, engine, reference_data):
    user = _make_user(engine, "analyst@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    response = client.get("/shrinkage?start_date=2026-09-07&end_date=2026-09-13")
    assert response.status_code == 200
    assert "Choisissez un skill" in response.text


# --- CSRF / validation ----------------------------------------------------------

def test_record_without_csrf_is_rejected(client: TestClient, engine, reference_data):
    user = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(client, user["email"], user["secret"])
    response = client.post("/shrinkage/new", data=_record_payload(reference_data))
    assert response.status_code == 400


def test_record_rejects_more_than_24_hours(client: TestClient, engine, reference_data):
    user = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _record_payload(reference_data, hours="30")
    response = client.post("/shrinkage/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


def test_record_rejects_zero_hours(client: TestClient, engine, reference_data):
    user = _make_user(engine, "teamlead@wfm.local", UserRole.TEAM_LEAD)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")
    payload = _record_payload(reference_data, hours="0")
    response = client.post("/shrinkage/new", data={**payload, "csrf_token": csrf})
    assert response.status_code == 400


def test_multiple_records_same_employee_same_day_allowed(engine, reference_data):
    """Contrairement au LTF/STF/Capacity, aucune contrainte d'unicite -
    un employe peut avoir plusieurs occurrences le meme jour (pause ET reunion)."""
    with Session(engine) as session:
        shrinkage_service.record_shrinkage(session, ShrinkageRecordInput(
            employee_id=reference_data["employee_ids"][0],
            category_id=reference_data["categories"]["BREAK"],
            record_date=date(2026, 9, 8), hours=1.0,
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        ))
        shrinkage_service.record_shrinkage(session, ShrinkageRecordInput(
            employee_id=reference_data["employee_ids"][0],
            category_id=reference_data["categories"]["MEETING"],
            record_date=date(2026, 9, 8), hours=2.0,
            campaign_id=reference_data["campaign_id"], skill_id=reference_data["skill_id"],
        ))
        records = shrinkage_service.list_shrinkage_records(
            session, start_date=date(2026, 9, 8), end_date=date(2026, 9, 8)
        )
        assert len(records) == 2
