"""Overtime — required vs actual, jamais confondus (§26-§30)."""

from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint

from app.models.enums import PeriodType


class OvertimePlan(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "skill_id", "period_type", "period_key",
            name="uq_overtime_campaign_skill_period",
        ),
    )

    __tablename__ = "overtime_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    period_type: PeriodType = Field(nullable=False, index=True)
    # "2026-09-08" (daily) / "2026-W36" (weekly) / "2026-09" (monthly)
    period_key: str = Field(index=True, nullable=False)

    required_hours: float = Field(default=0)
    available_hours: float = Field(default=0)
    gap_hours: float = Field(default=0)
    ot_required_hours: float = Field(default=0)
    # Reste nul tant qu'aucune donnée réelle (paie/pointage) n'est importée.
    ot_actual_hours: Optional[float] = Field(default=None)
    notes: Optional[str] = Field(default=None)
