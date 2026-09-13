"""Schémas Pydantic pour le module Shrinkage (§23-§25)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ShrinkageRecordInput(BaseModel):
    """Une occurrence de shrinkage pour un employé/jour donné.

    Plusieurs enregistrements peuvent coexister pour le même employé le
    même jour (ex: une pause ET une réunion) — pas de contrainte
    d'unicité, contrairement au LTF/STF/Capacity qui représentent chacun
    un état unique par période.
    """

    employee_id: int
    category_id: int
    record_date: date
    hours: float = Field(gt=0, le=24)
    campaign_id: int
    skill_id: int
    notes: Optional[str] = None
