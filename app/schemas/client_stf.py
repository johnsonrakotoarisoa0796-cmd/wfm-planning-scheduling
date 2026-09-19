"""Schémas d'import du STF client par intervalle."""
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ClientSTFImportInput(BaseModel):
    week_start_date: date
    campaign_id: int
    skill_id: int
    label: str = Field(default="STF client", min_length=1)
    notes: Optional[str] = None
