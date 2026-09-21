"""Granularité journalière et intraday (30 min par défaut, §10)."""

from datetime import date as DateType
from datetime import datetime, time
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now
from app.models.enums import Channel


class DailyForecast(SQLModel, table=True):
    __tablename__ = "daily_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: DateType = Field(index=True, nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    channel: Channel = Field(default=Channel.VOICE, nullable=False)

    forecast_volume: float = Field(default=0)
    forecast_aht_seconds: float = Field(default=0)
    actual_volume: Optional[float] = Field(default=None)
    actual_aht_seconds: Optional[float] = Field(default=None)
    actual_talk_time_seconds: Optional[float] = Field(default=None)
    actual_hold_time_seconds: Optional[float] = Field(default=None)
    actual_acw_seconds: Optional[float] = Field(default=None)
    required_hc: float = Field(default=0)
    scheduled_hc: float = Field(default=0)
    actual_hc: Optional[float] = Field(default=None)


class IntervalForecast(SQLModel, table=True):
    """Granularité 30 minutes (paramétrable via interval_minutes)."""

    __tablename__ = "interval_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: DateType = Field(index=True, nullable=False)
    interval_start: time = Field(nullable=False)
    interval_end: time = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    channel: Channel = Field(default=Channel.VOICE, nullable=False)

    forecast_volume: float = Field(default=0)
    actual_volume: Optional[float] = Field(default=None)
    forecast_aht_seconds: float = Field(default=0)
    actual_aht_seconds: Optional[float] = Field(default=None)
    required_hc: float = Field(default=0)
    scheduled_hc: float = Field(default=0)
    actual_hc: Optional[float] = Field(default=None)
    # Cibles utilisées lors du calcul Erlang C initial (§10) — conservées
    # sur l'intervalle pour pouvoir recalculer un Service Level/ASA "atteint"
    # cohérent une fois les actuals connus (même seuil de temps de réponse).
    service_level_target_pct: float = Field(default=0)
    answer_time_target_seconds: float = Field(default=0)
    service_level_pct: Optional[float] = Field(default=None)
    asa_seconds: Optional[float] = Field(default=None)
    occupancy_pct: Optional[float] = Field(default=None)
    abandon_rate_pct: Optional[float] = Field(default=None)
    staffing_gap: Optional[float] = Field(default=None)
    overtime_required_hours: Optional[float] = Field(default=None)
    handling_time_seconds: float = Field(default=0)
    absence_rate_pct: float = Field(default=0)
    leave_rate_pct: float = Field(default=0)
    absence_hours: float = Field(default=0)
    leave_hours: float = Field(default=0)
    break_15m_pct: float = Field(default=0)
    lunch_break_pct: float = Field(default=0)


class ActualPerformanceRaw(SQLModel, table=True):
    """Table de staging pour les imports CSV/Excel avant agrégation (§36)."""

    __tablename__ = "actual_performance_raw"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: DateType = Field(index=True, nullable=False)
    interval_start: time = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)

    offered: float = Field(default=0)
    handled: float = Field(default=0)
    abandoned: float = Field(default=0)
    answered_within_threshold: Optional[float] = Field(default=None)
    talk_time_seconds: float = Field(default=0)
    hold_time_seconds: float = Field(default=0)
    acw_seconds: float = Field(default=0)
    agents_staffed: float = Field(default=0)
    paid_hours: float = Field(default=0)
    import_batch_id: Optional[str] = Field(default=None, index=True)
    imported_at: datetime = Field(default_factory=utc_now, nullable=False)
