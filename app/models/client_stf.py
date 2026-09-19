"""STF client reçu déjà calculé et réparti par intervalle.

Cette source est distincte du STF hebdomadaire calculé par l'application.
Le STF client devient la référence de staffing opérationnel pour les
intervalles couverts par son import, sans recalculer le besoin à partir du
volume.
"""
from datetime import date, datetime, time
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now


class ClientSTFPlan(SQLModel, table=True):
    """Version d'un STF client pour une semaine/campagne/skill."""

    __tablename__ = "client_stf_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    week_start_date: date = Field(index=True, nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    label: str = Field(default="STF client", nullable=False)
    source: str = Field(default="client", nullable=False)
    import_batch_id: Optional[str] = Field(default=None, index=True)
    notes: Optional[str] = Field(default=None)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    is_current: bool = Field(default=True, index=True, nullable=False)


class ClientSTFInterval(SQLModel, table=True):
    """Besoin STF client pour une tranche horaire précise."""

    __tablename__ = "client_stf_intervals"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="client_stf_plans.id", index=True, nullable=False)
    date: date = Field(index=True, nullable=False)
    interval_start: time = Field(nullable=False)
    interval_end: time = Field(nullable=False)
    required_hc: float = Field(default=0, nullable=False)
