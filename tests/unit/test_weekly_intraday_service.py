from datetime import date

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.campaign import Campaign
from app.models.intraday import IntervalForecast
from app.models.market import Market
from app.models.skill import Skill
from app.services.weekly_intraday_service import disperse_week


def test_weekly_volume_is_distributed_to_five_days_and_30_minute_intervals():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        campaign = Campaign(name="Support FR", code="SUP-FR", is_active=True)
        market = Market(code="FR", name="France", timezone_name="Europe/Paris", is_active=True)
        session.add(campaign)
        session.add(market)
        session.commit()
        session.refresh(campaign)
        session.refresh(market)
        skill = Skill(campaign_id=campaign.id, market_id=market.id, name="Phone", is_active=True)
        session.add(skill)
        session.commit()
        session.refresh(skill)

        rows = disperse_week(
            session,
            week_start_date=date(2026, 9, 21),
            campaign_id=campaign.id,
            skill_id=skill.id,
            weekly_volume=5000,
            aht_seconds=300,
            occupancy_pct=85,
            service_level_target_pct=80,
            answer_time_target_seconds=20,
            shrinkage_pct=10,
        )
        assert len(rows) == 240
        assert sum(row.forecast_volume for row in rows) == 5000
        assert len({row.date for row in rows}) == 5
        assert session.exec(
            select(IntervalForecast).where(
                IntervalForecast.campaign_id == campaign.id,
                IntervalForecast.skill_id == skill.id,
            )
        ).all()
