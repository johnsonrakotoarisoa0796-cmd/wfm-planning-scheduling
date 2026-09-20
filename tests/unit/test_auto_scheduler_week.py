from datetime import date

from app.services.auto_scheduler_service import _weekdays


def test_auto_scheduler_covers_all_seven_calendar_days():
    days = _weekdays(date(2026, 9, 7))
    assert len(days) == 7
    assert days[0] == date(2026, 9, 7)
    assert days[-1] == date(2026, 9, 13)
