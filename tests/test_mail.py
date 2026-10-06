from unittest.mock import Mock, patch

from triage.mail import enqueue_mail


def queue(backend):
    with backend.store._connect() as db:
        enqueue_mail(db, tenant_id=backend.people["alice"].tenant_id, recipient=backend.people["alice"].email,
                     subject="Ticket update", body="Your ticket is resolved.", kind="ticket", event_key="mail:test")


def test_failed_email_remains_retryable_and_does_not_claim_sent(backend):
    queue(backend)
    with patch.object(backend.mail, "_send", side_effect=ConnectionError("private SMTP failure")):
        backend.mail.deliver_pending()
    assert backend.mail.event_status("mail:test") == "Failed"
    with backend.store._connect() as db:
        assert db.execute("SELECT last_error FROM mail_outbox").fetchone()[0] == "ConnectionError"
    backend.mail.deliver_pending()
    assert backend.mail.event_status("mail:test") == "Sent"


def test_smtp_uses_tls_and_credentials_and_delivers_actual_message(backend):
    queue(backend)
    backend.mail.mode = "smtp"
    backend.mail.settings = {"host":"smtp.example.test", "port":587, "from":"dataeko@example.test", "username":"user", "password":"test-only-secret"}
    smtp = Mock()
    smtp.__enter__ = Mock(return_value=smtp)
    smtp.__exit__ = Mock(return_value=None)
    with patch("triage.mail.smtplib.SMTP", return_value=smtp):
        backend.mail.deliver_pending()
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user", "test-only-secret")
    assert smtp.send_message.call_args[0][0]["To"] == backend.people["alice"].email
    assert backend.mail.event_status("mail:test") == "Sent"


def test_sent_events_are_not_delivered_twice(backend):
    queue(backend)
    with patch.object(backend.mail, "_send") as send:
        backend.mail.deliver_pending()
        backend.mail.deliver_pending()
    send.assert_called_once()


def test_plaintext_cannot_be_enabled_for_external_smtp(backend):
    queue(backend)
    backend.mail.mode = "smtp"
    backend.mail.settings = {"host":"smtp.example.test", "port":587, "from":"dataeko@example.test", "allow_local_plaintext":True}
    smtp = Mock()
    smtp.__enter__ = Mock(return_value=smtp)
    smtp.__exit__ = Mock(return_value=None)
    with patch("triage.mail.smtplib.SMTP", return_value=smtp):
        backend.mail.deliver_pending()
    smtp.starttls.assert_called_once()
