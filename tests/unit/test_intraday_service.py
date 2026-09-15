"""Tests unitaires — app/services/intraday_service.py (fonctions pures).

La logique DB (génération, mise à jour d'intervalle) est testée dans
tests/integration/test_daily.py.
"""

from datetime import time

import pytest

from app.services.intraday_service import (
    SLOTS_PER_DAY,
    slot_bounds,
    default_intraday_profile_pct,
)


def test_profile_has_48_slots():
    assert len(default_intraday_profile_pct()) == SLOTS_PER_DAY == 48


def test_profile_sums_to_exactly_100():
    profile = default_intraday_profile_pct()
    assert sum(profile) == pytest.approx(100.0, abs=1e-9)


def test_profile_is_never_negative():
    assert all(pct >= 0 for pct in default_intraday_profile_pct())


def test_profile_night_hours_lower_than_midday():
    profile = default_intraday_profile_pct()
    midnight_pct = profile[0]  # 00:00-00:30
    midday_pct = profile[24]  # 12:00-12:30
    assert midday_pct > midnight_pct


def test_slot_bounds_first_slot():
    start, end = slot_bounds(0)
    assert start == time(0, 0)
    assert end == time(0, 30)


def test_slot_bounds_last_slot_ends_at_235959_not_midnight():
    # time() ne represente pas minuit comme 24:00:00.
    start, end = slot_bounds(47)
    assert start == time(23, 30)
    assert end == time(23, 59, 59)


def test_slot_bounds_are_contiguous():
    for slot in range(SLOTS_PER_DAY - 1):
        _, end = slot_bounds(slot)
        next_start, _ = slot_bounds(slot + 1)
        assert end == next_start
