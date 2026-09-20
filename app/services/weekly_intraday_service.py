"""Dispersion d'un forecast hebdomadaire vers Daily puis Intraday."""
from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.forecast import LTFForecast, STFForecast
from app.models.market import Market
from app.models.skill import Skill
from app.models.intraday import IntervalForecast
from app.schemas.intraday import GenerateIntradayInput, WeeklyDispersionInput
from app.services.intraday_service import build_intraday_forecast_rows, intraday_window_profile_to_48
from app.services.weekly_parameter_service import get_weekly_parameters

settings = get_settings()


def weekday_volume_weights() -> list[float]:
    """Répartition V1 : 20% du volume hebdomadaire par jour ouvré."""
    return [0.20] * 5


def _timezone_for_skill(session: Session, skill_id: int) -> str:
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise ValueError("Skill introuvable.")
    if skill.market_id is None:
        return settings.default_timezone
    market = session.get(Market, skill.market_id)
    return market.timezone_name if market is not None else settings.default_timezone


def disperse_week(
    session: Session,
    *,
    week_start_date: date,
    campaign_id: int,
    skill_id: int,
    weekly_volume: float,
    aht_seconds: float,
    occupancy_pct: float,
    service_level_target_pct: float,
    answer_time_target_seconds: float,
    shrinkage_pct: float,
) -> list[IntervalForecast]:
    """Crée 5 journées x 48 intervalles = 240 intervalles par semaine.

    Le calcul HC reste centralisé dans le moteur Intraday/Erlang.
    """
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date doit être un lundi.")
    if weekly_volume < 0:
        raise ValueError("Le volume hebdomadaire doit être >= 0.")

    expected_dates = [week_start_date + timedelta(days=i) for i in range(5)]
    existing = session.exec(
        select(IntervalForecast).where(
            IntervalForecast.campaign_id == campaign_id,
            IntervalForecast.skill_id == skill_id,
            IntervalForecast.date >= expected_dates[0],
            IntervalForecast.date <= expected_dates[-1],
        )
    ).first()
    if existing is not None:
        raise ValueError("Des intervalles existent déjà sur cette semaine/campagne/skill.")

    timezone_name = _timezone_for_skill(session, skill_id)
    rows: list[IntervalForecast] = []
    for day, weight in zip(expected_dates, weekday_volume_weights()):
        data = GenerateIntradayInput(
            target_date=day,
            campaign_id=campaign_id,
            skill_id=skill_id,
            timezone_name=timezone_name,
            daily_volume=weekly_volume * weight,
            daily_aht_seconds=aht_seconds,
            service_level_target_pct=service_level_target_pct,
            answer_time_target_seconds=answer_time_target_seconds,
            occupancy_target_pct=occupancy_pct,
            shrinkage_pct=shrinkage_pct,
        )
        rows.extend(build_intraday_forecast_rows(session, data, check_existing=False, profile_pct_48=profile_48))

    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def disperse_stf(
    session: Session,
    stf: STFForecast,
) -> list[IntervalForecast]:
    iso = stf.week_start_date.isocalendar()
    parameters = get_weekly_parameters(
        session,
        iso_year=iso.year,
        iso_week=iso.week,
        campaign_id=stf.campaign_id,
        skill_id=stf.skill_id,
    )
    return disperse_week(
        session,
        week_start_date=stf.week_start_date,
        campaign_id=stf.campaign_id,
        skill_id=stf.skill_id,
        weekly_volume=stf.volume,
        aht_seconds=stf.aht_seconds,
        occupancy_pct=stf.occupancy_pct,
        service_level_target_pct=stf.service_level_target_pct,
        answer_time_target_seconds=parameters.answer_time_target_seconds,
        shrinkage_pct=stf.shrinkage_pct,
    )


def disperse_ltf(
    session: Session,
    ltf: LTFForecast,
) -> list[IntervalForecast]:
    if ltf.iso_year is None or ltf.iso_week is None or ltf.week_start_date is None:
        raise ValueError("Ce LTF est mensuel/historique ; créez un LTF hebdomadaire pour disperser.")
    return disperse_week(
        session,
        week_start_date=ltf.week_start_date,
        campaign_id=ltf.campaign_id,
        skill_id=ltf.skill_id,
        weekly_volume=ltf.forecast_volume,
        aht_seconds=ltf.forecast_aht_seconds,
        occupancy_pct=ltf.occupancy_required_pct,
        service_level_target_pct=ltf.service_level_target_pct,
        answer_time_target_seconds=ltf.asa_target_seconds,
        shrinkage_pct=ltf.total_shrinkage_pct,
    )


def disperse_stf_with_weights(
    session: Session,
    stf: STFForecast,
    dispersion: WeeklyDispersionInput,
) -> list[IntervalForecast]:
    """Disperse le volume STF sur lundi -> dimanche selon des poids explicites."""
    dispersion.validate_total()
    iso = stf.week_start_date.isocalendar()
    parameters = get_weekly_parameters(
        session,
        iso_year=iso.year,
        iso_week=iso.week,
        campaign_id=stf.campaign_id,
        skill_id=stf.skill_id,
    )

    expected_dates = [stf.week_start_date + timedelta(days=i) for i in range(7)]
    existing = session.exec(
        select(IntervalForecast).where(
            IntervalForecast.campaign_id == stf.campaign_id,
            IntervalForecast.skill_id == stf.skill_id,
            IntervalForecast.date >= expected_dates[0],
            IntervalForecast.date <= expected_dates[-1],
        )
    ).first()
    if existing is not None:
        raise ValueError(
            "Des intervalles existent déjà sur cette semaine/campagne/skill. "
            "Supprimez ou remplacez le Daily/Intraday existant avant une nouvelle dispersion."
        )

    timezone_name = _timezone_for_skill(session, stf.skill_id)
    profile_48 = intraday_window_profile_to_48(dispersion.intraday_profile_pct)
    rows: list[IntervalForecast] = []
    for day, weight in zip(expected_dates, dispersion.weights):
        daily_volume = stf.volume * (weight / 100.0)
        data = GenerateIntradayInput(
            target_date=day,
            campaign_id=stf.campaign_id,
            skill_id=stf.skill_id,
            timezone_name=timezone_name,
            daily_volume=daily_volume,
            daily_aht_seconds=stf.aht_seconds,
            service_level_target_pct=stf.service_level_target_pct,
            answer_time_target_seconds=parameters.answer_time_target_seconds,
            occupancy_target_pct=stf.occupancy_pct,
            shrinkage_pct=stf.shrinkage_pct,
        )
        rows.extend(build_intraday_forecast_rows(session, data, check_existing=False))

    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows
