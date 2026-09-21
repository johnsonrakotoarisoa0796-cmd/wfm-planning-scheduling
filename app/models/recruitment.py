"""Recrutement et ramp-up des nouvelles cohortes.

Une cohorte est planifiée avec une durée de formation et de nesting. Chaque
semaine de ramp-up possède ses propres hypothèses AHT, occupancy et facteur
de capacité opérationnelle, ce qui permet de projeter la capacité réellement
productive des nouvelles recrues.
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now


class RecruitmentPlan(SQLModel, table=True):
    __tablename__ = "recruitment_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    cohort_name: str = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    start_date: date = Field(index=True, nullable=False)
    headcount: int = Field(default=1, nullable=False)
    weekly_hours_contract: float = Field(default=40.0, nullable=False)

    # Suivi réel de la cohorte.
    recruited_hc: int = Field(default=0, nullable=False)
    training_hc: int = Field(default=0, nullable=False)
    nesting_hc: int = Field(default=0, nullable=False)
    production_hc: int = Field(default=0, nullable=False)
    exited_hc: int = Field(default=0, nullable=False)

    training_weeks: int = Field(default=2, nullable=False)
    nesting_weeks: int = Field(default=2, nullable=False)

    is_active: bool = Field(default=True, nullable=False)
    notes: Optional[str] = Field(default=None)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class RecruitmentRampWeek(SQLModel, table=True):
    __tablename__ = "recruitment_ramp_weeks"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="recruitment_plans.id", index=True, nullable=False)
    week_number: int = Field(nullable=False)
    week_start_date: date = Field(index=True, nullable=False)

    # training / nesting / production
    stage: str = Field(default="training", nullable=False)

    # Hypothèses opérationnelles de la semaine.
    aht_seconds: float = Field(default=300.0, nullable=False)
    occupancy_pct: float = Field(default=85.0, nullable=False)

    # 0% = formation pure, 100% = pleine capacité.
    capacity_factor_pct: float = Field(default=0.0, nullable=False)

    notes: Optional[str] = Field(default=None)
