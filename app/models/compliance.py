"""Politiques de conformité planning par campagne et skill."""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now


class CompliancePolicy(SQLModel, table=True):
    __tablename__ = "compliance_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: Optional[int] = Field(default=None, foreign_key="skills.id", index=True)
    name: str = Field(default="Standard WFM", nullable=False)

    max_consecutive_work_days: int = Field(default=5, nullable=False)
    max_daily_hours: float = Field(default=10.0, nullable=False)
    max_weekly_hours: float = Field(default=48.0, nullable=False)
    max_weekly_overtime_hours: float = Field(default=8.0, nullable=False)
    min_rest_hours: float = Field(default=11.0, nullable=False)

    weekly_coverage_target_pct: float = Field(default=95.0, nullable=False)

    is_active: bool = Field(default=True, nullable=False)
    notes: Optional[str] = Field(default=None)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
