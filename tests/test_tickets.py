from dataclasses import replace
from uuid import uuid4

import pytest

from triage.review import direct_human_result
from triage.tickets import TicketStore, normalize_phone


def raise_for(backend, name="alice", request_id=None):
    p = backend.people[name]
    return backend.store.create_ticket(actor=p, message="Please let me speak to a person.",
        details="The application still crashes.", phone=p.phone,
        result=direct_human_result("Please let me speak to a person."), request_id=request_id or uuid4().hex,
        direct_human=True)


def test_ticket_is_persistent_assigned_and_phone_reaches_staff(backend):
    ticket_id = raise_for(backend)
    restarted = TicketStore(backend.store.path)
    row = restarted.get_ticket(backend.people["rahul"], ticket_id)
    assert row["phone"] == backend.people["alice"].phone
    assert row["assigned_to"] == "Rahul" and row["callback_requested"]
    assert row["needs_human_review"] == 1


def test_customer_only_sees_own_tickets_and_staff_only_own_tenant(backend):
    a, b, e = raise_for(backend), raise_for(backend, "bob"), raise_for(backend, "eve")
    assert [row["id"] for row in backend.store.list_tickets(backend.people["alice"])] == [a]
    assert backend.store.get_ticket(backend.people["alice"], b) is None
    assert backend.store.get_ticket(backend.people["rahul"], e) is None
    assert {row["id"] for row in backend.store.list_tickets(backend.people["rahul"])} == {a, b}
    assert backend.store.events(backend.people["eve"], a) == []


def test_customer_and_other_tenant_staff_cannot_resolve_ticket(backend):
    ticket_id = raise_for(backend)
    with pytest.raises(PermissionError):
        backend.store.update_ticket(backend.people["alice"], ticket_id, status="Resolved", assigned_to="Rahul", resolution="Done", expected_version=0)
    with pytest.raises(ValueError):
        backend.store.update_ticket(backend.people["priya"], ticket_id, status="Resolved", assigned_to="Priya", resolution="Done", expected_version=0)
    assert backend.store.get_ticket(backend.people["alice"], ticket_id)["status"] == "Open"


def test_forged_role_or_tenant_is_rejected(backend):
    with pytest.raises(PermissionError):
        backend.store.list_tickets(replace(backend.people["alice"], role="staff"))
    with pytest.raises(PermissionError):
        backend.store.list_tickets(replace(backend.people["alice"], tenant_id=backend.people["eve"].tenant_id))
    with pytest.raises(PermissionError):
        backend.store.list_tickets(None)


def test_duplicate_submission_does_not_duplicate_ticket_or_email(backend):
    request = uuid4().hex
    a, b = raise_for(backend, request_id=request), raise_for(backend, request_id=request)
    assert a == b
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1
    with backend.store._connect() as db:
        assert db.execute("SELECT count(*) FROM mail_outbox WHERE event_key=?", (f"ticket:{a}:0",)).fetchone()[0] == 1
    with pytest.raises(PermissionError):
        raise_for(backend, "bob", request_id=request)


def test_resolution_and_email_are_atomic_and_stale_changes_rejected(backend):
    ticket_id = raise_for(backend)
    backend.store.update_ticket(backend.people["rahul"], ticket_id, status="Resolved", assigned_to="Rahul", resolution="Issue resolved after updating the application.", expected_version=0)
    row = backend.store.get_ticket(backend.people["alice"], ticket_id)
    assert row["status"] == "Resolved" and row["resolution"]
    with backend.store._connect() as db:
        email = db.execute("SELECT recipient,body FROM mail_outbox WHERE event_key=?", (f"ticket:{ticket_id}:1",)).fetchone()
    assert email["recipient"] == backend.people["alice"].email
    assert "Resolved" in email["body"]
    with pytest.raises(ValueError, match="changed"):
        backend.store.update_ticket(backend.people["rahul"], ticket_id, status="In progress", assigned_to="Rahul", resolution="", expected_version=0)
    assert len(backend.store.events(backend.people["alice"], ticket_id)) == 2


def test_resolution_requires_customer_response_and_same_tenant_assignee(backend):
    ticket_id = raise_for(backend)
    with pytest.raises(ValueError, match="resolution"):
        backend.store.update_ticket(backend.people["rahul"], ticket_id, status="Resolved", assigned_to="Rahul", resolution="", expected_version=0)
    with pytest.raises(ValueError, match="organisation"):
        backend.store.update_ticket(backend.people["rahul"], ticket_id, status="In progress", assigned_to="Priya", resolution="", expected_version=0)


def test_phone_and_sql_inputs_validated(backend):
    assert normalize_phone("+1 (202) 555-0111", True) == "+12025550111"
    for invalid in ("", "555", "+012345678", "'+1; DROP TABLE tickets;--"):
        with pytest.raises(ValueError):
            normalize_phone(invalid, True)


def test_staff_notification_contains_callback_phone(backend):
    ticket_id = raise_for(backend)
    with backend.store._connect() as db:
        email = db.execute("SELECT recipient,body FROM mail_outbox WHERE event_key=?", (f"staff-ticket:{ticket_id}",)).fetchone()
    assert email["recipient"] == backend.people["rahul"].email
    assert backend.people["alice"].phone in email["body"]
