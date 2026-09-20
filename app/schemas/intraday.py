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


class WeeklyDispersionInput(BaseModel):
    """Pondérations hebdomadaires + profil intraday personnalisable."""
    monday_pct: float = Field(ge=0, le=100)
    tuesday_pct: float = Field(ge=0, le=100)
    wednesday_pct: float = Field(ge=0, le=100)
    thursday_pct: float = Field(ge=0, le=100)
    friday_pct: float = Field(ge=0, le=100)
    saturday_pct: float = Field(ge=0, le=100)
    sunday_pct: float = Field(ge=0, le=100)
    intraday_profile_pct: list[float] = Field(min_length=33, max_length=33)

    @property
    def weights(self) -> list[float]:
        return [
            self.monday_pct,
            self.tuesday_pct,
            self.wednesday_pct,
            self.thursday_pct,
            self.friday_pct,
            self.saturday_pct,
            self.sunday_pct,
        ]

    @property
    def total_pct(self) -> float:
        return sum(self.weights)

    @property
    def intraday_total_pct(self) -> float:
        return sum(self.intraday_profile_pct)

    def validate_total(self) -> None:
        if abs(self.total_pct - 100.0) > 0.01:
            raise ValueError(
                f"La somme des poids jours doit être égale à 100%. "
                f"Actuellement : {self.total_pct:.2f}%."
            )
        if abs(self.intraday_total_pct - 100.0) > 0.01:
            raise ValueError(
                f"La somme du profil intraday doit être égale à 100%. "
                f"Actuellement : {self.intraday_total_pct:.2f}%."
            )
        if any(value < 0 or value > 100 for value in self.intraday_profile_pct):
            raise ValueError("Chaque poids intraday doit être compris entre 0% et 100%.")
