"""Suivi Workforce global par campagne et par mois."""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now


class CampaignWorkforcePlan(SQLModel, table=True):
    __tablename__ = "campaign_workforce_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    period: str = Field(index=True, nullable=False)  # YYYY-MM

    current_hc: float = Field(default=0.0, nullable=False)
    available_hc: float = Field(default=0.0, nullable=False)

    long_leave_hc: float = Field(default=0.0, nullable=False)
    planned_leave_hc: float = Field(default=0.0, nullable=False)
    unplanned_absence_hc: float = Field(default=0.0, nullable=False)
    training_hc: float = Field(default=0.0, nullable=False)
    nesting_hc: float = Field(default=0.0, nullable=False)
    other_unavailable_hc: float = Field(default=0.0, nullable=False)

    attrition_pct: float = Field(default=0.0, nullable=False)
    hiring_hc: float = Field(default=0.0, nullable=False)
    transfers_in_hc: float = Field(default=0.0, nullable=False)
    transfers_out_hc: float = Field(default=0.0, nullable=False)

    required_hc: float = Field(default=0.0, nullable=False)
    notes: Optional[str] = Field(default=None)

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
