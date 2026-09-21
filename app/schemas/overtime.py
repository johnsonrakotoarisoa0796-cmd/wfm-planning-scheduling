"""Schémas Pydantic pour le module Overtime (§26-§30)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import PeriodType


class OvertimePlanInput(BaseModel):
    """Entrées pour calculer et enregistrer un plan Overtime sur une plage
    de dates. period_type détermine comment period_key est dérivé de
    start_date pour le stockage/upsert — end_date sert au calcul réel
    (somme des intervalles Daily/Intraday sur toute la plage)."""

    start_date: date
    end_date: date
    campaign_id: int
    skill_id: int
    period_type: PeriodType
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_period(self) -> "OvertimePlanInput":
        if self.end_date < self.start_date:
            raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")
        if self.period_type == PeriodType.DAILY and self.start_date != self.end_date:
            raise ValueError("Un plan DAILY doit couvrir exactement une journée.")
        if self.period_type == PeriodType.WEEKLY:
            if self.start_date.weekday() != 0 or (self.end_date - self.start_date).days != 6:
                raise ValueError("Un plan WEEKLY doit couvrir du lundi au dimanche.")
        if self.period_type == PeriodType.MONTHLY:
            from calendar import monthrange
            last_day = monthrange(self.start_date.year, self.start_date.month)[1]
            expected_end = self.start_date.replace(day=last_day)
            if self.start_date.day != 1 or self.end_date != expected_end:
                raise ValueError("Un plan MONTHLY doit couvrir le mois calendaire complet.")
        return self


class OvertimeActualInput(BaseModel):
    """Saisie de l'OT réellement effectué (§30), une fois connu (paie/pointage)."""

    ot_actual_hours: float = Field(ge=0)
