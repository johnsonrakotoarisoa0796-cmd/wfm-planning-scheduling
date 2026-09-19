"""Schemas du suivi Workforce par campagne."""
from typing import Optional

from pydantic import BaseModel, Field


class CampaignWorkforcePlanInput(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    campaign_id: int

    current_hc: float = Field(ge=0)
    available_hc: float = Field(ge=0)
    long_leave_hc: float = Field(ge=0)
    training_hc: float = Field(ge=0)
    nesting_hc: float = Field(ge=0)
    other_unavailable_hc: float = Field(ge=0)

    attrition_pct: float = Field(ge=0, le=100)
    hiring_hc: float = Field(ge=0)
    transfers_in_hc: float = Field(ge=0)
    transfers_out_hc: float = Field(ge=0)

    required_hc: float = Field(ge=0)
    notes: Optional[str] = None
