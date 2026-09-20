"""Résolution centralisée des paramètres WFM d'une semaine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.forecast import LTFForecast, ForecastVersion, STFForecast
from app.models.weekly_parameters import WeeklyWFMParameter

settings = get_settings()


@dataclass(frozen=True)
class WeeklyParameters:
    iso_year: int
    iso_week: int
    week_start_date: date
    aht_seconds: float
    occupancy_pct: float
    service_level_target_pct: float
    answer_time_target_seconds: float
    shrinkage_pct: float
    interval_minutes: int
    source: str


def week_start(iso_year: int, iso_week: int) -> date:
    return date.fromisocalendar(iso_year, iso_week, 1)


def get_weekly_parameters(
    session: Session,
    *,
    iso_year: int,
    iso_week: int,
    campaign_id: int,
    skill_id: int,
) -> WeeklyParameters:
    """Retourne les paramètres explicites, puis STF/LTF, puis les défauts."""
    row = session.exec(
        select(WeeklyWFMParameter).where(
            WeeklyWFMParameter.iso_year == iso_year,
            WeeklyWFMParameter.iso_week == iso_week,
            WeeklyWFMParameter.campaign_id == campaign_id,
            WeeklyWFMParameter.skill_id == skill_id,
        )
    ).first()
    if row is not None:
        return WeeklyParameters(
            iso_year=row.iso_year, iso_week=row.iso_week, week_start_date=row.week_start_date,
            aht_seconds=row.aht_seconds, occupancy_pct=row.occupancy_pct,
            service_level_target_pct=row.service_level_target_pct,
            answer_time_target_seconds=row.answer_time_target_seconds,
            shrinkage_pct=row.shrinkage_pct, interval_minutes=row.interval_minutes,
            source="weekly-config",
        )

    stf = session.exec(
        select(STFForecast)
        .join(ForecastVersion, STFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            STFForecast.iso_year == iso_year,
            STFForecast.iso_week == iso_week,
            STFForecast.campaign_id == campaign_id,
            STFForecast.skill_id == skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).first()
    if stf is not None:
        return WeeklyParameters(
            iso_year, iso_week, stf.week_start_date, stf.aht_seconds, stf.occupancy_pct,
            stf.service_level_target_pct, settings.default_answer_time_target_seconds,
            stf.shrinkage_pct, settings.interval_minutes, "stf",
        )

    ltf = session.exec(
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            LTFForecast.iso_year == iso_year,
            LTFForecast.iso_week == iso_week,
            LTFForecast.campaign_id == campaign_id,
            LTFForecast.skill_id == skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).first()
    if ltf is not None:
        return WeeklyParameters(
            iso_year, iso_week, ltf.week_start_date or week_start(iso_year, iso_week),
            ltf.forecast_aht_seconds, ltf.occupancy_required_pct,
            ltf.service_level_target_pct, ltf.asa_target_seconds,
            ltf.total_shrinkage_pct, settings.interval_minutes, "ltf",
        )

    return WeeklyParameters(
        iso_year=iso_year,
        iso_week=iso_week,
        week_start_date=week_start(iso_year, iso_week),
        aht_seconds=settings.default_aht_seconds,
        occupancy_pct=settings.default_occupancy_pct,
        service_level_target_pct=settings.default_service_level_target_pct,
        answer_time_target_seconds=settings.default_answer_time_target_seconds,
        shrinkage_pct=settings.default_shrinkage_pct,
        interval_minutes=settings.interval_minutes,
        source="defaults",
    )


def upsert_weekly_parameters(
    session: Session,
    *,
    iso_year: int,
    iso_week: int,
    campaign_id: int,
    skill_id: int,
    aht_seconds: float,
    occupancy_pct: float,
    service_level_target_pct: float,
    answer_time_target_seconds: float,
    shrinkage_pct: float,
    interval_minutes: int,
    notes: str | None = None,
) -> WeeklyWFMParameter:
    if not 1 <= iso_week <= 53:
        raise ValueError("La semaine ISO doit être comprise entre 1 et 53.")
    if aht_seconds <= 0:
        raise ValueError("AHT doit être strictement positif.")
    if not 0 < occupancy_pct <= 100:
        raise ValueError("Occupancy doit être comprise entre 0 et 100%.")
    if not 0 <= service_level_target_pct <= 100:
        raise ValueError("Service Level doit être compris entre 0 et 100%.")
    if answer_time_target_seconds < 0:
        raise ValueError("ASA cible invalide.")
    if not 0 <= shrinkage_pct < 100:
        raise ValueError("Shrinkage doit être compris entre 0 et 100%.")
    if interval_minutes != 30:
        raise ValueError("La granularité WFM actuelle est fixée à 30 minutes.")

    row = session.exec(
        select(WeeklyWFMParameter).where(
            WeeklyWFMParameter.iso_year == iso_year,
            WeeklyWFMParameter.iso_week == iso_week,
            WeeklyWFMParameter.campaign_id == campaign_id,
            WeeklyWFMParameter.skill_id == skill_id,
        )
    ).first()
    payload = dict(
        iso_year=iso_year,
        iso_week=iso_week,
        week_start_date=week_start(iso_year, iso_week),
        campaign_id=campaign_id,
        skill_id=skill_id,
        aht_seconds=aht_seconds,
        occupancy_pct=occupancy_pct,
        service_level_target_pct=service_level_target_pct,
        answer_time_target_seconds=answer_time_target_seconds,
        shrinkage_pct=shrinkage_pct,
        interval_minutes=interval_minutes,
        notes=notes.strip() or None if notes else None,
    )
    if row is None:
        row = WeeklyWFMParameter(**payload)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
