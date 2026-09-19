from datetime import date, time

import pytest

from app.models.enums import Channel
from app.models.intraday import IntervalForecast
from app.models.market import Market
from app.services.channel_service import (
    channel_label,
    concurrency_for_channel,
    normalized_workload_hours,
    required_hc_aggregate_channel,
    required_hc_for_async,
)
from app.services.intraday_service import INTERVAL_SECONDS, generate_intraday_forecast


def test_channel_concurrency_rules():
    assert concurrency_for_channel(Channel.VOICE) == pytest.approx(1.0)
    assert concurrency_for_channel(Channel.EMAIL) == pytest.approx(3.0)
    assert concurrency_for_channel(Channel.CHAT) == pytest.approx(2.0)
    assert channel_label(Channel.VOICE) == "Phone"
    assert channel_label(Channel.CHAT) == "Message Us"


def test_async_workload_is_divided_by_concurrency():
    phone = normalized_workload_hours(120, 900, Channel.VOICE)
    email = normalized_workload_hours(120, 900, Channel.EMAIL)
    message_us = normalized_workload_hours(120, 900, Channel.CHAT)
    assert phone == pytest.approx(30.0)
    assert email == pytest.approx(10.0)
    assert message_us == pytest.approx(15.0)


def test_async_interval_staffing_uses_occupancy_and_concurrency():
    # 120 emails x 15 min = 30 workload hours.
    # /3 simultaneous = 10 agent-hours; in a 30-min interval at 85% occupancy:
    # 10 / (0.5 * .85) = 23.529 agents.
    assert required_hc_for_async(
        120, 900, 1800, 85, Channel.EMAIL
    ) == pytest.approx(23.5294118, abs=0.0001)


def test_aggregate_staffing_changes_by_channel():
    assert required_hc_aggregate_channel(30, 160, 85, Channel.VOICE) == pytest.approx(
        22.0588235, abs=0.0001
    )
    assert required_hc_aggregate_channel(30, 160, 85, Channel.EMAIL) == pytest.approx(
        7.3529411, abs=0.0001
    )


def test_market_model():
    market = Market(
        code="FR",
        name="France",
        language_code="fr",
        timezone_name="Europe/Paris",
    )
    assert market.code == "FR"
    assert market.timezone_name == "Europe/Paris"
