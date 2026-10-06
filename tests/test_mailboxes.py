from dataclasses import replace
import time

import pytest

from triage.mailboxes import MailboxService


@pytest.fixture
def boxes(backend):
    service = MailboxService(backend.store)
    for name in ("alice", "bob", "eve"):
        person = backend.people[name]
        service.provision(person.tenant_id,person.email,"separate-mail-password-123")
        service.receive(person.email,"Private email",f"Only for {name}")
    return service


def test_mailbox_requires_own_credentials_and_isolates_recipient_and_tenant(boxes, backend):
    token = boxes.sign_in(backend.people["alice"].email,"separate-mail-password-123")
    principal = boxes.resolve_session(token)
    assert [m["body"] for m in boxes.messages(principal)] == ["Only for alice"]
    with pytest.raises(PermissionError):
        boxes.messages(None)
    with pytest.raises(PermissionError):
        boxes.messages(replace(principal,tenant_id=backend.people["eve"].tenant_id))
    with pytest.raises(ValueError):
        boxes.sign_in(backend.people["alice"].email,"wrong password")


def test_mailbox_password_is_independent_of_support_password(boxes, backend):
    from conftest import PASSWORD
    with pytest.raises(ValueError):
        boxes.sign_in(backend.people["alice"].email,PASSWORD)


def test_mailbox_logout_and_session_expiry(boxes, backend):
    token = boxes.sign_in(backend.people["alice"].email,"separate-mail-password-123")
    boxes.logout(token)
    assert boxes.resolve_session(token) is None
    token = boxes.sign_in(backend.people["alice"].email,"separate-mail-password-123")
    with backend.store._connect() as db:
        db.execute("UPDATE mailbox_sessions SET expires_at=?",(time.time()-1,))
    assert boxes.resolve_session(token) is None


def test_mailbox_csrf_tokens_expire_and_require_cookie_match(boxes, backend):
    token = boxes.csrf_token()
    assert boxes.valid_csrf(token,token)
    assert not boxes.valid_csrf("",token)
    assert not boxes.valid_csrf(token,"wrong")
    with backend.store._connect() as db:
        db.execute("UPDATE mailbox_csrf SET expires_at=?",(time.time()-1,))
    assert not boxes.valid_csrf(token,token)


def test_same_email_cannot_be_reassigned_to_another_tenant(boxes, backend):
    with pytest.raises(ValueError,match="different tenant"):
        boxes.provision(backend.people["eve"].tenant_id,backend.people["alice"].email)


def test_unprovisioned_demo_recipient_is_not_silently_accepted(boxes):
    assert not boxes.receive("nobody@example.test","Test","No mailbox")


def test_demo_mailbox_accepts_one_character_password(backend):
    service = MailboxService(backend.store)
    service.provision(backend.people["alice"].tenant_id,"shortbox@example.test","1")
    assert service.resolve_session(service.sign_in("shortbox@example.test","1"))
