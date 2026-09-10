"""Capacity planning — projection HC (§31)."""

from typing import Optional

from sqlmodel import Field, SQLModel


class CapacityPlan(SQLModel, table=True):
    __tablename__ = "capacity_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    period: str = Field(index=True, nullable=False)  # format "YYYY-MM"

    current_hc: float = Field(default=0)
    required_hc: float = Field(default=0)
    hiring: float = Field(default=0)
    transfers_in: float = Field(default=0)
    transfers_out: float = Field(default=0)
    attrition_pct: float = Field(default=0)
    absenteeism_pct: float = Field(default=0)
    projected_hc: float = Field(default=0)
    notes: Optional[str] = Field(default=None)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
