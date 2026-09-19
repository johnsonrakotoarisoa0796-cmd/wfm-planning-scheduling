"""Analyse forecast vs actual et reforecast de tendance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.intraday import IntervalForecast


@dataclass(frozen=True)
class ForecastLabMetrics:
    forecast_volume: float
    actual_volume: float
    wape_pct: Optional[float]
    bias_pct: Optional[float]
    accuracy_pct: Optional[float]
    forecast_aht_seconds: Optional[float]
    actual_aht_seconds: Optional[float]
    aht_bias_pct: Optional[float]
    data_points: int
    actual_points: int


@dataclass(frozen=True)
class ReforecastSuggestion:
    volume_multiplier: Optional[float]
    aht_multiplier: Optional[float]
    suggested_volume: Optional[float]
    suggested_aht_seconds: Optional[float]
    confidence_label: str


def list_intervals(session: Session, *, start_date: date, end_date: date, campaign_id: int, skill_id: int):
    return list(
        session.exec(
            select(IntervalForecast)
            .where(
                IntervalForecast.date >= start_date,
                IntervalForecast.date <= end_date,
                IntervalForecast.campaign_id == campaign_id,
                IntervalForecast.skill_id == skill_id,
            )
            .order_by(IntervalForecast.date, IntervalForecast.interval_start)
        ).all()
    )


def compute_metrics(rows: list[IntervalForecast]) -> ForecastLabMetrics:
    forecast_volume = sum(max(row.forecast_volume, 0.0) for row in rows)
    actual_rows = [row for row in rows if row.actual_volume is not None]
    actual_volume = sum(max(row.actual_volume or 0.0, 0.0) for row in actual_rows)
    abs_error = sum(abs(row.forecast_volume - (row.actual_volume or 0.0)) for row in actual_rows)
    wape = abs_error / actual_volume * 100.0 if actual_volume else None
    bias = (sum(row.forecast_volume for row in actual_rows) - actual_volume) / actual_volume * 100.0 if actual_volume else None
    accuracy = max(0.0, 100.0 - wape) if wape is not None else None

    aht_pairs = [
        (row.forecast_aht_seconds, row.actual_aht_seconds, max(row.actual_volume or 0.0, 0.0))
        for row in actual_rows
        if row.actual_aht_seconds is not None and row.actual_aht_seconds > 0 and row.actual_volume is not None and row.actual_volume > 0
    ]
    forecast_aht = (
        sum(f * w for f, _, w in aht_pairs) / sum(w for _, _, w in aht_pairs)
        if aht_pairs else None
    )
    actual_aht = (
        sum(a * w for _, a, w in aht_pairs) / sum(w for _, _, w in aht_pairs)
        if aht_pairs else None
    )
    aht_bias = (forecast_aht - actual_aht) / actual_aht * 100.0 if forecast_aht is not None and actual_aht else None

    return ForecastLabMetrics(
        forecast_volume=forecast_volume,
        actual_volume=actual_volume,
        wape_pct=wape,
        bias_pct=bias,
        accuracy_pct=accuracy,
        forecast_aht_seconds=forecast_aht,
        actual_aht_seconds=actual_aht,
        aht_bias_pct=aht_bias,
        data_points=len(rows),
        actual_points=len(actual_rows),
    )


def suggest_reforecast(
    session: Session,
    *,
    target_date: date,
    campaign_id: int,
    skill_id: int,
    lookback_days: int = 14,
) -> ReforecastSuggestion:
    start = target_date - timedelta(days=max(1, lookback_days))
    rows = list_intervals(
        session, start_date=start, end_date=target_date - timedelta(days=1),
        campaign_id=campaign_id, skill_id=skill_id,
    )
    volume_ratios = [
        row.actual_volume / row.forecast_volume
        for row in rows
        if row.actual_volume is not None and row.forecast_volume > 0
    ]
    aht_ratios = [
        row.actual_aht_seconds / row.forecast_aht_seconds
        for row in rows
        if row.actual_aht_seconds is not None and row.actual_aht_seconds > 0 and row.forecast_aht_seconds > 0
    ]
    volume_multiplier = sum(volume_ratios) / len(volume_ratios) if volume_ratios else None
    aht_multiplier = sum(aht_ratios) / len(aht_ratios) if aht_ratios else None

    target_rows = list_intervals(
        session, start_date=target_date, end_date=target_date,
        campaign_id=campaign_id, skill_id=skill_id,
    )
    base_volume = sum(row.forecast_volume for row in target_rows)
    weighted_aht_points = [
        (row.forecast_aht_seconds, row.forecast_volume)
        for row in target_rows if row.forecast_volume > 0
    ]
    base_aht = (
        sum(a * w for a, w in weighted_aht_points) / sum(w for _, w in weighted_aht_points)
        if weighted_aht_points else None
    )

    samples = min(len(volume_ratios), len(aht_ratios))
    confidence = "faible"
    if samples >= 100:
        confidence = "forte"
    elif samples >= 30:
        confidence = "moyenne"

    return ReforecastSuggestion(
        volume_multiplier=volume_multiplier,
        aht_multiplier=aht_multiplier,
        suggested_volume=(base_volume * volume_multiplier) if base_volume and volume_multiplier else None,
        suggested_aht_seconds=(base_aht * aht_multiplier) if base_aht and aht_multiplier else None,
        confidence_label=confidence,
    )
