"""Schémas Pydantic pour le module Overtime (§26-§30)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

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


class OvertimeActualInput(BaseModel):
    """Saisie de l'OT réellement effectué (§30), une fois connu (paie/pointage)."""

    ot_actual_hours: float = Field(ge=0)
