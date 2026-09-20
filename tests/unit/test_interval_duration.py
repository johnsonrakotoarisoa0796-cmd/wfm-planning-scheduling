from datetime import time

import pytest

from app.services.intraday_service import interval_duration_hours


def test_interval_duration_standard_30_minutes():
    assert interval_duration_hours(time(10, 0), time(10, 30)) == pytest.approx(0.5)


def test_interval_duration_crossing_midnight():
    assert interval_duration_hours(time(23, 30), time(0, 0)) == pytest.approx(0.5)
