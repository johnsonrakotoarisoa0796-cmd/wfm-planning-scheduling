import pytest

from app.models.enums import Channel
from app.services.channel_service import normalized_workload_hours


def test_skill_specific_concurrency_overrides_channel_default():
    default = normalized_workload_hours(120, 900, Channel.CHAT)
    custom = normalized_workload_hours(120, 900, Channel.CHAT, concurrency_factor=4)
    assert default == pytest.approx(15.0)
    assert custom == pytest.approx(7.5)