"""Forecast LTF (mensuel) et STF (hebdomadaire), avec versioning complet.

ForecastVersion est la table pivot : chaque révision (LTF initiale, ou
réajustement STF hebdomadaire) crée une nouvelle ligne, jamais un écrasement
silencieux (règle §9 du cahier des charges). parent_version_id relie une
version STF à la version (LTF ou STF précédente) dont elle découle, ce qui
permet à forecast_service.py de calculer les écarts (adjustment,
adjustment_pct) à la volée sans les stocker.
"""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now
from app.models.enums import ForecastVersionType


class ForecastVersion(SQLModel, table=True):
    __tablename__ = "forecast_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    version_type: ForecastVersionType = Field(nullable=False, index=True)
    period_start: date = Field(nullable=False)
    period_end: date = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    parent_version_id: Optional[int] = Field(default=None, foreign_key="forecast_versions.id")
    label: str = Field(nullable=False)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    notes: Optional[str] = Field(default=None)
    # Une seule version "courante" par (campagne, skill, période) : c'est
    # elle qui alimente le dashboard et les rapports "Current Forecast".
    is_current: bool = Field(default=True, index=True, nullable=False)
    calculation_engine_version: str = Field(default="2.1", nullable=False)


class LTFForecast(SQLModel, table=True):
    """Forecast mensuel — plan de référence long terme (§6 / §7)."""

    __tablename__ = "ltf_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    forecast_version_id: int = Field(foreign_key="forecast_versions.id", index=True, nullable=False)
    year: int = Field(index=True, nullable=False)
    month: int = Field(index=True, nullable=False)
    # Période hebdomadaire utilisée par le nouveau LTF. Les colonnes
    # year/month restent pour l'historique mensuel existant.
    iso_year: Optional[int] = Field(default=None, index=True)
    iso_week: Optional[int] = Field(default=None, index=True)
    week_start_date: Optional[date] = Field(default=None, index=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)

    forecast_volume: float = Field(default=0)
    forecast_aht_seconds: float = Field(default=0)
    aht_required_seconds: float = Field(default=0)
    occupancy_required_pct: float = Field(default=0)
    service_level_target_pct: float = Field(default=0)
    asa_target_seconds: float = Field(default=0)
    headcount_required: float = Field(default=0)
    paid_hours: float = Field(default=0)
    productive_hours: float = Field(default=0)
    production_hours: float = Field(default=0)
    waiting_hours: float = Field(default=0)
    indoor_shrinkage_pct: float = Field(default=0)
    outdoor_shrinkage_pct: float = Field(default=0)
    total_shrinkage_pct: float = Field(default=0)
    available_hours: float = Field(default=0)
    staffing_gap: float = Field(default=0)
    overtime_required_hours: float = Field(default=0)


class STFForecast(SQLModel, table=True):
    """Forecast hebdomadaire — révision du LTF (§8)."""

    __tablename__ = "stf_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    forecast_version_id: int = Field(foreign_key="forecast_versions.id", index=True, nullable=False)
    iso_year: int = Field(index=True, nullable=False)
    iso_week: int = Field(index=True, nullable=False)
    week_start_date: date = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)

    volume: float = Field(default=0)
    aht_seconds: float = Field(default=0)
    occupancy_pct: float = Field(default=0)
    shrinkage_pct: float = Field(default=0)
    service_level_target_pct: float = Field(default=0)
    headcount_required: float = Field(default=0)
    paid_hours: float = Field(default=0)
    productive_hours: float = Field(default=0)
    production_hours: float = Field(default=0)
    waiting_hours: float = Field(default=0)
    overtime_required_hours: float = Field(default=0)
