"""Tests du transport email et de la validation expéditeur."""

from app.services.email_service import (
    _brevo_payload,
    is_free_email_domain,
    sender_configuration_error,
)


def test_free_receiver_domains_are_allowed_as_recipients_but_not_as_senders():
    assert is_free_email_domain("user@yahoo.com")
    assert is_free_email_domain("user@outlook.com")
    assert is_free_email_domain("user@hotmail.com")
    assert not is_free_email_domain("user@company.example")


def test_production_rejects_free_email_sender_domains():
    error = sender_configuration_error(
        provider="brevo",
        from_email="wfm@yahoo.com",
        production=True,
    )
    assert error is not None
    assert "domaine email gratuit" in error


def test_production_accepts_custom_sender_domain():
    error = sender_configuration_error(
        provider="brevo",
        from_email="no-reply@wfm.example.com",
        production=True,
    )
    assert error is None


def test_development_can_use_a_free_sender_for_local_testing():
    error = sender_configuration_error(
        provider="brevo",
        from_email="wfm@gmail.com",
        production=False,
    )
    assert error is None


def test_brevo_payload_contains_transactional_tag_and_reply_to(monkeypatch):
    class FakeSettings:
        brevo_from_email = "no-reply@wfm.example.com"
        brevo_from_name = "WFM Planning & Scheduling"
        smtp_from_name = "WFM Planning & Scheduling"
        brevo_reply_to_email = "support@wfm.example.com"

    monkeypatch.setattr("app.services.email_service.get_settings", lambda: FakeSettings())

    payload = _brevo_payload(
        to_email="user@outlook.com",
        subject="Code",
        text_body="123456",
        html_body="<p>123456</p>",
    )

    assert payload["sender"]["email"] == "no-reply@wfm.example.com"
    assert payload["to"] == [{"email": "user@outlook.com"}]
    assert payload["tags"] == ["wfm-otp"]
    assert payload["replyTo"]["email"] == "support@wfm.example.com"
