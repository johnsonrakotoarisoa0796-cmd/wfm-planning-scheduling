"""Schémas Pydantic pour le module Capacity Planning (§31)."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class CapacityPlanInput(BaseModel):
    """Entrées d'un plan de capacité pour un mois/campagne/skill donné.

    Contrairement au LTF/STF (versionnés, jamais écrasés), un plan de
    capacité représente l'état courant du suivi RH pour une période — le
    ré-enregistrer met à jour le plan existant plutôt que d'en créer un
    nouveau (même logique que la saisie d'actuals en Daily/Intraday,
    commit 08 : ce n'est pas un forecast, c'est un suivi opérationnel).
    """

    period: str = Field(pattern=r"^\d{4}-\d{2}$")  # "YYYY-MM"
    campaign_id: int
    skill_id: int

    current_hc: float = Field(ge=0)
    hiring: float = Field(ge=0)
    transfers_in: float = Field(ge=0)
    transfers_out: float = Field(ge=0)
    attrition_pct: float = Field(ge=0, le=100)
    absenteeism_pct: float = Field(ge=0, le=100)

    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_period_month(self) -> "CapacityPlanInput":
        month = int(self.period.split("-")[1])
        if month < 1 or month > 12:
            raise ValueError("La période doit contenir un mois valide.")
        return self
