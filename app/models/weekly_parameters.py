"""Paramètres WFM hebdomadaires par campagne/skill.

Cette table est la source de vérité des hypothèses utilisées lorsqu'un flux
intervalisé ne fournit que le volume. Elle permet notamment de calculer le
HC requis d'un STF client sans demander au client d'envoyer un HC pré-calculé.
"""
from datetime import date
from typing import Optional

from sqlmodel import Field, SQLModel


class WeeklyWFMParameter(SQLModel, table=True):
    __tablename__ = "weekly_wfm_parameters"

    id: Optional[int] = Field(default=None, primary_key=True)
    iso_year: int = Field(index=True, nullable=False)
    iso_week: int = Field(index=True, nullable=False)
    week_start_date: date = Field(index=True, nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)

    aht_seconds: float = Field(default=300.0, nullable=False)
    occupancy_pct: float = Field(default=85.0, nullable=False)
    service_level_target_pct: float = Field(default=80.0, nullable=False)
    answer_time_target_seconds: float = Field(default=20.0, nullable=False)
    shrinkage_pct: float = Field(default=0.0, nullable=False)
    interval_minutes: int = Field(default=30, nullable=False)

    notes: Optional[str] = Field(default=None)
