"""Schemas du référentiel Workforce / Agents."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator

from app.models.enums import EmployeeStatus
from app.services.workforce_service import validate_timezone_name


class WorkforceEmployeeInput(BaseModel):
    employee_code: str
    first_name: str
    last_name: str
    campaign_id: int
    skill_id: int
    hire_date: date
    termination_date: date | None = None
    weekly_hours_contract: float = 40.0
    timezone_name: str = "UTC"
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    data_source: Literal["real", "synthetic"] = "real"

    @field_validator("employee_code", "first_name", "last_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ est obligatoire.")
        return value

    @field_validator("weekly_hours_contract")
    @classmethod
    def positive_hours(cls, value: float) -> float:
        if value <= 0 or value > 168:
            raise ValueError("Les heures contractuelles doivent être comprises entre 0 et 168.")
        return value

    @field_validator("termination_date")
    @classmethod
    def valid_termination_date(cls, value: date | None, info):
        hire_date = info.data.get("hire_date")
        if value is not None and hire_date is not None and value < hire_date:
            raise ValueError("La date de sortie ne peut pas être antérieure à la date d'embauche.")
        return value

    @field_validator("timezone_name")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        return validate_timezone_name(value.strip())
