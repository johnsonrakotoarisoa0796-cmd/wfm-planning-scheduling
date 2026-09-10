"""Test d'intégration de base : le schéma se crée et accepte des données
réelles avec relations (Campaign -> Skill -> ForecastVersion -> LTFForecast).

Utilise une base SQLite en mémoire, indépendante de Supabase, pour vérifier
la cohérence structurelle des modèles à chaque exécution de la suite de
tests (y compris en CI, sans base Postgres disponible).
"""

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as m
from app.models.enums import Channel, ForecastVersionType


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_all_tables_are_created(session: Session):
    table_names = set(SQLModel.metadata.tables.keys())
    expected = {
        "users",
        "campaigns",
        "skills",
        "employees",
        "employee_skills",
        "shifts",
        "schedule_entries",
        "forecast_versions",
        "ltf_forecasts",
        "stf_forecasts",
        "daily_forecasts",
        "interval_forecasts",
        "actual_performance_raw",
        "shrinkage_categories",
        "shrinkage_records",
        "capacity_plans",
        "overtime_plans",
        "sla_profiles",
        "config_parameters",
    }
    assert expected.issubset(table_names)


def test_ltf_forecast_versioning_chain(session: Session):
    """Vérifie la chaîne Campaign -> Skill -> ForecastVersion -> LTFForecast,
    et qu'aucune version n'écrase la précédente (règle §9)."""
    campaign = m.Campaign(name="Support Client FR", code="SUP-FR")
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    skill = m.Skill(campaign_id=campaign.id, name="Voix Niveau 1", channel=Channel.VOICE)
    session.add(skill)
    session.commit()
    session.refresh(skill)

    ltf_version = m.ForecastVersion(
        version_type=ForecastVersionType.LTF,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        campaign_id=campaign.id,
        skill_id=skill.id,
        label="LTF Septembre 2026",
        is_current=True,
    )
    session.add(ltf_version)
    session.commit()
    session.refresh(ltf_version)

    ltf = m.LTFForecast(
        forecast_version_id=ltf_version.id,
        year=2026,
        month=9,
        campaign_id=campaign.id,
        skill_id=skill.id,
        forecast_volume=42000,
        forecast_aht_seconds=320,
        headcount_required=98,
    )
    session.add(ltf)
    session.commit()

    # STF de la semaine 1, qui référence sa version LTF parente (jamais
    # d'écrasement de l'original).
    stf_version = m.ForecastVersion(
        version_type=ForecastVersionType.STF,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 7),
        campaign_id=campaign.id,
        skill_id=skill.id,
        parent_version_id=ltf_version.id,
        label="STF Semaine 36 - 2026",
        is_current=True,
    )
    session.add(stf_version)
    session.commit()
    session.refresh(stf_version)

    stf = m.STFForecast(
        forecast_version_id=stf_version.id,
        iso_year=2026,
        iso_week=36,
        week_start_date=date(2026, 9, 1),
        campaign_id=campaign.id,
        skill_id=skill.id,
        volume=44500,
        headcount_required=108,
    )
    session.add(stf)
    session.commit()

    # L'original LTF doit rester intact malgré la création du STF.
    stored_ltf = session.exec(
        select(m.LTFForecast).where(m.LTFForecast.forecast_version_id == ltf_version.id)
    ).one()
    assert stored_ltf.forecast_volume == 42000
    assert stored_ltf.headcount_required == 98

    stored_stf_version = session.exec(
        select(m.ForecastVersion).where(m.ForecastVersion.id == stf_version.id)
    ).one()
    assert stored_stf_version.parent_version_id == ltf_version.id
