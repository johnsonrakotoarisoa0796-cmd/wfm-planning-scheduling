from datetime import date, time

import pytest

from app.services.client_stf_service import ClientSTFRow, parse_csv


def test_parse_client_stf_volume_only():
    rows = parse_csv(
        "date,interval_start,interval_end,volume\n"
        "2026-09-21,07:00,07:30,180\n"
        "2026-09-21,07:30,08:00,210\n"
    )
    assert rows == [
        ClientSTFRow(date(2026, 9, 21), time(7, 0), time(7, 30), None, 180.0),
        ClientSTFRow(date(2026, 9, 21), time(7, 30), time(8, 0), None, 210.0),
    ]


def test_parse_client_stf_keeps_legacy_required_hc_import():
    rows = parse_csv(
        "date,interval_start,interval_end,required_hc\n"
        "2026-09-21,07:00,07:30,18\n"
    )
    assert rows[0].required_hc == pytest.approx(18)
    assert rows[0].volume is None


def test_parse_client_stf_requires_volume_or_legacy_hc():
    with pytest.raises(ValueError, match="volume"):
        parse_csv(
            "date,interval_start,interval_end\n"
            "2026-09-21,07:00,07:30\n"
        )
