"""SLA configurable par campagne — distinct du Service Level pur (§15).

Le Service Level est un KPI calculé (% répondu <= seuil). La SLA est un
profil d'engagements contractuels qui peut inclure ce Service Level et
d'autres règles ; extra_rules_json permet d'étendre sans migration à chaque
nouvelle règle métier.
"""

from typing import Optional

from sqlmodel import Field, SQLModel


class SLAProfile(SQLModel, table=True):
    __tablename__ = "sla_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    name: str = Field(nullable=False)
    service_level_target_pct: float = Field(default=80.0, nullable=False)
    answer_time_threshold_seconds: float = Field(default=20.0, nullable=False)
    exclude_short_abandon: bool = Field(default=True, nullable=False)
    short_abandon_threshold_seconds: float = Field(default=5.0, nullable=False)
    extra_rules_json: Optional[str] = Field(default=None)
