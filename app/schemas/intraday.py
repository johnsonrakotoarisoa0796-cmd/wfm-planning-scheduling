"""Schémas Pydantic pour le module Daily/Intraday (§10)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class GenerateIntradayInput(BaseModel):
    """Entrées pour générer les 48 intervalles de 30 min d'une journée à
    partir d'un volume total et d'un profil de distribution."""

    target_date: date
    campaign_id: int
    skill_id: int
    timezone_name: str = Field(default="UTC", min_length=1)

    daily_volume: float = Field(ge=0)
    daily_aht_seconds: float = Field(gt=0)

    service_level_target_pct: float = Field(ge=0, le=100)
    answer_time_target_seconds: float = Field(ge=0)
    occupancy_target_pct: float = Field(gt=0, le=100)
    shrinkage_pct: float = Field(ge=0, lt=100)


class IntervalUpdateInput(BaseModel):
    """Mise à jour d'un intervalle : planning réel (scheduled_hc) et/ou
    actuals une fois la journée passée. Tous les champs sont optionnels —
    seuls ceux fournis sont mis à jour."""

    scheduled_hc: Optional[float] = Field(default=None, ge=0)
    actual_volume: Optional[float] = Field(default=None, ge=0)
    actual_aht_seconds: Optional[float] = Field(default=None, gt=0)
    actual_talk_time_seconds: Optional[float] = Field(default=None, ge=0)
    actual_hold_time_seconds: Optional[float] = Field(default=None, ge=0)
    actual_acw_seconds: Optional[float] = Field(default=None, ge=0)
    actual_hc: Optional[float] = Field(default=None, ge=0)
    abandoned_contacts: Optional[float] = Field(default=None, ge=0)
