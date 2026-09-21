from datetime import date

import pytest
from sqlmodel import Session, create_engine

from app.models.recruitment import RecruitmentPlan
from app.services.recruitment_service import progress_snapshot, update_progress


def test_progress_snapshot_calculates_production_readiness():
    plan = RecruitmentPlan(
        cohort_name='Wave A',
        campaign_id=1,
        skill_id=1,
        start_date=date(2026, 10, 5),
        headcount=20,
        training_weeks=2,
        nesting_weeks=2,
        recruited_hc=20,
        training_hc=4,
        nesting_hc=6,
        production_hc=8,
        exited_hc=2,
    )
    snapshot = progress_snapshot(plan)
    assert snapshot.active_pipeline_hc == 18
    assert snapshot.production_readiness_pct == pytest.approx(40.0)
    assert snapshot.recruitment_completion_pct == pytest.approx(100.0)
    assert snapshot.current_stage == 'production'
    assert snapshot.expected_production_date == date(2026, 11, 2)


def test_update_progress_rejects_more_people_than_pipeline():
    engine = create_engine('sqlite://')
    plan = RecruitmentPlan(
        cohort_name='Wave B',
        campaign_id=1,
        skill_id=1,
        start_date=date(2026, 10, 5),
        headcount=10,
    )
    with Session(engine) as session:
        with pytest.raises(ValueError, match='ne peuvent pas dépasser'):
            update_progress(
                session, plan, recruited_hc=5, training_hc=3,
                nesting_hc=2, production_hc=1, exited_hc=0,
            )