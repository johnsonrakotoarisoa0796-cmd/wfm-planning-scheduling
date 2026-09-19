from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.main import bootstrap_markets, bootstrap_operational_configuration
from app.models.campaign import Campaign
from app.models.skill import Skill


def test_bootstrap_operational_configuration_fills_missing_standard_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    bootstrap_markets(db_engine=engine)

    with Session(engine) as session:
        session.add(Campaign(name="Support Client FR", code="SUP-FR", is_active=True))
        session.commit()

    bootstrap_operational_configuration(db_engine=engine)
    bootstrap_operational_configuration(db_engine=engine)

    with Session(engine) as session:
        campaigns = list(session.exec(select(Campaign).where(Campaign.is_active == True)).all())  # noqa: E712
        skills = list(session.exec(select(Skill).where(Skill.is_active == True)).all())  # noqa: E712

        assert {campaign.code for campaign in campaigns} == {
            "SUP-FR", "SUP-UK", "SUP-DE", "SUP-IN", "SUP-ES", "SUP-JP", "SUP-NL"
        }
        assert len(skills) == 28
        assert len({(skill.campaign_id, skill.channel) for skill in skills}) == 28
