"""Schémas Compliance / règles sociales WFM."""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class CompliancePolicyInput(BaseModel):
    campaign_id: int
    skill_id: Optional[int] = None
    name: str = Field(default="Standard WFM", min_length=1, max_length=120)

    max_consecutive_work_days: int = Field(default=5, ge=1, le=14)
    max_daily_hours: float = Field(default=10.0, gt=0, le=24)
    max_weekly_hours: float = Field(default=48.0, gt=0, le=168)
    max_weekly_overtime_hours: float = Field(default=8.0, ge=0, le=168)
    min_rest_hours: float = Field(default=11.0, ge=0, le=168)
    weekly_coverage_target_pct: float = Field(default=95.0, ge=0, le=100)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _valid_limits(self) -> "CompliancePolicyInput":
        if self.max_weekly_hours < self.max_daily_hours:
            raise ValueError("Le maximum hebdomadaire doit être >= au maximum journalier.")
        if self.max_weekly_overtime_hours > self.max_weekly_hours:
            raise ValueError("L'overtime maximum hebdomadaire ne peut pas dépasser le maximum hebdomadaire.")
        return self
