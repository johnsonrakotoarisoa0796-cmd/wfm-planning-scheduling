"""Schémas Pydantic pour le module STF Weekly."""

from typing import Optional

from pydantic import BaseModel, Field


class STFCreateInput(BaseModel):
    """Entrées d'un formulaire de création STF — réajustement hebdomadaire
    d'un LTF déjà existant (§8). La cohérence "un LTF actif existe pour
    cette période" est vérifiée par le service, pas ici (elle nécessite une
    requête DB, hors périmètre d'un schéma Pydantic)."""

    iso_year: int = Field(ge=2000, le=2100)
    iso_week: int = Field(ge=1, le=53)
    campaign_id: int
    skill_id: int

    volume: float = Field(ge=0)
    aht_seconds: float = Field(gt=0)
    occupancy_pct: float = Field(gt=0, le=100)
    shrinkage_pct: float = Field(ge=0, lt=100)
    service_level_target_pct: float = Field(ge=0, le=100)

    @property
    def handling_time_seconds(self) -> float:
        """Handling Time opérationnel (AHT = Talk + Hold + ACW lorsqu'il est mesuré)."""
        return self.aht_seconds

    notes: Optional[str] = None
