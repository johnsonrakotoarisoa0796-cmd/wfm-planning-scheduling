from datetime import timedelta

from app.core.time_utils import utc_now
from app.models.user import User
from app.services import otp_service


def test_email_otp_is_hashed_and_verified(monkeypatch):
    sent = {}

    def fake_send_login_otp(*, to_email, code, ttl_minutes):
        sent["email"] = to_email
        sent["code"] = code
        sent["ttl"] = ttl_minutes

    monkeypatch.setattr(otp_service, "send_login_otp", fake_send_login_otp)

    user = User(
        email="user@gmail.com",
        hashed_password="x",
        is_active=True,
    )

    class FakeSession:
        def add(self, obj): pass
        def commit(self): pass

    session = FakeSession()
    otp_service.issue_email_otp(session, user, force=True)

    assert sent["email"] == "user@gmail.com"
    assert len(sent["code"]) == 6
    assert sent["code"].isdigit()
    assert user.email_otp_hash != sent["code"]
    assert otp_service.verify_email_otp(session, user, sent["code"]) is True
    assert user.email_otp_hash is None


def test_email_otp_rejects_invalid_code(monkeypatch):
    monkeypatch.setattr(otp_service, "send_login_otp", lambda **kwargs: None)
    user = User(
        email="user@gmail.com",
        hashed_password="x",
        is_active=True,
    )

    class FakeSession:
        def add(self, obj): pass
        def commit(self): pass

    session = FakeSession()
    otp_service.issue_email_otp(session, user, force=True)
    assert otp_service.verify_email_otp(session, user, "000000") is False
