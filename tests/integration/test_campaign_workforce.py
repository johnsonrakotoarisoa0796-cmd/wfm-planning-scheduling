"""Tests du Workforce Plan global par campagne."""
from datetime import date

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.campaign import Campaign
from app.models.campaign_workforce import CampaignWorkforcePlan
from app.models.employee import Employee
from app.models.enums import EmployeeStatus, UserRole
from app.models.user import User
from app.schemas.campaign_workforce import CampaignWorkforcePlanInput
from app.services import campaign_workforce_service


TEST_PASSWORD = "mot-de-passe-solide-123"


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        campaign = Campaign(name="Support Client FR", code="WF-FR", is_active=True)
        session.add(campaign)
        session.commit()
        session.refresh(campaign)
        for idx in range(3):
            session.add(
                Employee(
                    employee_code=f"WF{idx + 1:03d}",
                    first_name=f"Agent{idx + 1}",
                    last_name="Test",
                    campaign_id=campaign.id,
                    hire_date=date(2026, 1, 1),
                    status=EmployeeStatus.ACTIVE,
                    weekly_hours_contract=40,
                )
            )
        session.commit()
        return campaign.id


def _make_user(engine, email: str, role: UserRole):
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
        return {"email": email, "secret": secret}


def _login(client: TestClient, email: str, secret: str):
    client.get("/login")
    csrf = client.cookies.get("csrf_token")
    client.post(
        "/login",
        data={
            "email": email,
            "password": TEST_PASSWORD,
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    client.get("/login/verify")
    csrf2 = client.cookies.get("csrf_token")
    client.post(
        "/login/verify",
        data={
            "code": pyotp.TOTP(secret).now(),
            "csrf_token": csrf2,
        },
        follow_redirects=False,
    )


def test_service_computes_available_and_projected_headcount(engine, reference_data):
    with Session(engine) as session:
        plan = campaign_workforce_service.upsert_plan(
            session,
            CampaignWorkforcePlanInput(
                period="2026-09",
                campaign_id=reference_data,
                current_hc=20,
                available_hc=18,
                long_leave_hc=2,
                training_hc=2,
                nesting_hc=1,
                other_unavailable_hc=1,
                attrition_pct=5,
                hiring_hc=4,
                transfers_in_hc=1,
                transfers_out_hc=2,
                required_hc=19,
                notes="Test",
            ),
            created_by_user_id=None,
        )
        metrics = campaign_workforce_service.calculate_metrics(plan)

        assert metrics.production_available_hc == pytest.approx(14)
        assert metrics.attrition_hc == pytest.approx(1)
        assert metrics.projected_hc == pytest.approx(22)
        assert metrics.projected_production_hc == pytest.approx(16)
        assert metrics.projected_gap_hc == pytest.approx(-3)


def test_upsert_same_campaign_and_period_updates_same_row(engine, reference_data):
    with Session(engine) as session:
        first = campaign_workforce_service.upsert_plan(
            session,
            CampaignWorkforcePlanInput(
                period="2026-09",
                campaign_id=reference_data,
                current_hc=20,
                available_hc=18,
                long_leave_hc=2,
                training_hc=0,
                nesting_hc=0,
                other_unavailable_hc=0,
                attrition_pct=3,
                hiring_hc=0,
                transfers_in_hc=0,
                transfers_out_hc=0,
                required_hc=18,
            ),
            created_by_user_id=None,
        )
        second = campaign_workforce_service.upsert_plan(
            session,
            CampaignWorkforcePlanInput(
                period="2026-09",
                campaign_id=reference_data,
                current_hc=21,
                available_hc=19,
                long_leave_hc=1,
                training_hc=1,
                nesting_hc=1,
                other_unavailable_hc=0,
                attrition_pct=2,
                hiring_hc=2,
                transfers_in_hc=0,
                transfers_out_hc=1,
                required_hc=20,
            ),
            created_by_user_id=None,
        )

        assert first.id == second.id
        assert session.get(CampaignWorkforcePlan, first.id).current_hc == 21


def test_campaign_workforce_page_prefills_roster(client, engine, reference_data):
    user = _make_user(engine, "analyst-workforce@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])

    response = client.get(f"/campaigns/{reference_data}/workforce?period=2026-09")

    assert response.status_code == 200
    assert "Roster actif" in response.text
    assert "Current HC / nombre d'agents" in response.text
    assert "Long leave / longue absence" in response.text
    assert "Attrition prévue" in response.text


def test_campaign_workforce_post_saves_plan(client, engine, reference_data):
    user = _make_user(engine, "analyst-save@wfm.local", UserRole.WFM_ANALYST)
    _login(client, user["email"], user["secret"])
    csrf = client.cookies.get("csrf_token")

    response = client.post(
        f"/campaigns/{reference_data}/workforce",
        data={
            "csrf_token": csrf,
            "period": "2026-09",
            "current_hc": "20",
            "available_hc": "18",
            "long_leave_hc": "2",
            "training_hc": "1",
            "nesting_hc": "1",
            "other_unavailable_hc": "0",
            "attrition_pct": "5",
            "hiring_hc": "3",
            "transfers_in_hc": "1",
            "transfers_out_hc": "1",
            "required_hc": "19",
            "notes": "Départs confirmés",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "saved=1" in response.headers["location"]

    with Session(engine) as session:
        plan = session.get(CampaignWorkforcePlan, 1)
        assert plan is not None
        assert plan.available_hc == 18
        assert plan.attrition_pct == 5
        assert plan.long_leave_hc == 2


def test_workforce_rejects_available_hc_above_current_hc(engine, reference_data):
    with Session(engine) as session:
        with pytest.raises(ValueError, match="disponibles"):
            campaign_workforce_service.upsert_plan(
                session,
                CampaignWorkforcePlanInput(
                    period="2026-09",
                    campaign_id=reference_data,
                    current_hc=10,
                    available_hc=11,
                    long_leave_hc=0,
                    training_hc=0,
                    nesting_hc=0,
                    other_unavailable_hc=0,
                    attrition_pct=0,
                    hiring_hc=0,
                    transfers_in_hc=0,
                    transfers_out_hc=0,
                    required_hc=0,
                ),
                created_by_user_id=None,
            )


def test_viewer_cannot_edit_workforce(client, engine, reference_data):
    user = _make_user(engine, "viewer-workforce@wfm.local", UserRole.VIEWER)
    _login(client, user["email"], user["secret"])

    response = client.get(f"/campaigns/{reference_data}/workforce")

    assert response.status_code == 200
    assert "Enregistrer le Workforce Plan" not in response.text
