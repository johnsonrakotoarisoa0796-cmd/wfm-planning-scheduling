"""Schémas Pydantic pour le module Scheduling (§33-§34)."""

from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ShiftInput(BaseModel):
    """Un gabarit de shift (§33) — les horaires doivent être configurables,
    pas codés en dur."""

    name: str = Field(min_length=1)
    start_time: time
    end_time: time
    break_minutes: int = Field(default=15, ge=0, le=120)
    break_count: int = Field(default=2, ge=0, le=4)
    break_paid: bool = True
    lunch_minutes: int = Field(default=60, ge=0, le=180)
    lunch_paid: bool = False

    @model_validator(mode="after")
    def _validate_shift_range(self) -> "ShiftInput":
        if self.start_time == self.end_time:
            raise ValueError("Un shift ne peut pas avoir la même heure de début et de fin.")
        return self


class ScheduleEntryInput(BaseModel):
    """Affectation d'un employé à un shift pour une date donnée.

    Si is_day_off est vrai, shift_id/break/lunch sont ignorés — un
    ré-enregistrement pour le même employé/date met à jour l'affectation
    existante plutôt que d'en créer une seconde (un agent a un seul
    planning par jour, contrairement au Shrinkage).
    """

    employee_id: int
    entry_date: date
    campaign_id: int
    skill_id: int
    is_day_off: bool = False
    shift_id: Optional[int] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    break2_start: Optional[time] = None
    break2_end: Optional[time] = None
    lunch_start: Optional[time] = None
    lunch_end: Optional[time] = None

    @model_validator(mode="after")
    def _shift_required_unless_day_off(self) -> "ScheduleEntryInput":
        if not self.is_day_off and self.shift_id is None:
            raise ValueError("Un shift est requis sauf si l'employé est en jour de repos.")
        return self


class EmployeeAbsenceInput(BaseModel):
    """Absence d'un agent sur une période calendaire."""

    employee_id: int
    start_date: date
    end_date: date
    absence_type: str
    paid: bool = False
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _valid_range(self) -> "EmployeeAbsenceInput":
        if self.end_date < self.start_date:
            raise ValueError("La fin d'absence doit être postérieure ou égale au début.")
        return self
