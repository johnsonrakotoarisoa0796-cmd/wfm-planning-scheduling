"""Schemas du suivi Workforce par campagne."""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class CampaignWorkforcePlanInput(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    campaign_id: int

    current_hc: float = Field(ge=0)
    available_hc: float = Field(ge=0)
    long_leave_hc: float = Field(ge=0)
    planned_leave_hc: float = Field(ge=0)
    unplanned_absence_hc: float = Field(ge=0)
    training_hc: float = Field(ge=0)
    nesting_hc: float = Field(ge=0)
    other_unavailable_hc: float = Field(ge=0)

    attrition_pct: float = Field(ge=0, le=100)
    hiring_hc: float = Field(ge=0)
    transfers_in_hc: float = Field(ge=0)
    transfers_out_hc: float = Field(ge=0)

    required_hc: float = Field(ge=0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_period_and_availability(self) -> "CampaignWorkforcePlanInput":
        month = int(self.period.split("-")[1])
        if month < 1 or month > 12:
            raise ValueError("La période doit être au format YYYY-MM avec un mois valide.")
        unavailable = (
            self.long_leave_hc
            + self.planned_leave_hc
            + self.unplanned_absence_hc
            + self.training_hc
            + self.nesting_hc
            + self.other_unavailable_hc
        )
        if unavailable > self.current_hc:
            raise ValueError("La somme des indisponibilités ne peut pas dépasser le Current HC.")
        return self
