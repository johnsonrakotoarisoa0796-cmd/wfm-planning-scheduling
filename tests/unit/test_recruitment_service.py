from datetime import date

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.campaign import Campaign
from app.models.skill import Skill
from app.services.recruitment_service import create_recruitment_plan, list_ramp_weeks, project_ramp


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    campaign = Campaign(name="Support FR", code="SUP-FR", is_active=True)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    skill = Skill(campaign_id=campaign.id, name="Phone", is_active=True)
    session.add(skill)
    session.commit()
    session.refresh(skill)
    return session, campaign.id, skill.id


def test_recruitment_creates_training_nesting_and_production_weeks():
    session, campaign_id, skill_id = _session()
    plan = create_recruitment_plan(
        session,
        cohort_name="Wave FR",
        campaign_id=campaign_id,
        skill_id=skill_id,
        start_date=date(2026, 9, 21),
        headcount=10,
        weekly_hours_contract=40,
        training_weeks=2,
        nesting_weeks=2,
        training_aht_seconds=420,
        training_occupancy_pct=75,
        nesting_aht_seconds=360,
        nesting_occupancy_pct=80,
        nesting_capacity_factor_pct=50,
        production_aht_seconds=300,
        production_occupancy_pct=85,
        created_by=None,
    )
    weeks = list_ramp_weeks(session, plan.id)
    assert [w.stage for w in weeks] == ["training", "training", "nesting", "nesting", "production"]
    projection = project_ramp(plan, weeks)
    assert projection[0].capacity_contacts == 0
    assert projection[2].capacity_contacts > 0
    assert projection[-1].capacity_contacts > projection[2].capacity_contacts
