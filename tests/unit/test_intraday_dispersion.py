from app.schemas.intraday import WeeklyDispersionInput


def _base_payload(**overrides):
    data = {
        "monday_pct": 13,
        "tuesday_pct": 14,
        "wednesday_pct": 16,
        "thursday_pct": 17,
        "friday_pct": 14,
        "saturday_pct": 13,
        "sunday_pct": 13,
        "intraday_profile_pct": [1,1,1,2,3,3,3,3,4,4,2,2,2,2,2,2,2,2,2,2,2,2,5,5,5,5,5,5,5,5,3,4,4],
        "handling_time_seconds": 300,
        "absence_rate_pct": 5,
        "leave_rate_pct": 8,
        "break_15m_pct": [0]*33,
        "lunch_break_pct": [0]*33,
    }
    data.update(overrides)
    return data


def test_weekly_dispersion_profile_accepts_defaults():
    payload = WeeklyDispersionInput(**_base_payload())
    payload.validate_total()


def test_weekly_dispersion_rejects_non_100_intraday_profile():
    values = _base_payload()
    values["intraday_profile_pct"][0] = 2
    payload = WeeklyDispersionInput(**values)

    try:
        payload.validate_total()
    except ValueError as exc:
        assert "profil intraday" in str(exc)
    else:
        raise AssertionError("Expected the intraday total validation to fail")


def test_weekly_dispersion_rejects_absence_plus_leave_at_100():
    payload = WeeklyDispersionInput(**_base_payload(absence_rate_pct=60, leave_rate_pct=40))
    try:
        payload.validate_total()
    except ValueError as exc:
        assert "Absentéisme" in str(exc)
    else:
        raise AssertionError("Expected absence + leave validation to fail")
