"""Schémas Pydantic pour le forecast LTF.

Le modèle courant est hebdomadaire. Les champs year/month restent acceptés
pour compatibilité avec les forecasts mensuels historiques.
"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class LTFCreateInput(BaseModel):
    # Nouveau mode hebdomadaire.
    iso_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    iso_week: Optional[int] = Field(default=None, ge=1, le=53)

    # Compatibilité historique mensuelle.
    year: Optional[int] = Field(default=None, ge=2000, le=2100)
    month: Optional[int] = Field(default=None, ge=1, le=12)

    campaign_id: int
    skill_id: int

    forecast_volume: float = Field(ge=0)
    forecast_aht_seconds: float = Field(gt=0)
    aht_required_seconds: float = Field(gt=0)

    occupancy_required_pct: float = Field(gt=0, le=100)
    service_level_target_pct: float = Field(ge=0, le=100)
    asa_target_seconds: float = Field(ge=0)

    indoor_shrinkage_pct: float = Field(ge=0, le=100)
    outdoor_shrinkage_pct: float = Field(ge=0, le=100)

    @property
    def handling_time_seconds(self) -> float:
        """Handling Time opérationnel (AHT = Talk + Hold + ACW lorsqu'il est mesuré)."""
        return self.forecast_aht_seconds

    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_period(self):
        has_week = self.iso_year is not None or self.iso_week is not None
        has_month = self.year is not None or self.month is not None
        if has_week:
            if self.iso_year is None or self.iso_week is None:
                raise ValueError("Le mode hebdomadaire exige iso_year et iso_week.")
        elif has_month:
            if self.year is None or self.month is None:
                raise ValueError("Le mode mensuel exige year et month.")
        else:
            raise ValueError("Une période LTF est obligatoire.")
        if self.indoor_shrinkage_pct + self.outdoor_shrinkage_pct >= 100:
            raise ValueError("La somme du shrinkage indoor + outdoor doit rester strictement inférieure à 100%.")
        return self
