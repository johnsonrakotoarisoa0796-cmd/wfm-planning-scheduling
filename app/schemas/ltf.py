"""Schémas Pydantic pour le module LTF Monthly."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LTFCreateInput(BaseModel):
    """Entrées d'un formulaire de création LTF, validées avant tout calcul.

    Toute règle de cohérence (bornes, sommes de pourcentages...) est
    vérifiée ici plutôt que dans le router ou le service, pour des messages
    d'erreur clairs et centralisés.
    """

    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
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

    notes: Optional[str] = None

    @field_validator("outdoor_shrinkage_pct")
    @classmethod
    def _total_shrinkage_under_100(cls, v: float, info) -> float:
        indoor = info.data.get("indoor_shrinkage_pct", 0.0)
        if indoor + v >= 100:
            raise ValueError("La somme du shrinkage indoor + outdoor doit rester strictement inférieure à 100%.")
        return v
