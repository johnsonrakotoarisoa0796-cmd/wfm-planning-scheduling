"""Tests unitaires — app/services/scheduling_service.py (fonctions pures).

La logique DB (upsert, compute_break_impact avec de vraies affectations)
est testée dans tests/integration/test_scheduling.py.
"""

from datetime import time

from app.models.schedule import ScheduleEntry
from app.models.shift import Shift
from app.services.scheduling_service import _entry_on_break_during_interval, _shift_covers_interval


def _shift(start: time, end: time) -> Shift:
    return Shift(name="Test", start_time=start, end_time=end, break_minutes=15, lunch_minutes=60)


# --- Couverture de shift, shifts normaux --------------------------------------

def test_normal_shift_covers_interval_inside():
    shift = _shift(time(9, 0), time(18, 0))
    assert _shift_covers_interval(shift, time(10, 0), time(10, 30)) is True


def test_normal_shift_does_not_cover_before_start():
    shift = _shift(time(9, 0), time(18, 0))
    assert _shift_covers_interval(shift, time(8, 0), time(8, 30)) is False


def test_normal_shift_end_is_exclusive():
    # Un shift 09:00-18:00 ne couvre pas l'intervalle 18:00-18:30.
    shift = _shift(time(9, 0), time(18, 0))
    assert _shift_covers_interval(shift, time(18, 0), time(18, 30)) is False


def test_normal_shift_start_is_inclusive():
    shift = _shift(time(9, 0), time(18, 0))
    assert _shift_covers_interval(shift, time(9, 0), time(9, 30)) is True


# --- Couverture de shift, shifts chevauchant minuit (§33, ex: 17:00-02:00) -----

def test_overnight_shift_covers_evening():
    shift = _shift(time(17, 0), time(2, 0))
    assert _shift_covers_interval(shift, time(20, 0), time(20, 30)) is True


def test_overnight_shift_covers_after_midnight():
    shift = _shift(time(17, 0), time(2, 0))
    assert _shift_covers_interval(shift, time(1, 0), time(1, 30)) is True


def test_overnight_shift_does_not_cover_daytime():
    shift = _shift(time(17, 0), time(2, 0))
    assert _shift_covers_interval(shift, time(10, 0), time(10, 30)) is False


def test_overnight_shift_end_is_exclusive():
    shift = _shift(time(17, 0), time(2, 0))
    assert _shift_covers_interval(shift, time(2, 0), time(2, 30)) is False


# --- Chevauchement pause/déjeuner ------------------------------------------------

def _entry(break_start=None, break_end=None, lunch_start=None, lunch_end=None) -> ScheduleEntry:
    return ScheduleEntry(
        employee_id=1, date="2026-09-15", campaign_id=1, skill_id=1,
        break_start=break_start, break_end=break_end, lunch_start=lunch_start, lunch_end=lunch_end,
    )


def test_break_overlapping_interval_detected():
    entry = _entry(break_start=time(10, 0), break_end=time(10, 15))
    assert _entry_on_break_during_interval(entry, time(10, 0), time(10, 30)) is True


def test_break_not_overlapping_interval():
    entry = _entry(break_start=time(10, 0), break_end=time(10, 15))
    assert _entry_on_break_during_interval(entry, time(11, 0), time(11, 30)) is False


def test_lunch_overlapping_interval_detected():
    entry = _entry(lunch_start=time(12, 0), lunch_end=time(13, 0))
    assert _entry_on_break_during_interval(entry, time(12, 30), time(13, 0)) is True


def test_no_break_or_lunch_set_never_overlaps():
    entry = _entry()
    assert _entry_on_break_during_interval(entry, time(12, 0), time(12, 30)) is False


def test_second_break_is_counted_in_break_impact():
    entry = _entry()
    entry.break2_start = time(16, 0)
    entry.break2_end = time(16, 15)
    assert _entry_on_break_during_interval(entry, time(16, 0), time(16, 30)) is True


def test_partial_overlap_at_boundary_counts():
    # Pause 10:00-10:10, intervalle 09:30-10:00 -> pas de chevauchement (limite exacte).
    entry = _entry(break_start=time(10, 0), break_end=time(10, 10))
    assert _entry_on_break_during_interval(entry, time(9, 30), time(10, 0)) is False
    # Intervalle 10:00-10:30 -> chevauchement.
    assert _entry_on_break_during_interval(entry, time(10, 0), time(10, 30)) is True
