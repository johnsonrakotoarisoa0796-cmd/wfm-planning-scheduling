from app.services.kpi_service import handle_time_seconds, average_handle_time_seconds


def test_handle_time_is_talk_hold_plus_acw():
    assert handle_time_seconds(210, 35, 55) == 300


def test_average_handle_time_uses_handled_contacts():
    assert average_handle_time_seconds(30000, 100) == 300
