from datetime import date, time

import pytest

from app.models.client_stf import ClientSTFInterval
from app.models.intraday import IntervalForecast
from app.services.client_stf_service import (
    ClientSTFRow,
    effective_intervals,
    parse_csv,
    scorecard,
)


def test_parse_client_stf_csv():
    rows = parse_csv(
        "date,interval_start,interval_end,required_hc\n"
        "2026-09-21,07:00,07:30,18\n"
        "2026-09-21,07:30,08:00,20\n"
    )
    assert rows == [
        ClientSTFRow(date(2026, 9, 21), time(7, 0), time(7, 30), 18.0),
        ClientSTFRow(date(2026, 9, 21), time(7, 30), time(8, 0), 20.0),
    ]


def test_client_stf_rejects_duplicate_interval():
    with pytest.raises(ValueError, match="dupliqué"):
        parse_csv(
            "date,interval_start,interval_end,required_hc\n"
            "2026-09-21,07:00,07:30,18\n"
            "2026-09-21,07:00,07:30,20\n"
        )


def test_client_stf_overrides_required_hc_without_changing_forecast():
    internal = IntervalForecast(
        date=date(2026, 9, 21),
        interval_start=time(7, 0),
        interval_end=time(7, 30),
        campaign_id=1,
        skill_id=1,
        forecast_volume=100,
        forecast_aht_seconds=300,
        required_hc=10,
        scheduled_hc=15,
    )
    client = ClientSTFInterval(
        plan_id=1,
        date=date(2026, 9, 21),
        interval_start=time(7, 0),
        interval_end=time(7, 30),
        required_hc=18,
    )
    effective = effective_intervals([internal], [client])
    assert effective[0].required_hc == pytest.approx(18)
    assert effective[0].forecast_volume == pytest.approx(100)
    assert internal.required_hc == pytest.approx(10)


def test_client_stf_scorecard_calculates_coverage_shortage_surplus_and_fte():
    intervals = [
        IntervalForecast(
            date=date(2026, 9, 21),
            interval_start=time(7, 0),
            interval_end=time(7, 30),
            campaign_id=1,
            skill_id=1,
            required_hc=10,
            scheduled_hc=8,
        ),
        IntervalForecast(
            date=date(2026, 9, 21),
            interval_start=time(7, 30),
            interval_end=time(8, 0),
            campaign_id=1,
            skill_id=1,
            required_hc=10,
            scheduled_hc=12,
        ),
    ]
    rows = [
        ClientSTFInterval(
            plan_id=1,
            date=date(2026, 9, 21),
            interval_start=time(7, 0),
            interval_end=time(7, 30),
            required_hc=10,
        ),
        ClientSTFInterval(
            plan_id=1,
            date=date(2026, 9, 21),
            interval_start=time(7, 30),
            interval_end=time(8, 0),
            required_hc=14,
        ),
    ]
    result = scorecard(intervals, client_rows=rows)
    assert result.required_hc_hours == pytest.approx(12.0)
    assert result.scheduled_hc_hours == pytest.approx(10.0)
    assert result.shortage_hc_hours == pytest.approx(2.0)
    assert result.surplus_hc_hours == pytest.approx(0.0)
    assert result.coverage_pct == pytest.approx(83.33, abs=0.01)
    assert result.peak_stf_hc == pytest.approx(14)
    assert result.fte_equivalent_week == pytest.approx(0.3)
    assert result.model_variance_hc_hours == pytest.approx(2.0)
