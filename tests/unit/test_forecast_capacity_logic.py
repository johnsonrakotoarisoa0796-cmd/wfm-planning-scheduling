import pytest

from app.models.enums import Channel
from app.services.channel_service import normalized_workload_hours
from app.services.kpi_service import (
    agent_workload_hours,
    workload_hours,
    projected_available_headcount,
    projected_headcount,
)


def test_voice_contact_hours_equal_agent_workload_when_no_concurrency():
    contact_hours = workload_hours(53200, 315)
    agent_hours = agent_workload_hours(53200, 315, 1.0)
    assert contact_hours == pytest.approx(agent_hours)


def test_async_channel_can_have_more_contact_hours_than_agent_workload():
    contact_hours = workload_hours(53200, 315)
    agent_hours = normalized_workload_hours(53200, 315, Channel.CHAT)
    assert contact_hours > agent_hours
    assert agent_hours == pytest.approx(contact_hours / 2.0)


def test_absenteeism_changes_availability_not_projected_headcount():
    projected = projected_headcount(
        current_hc=100,
        hiring=5,
        transfers_in=2,
        transfers_out=3,
        attrition_pct=5,
    )
    assert projected == pytest.approx(99.0)
    assert projected_available_headcount(projected, 10) == pytest.approx(89.1)
