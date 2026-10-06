from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import sqlite3

import pytest

from triage.review import direct_human_result
from triage.review import review_decision_from_classification
from triage.schemas import ClassificationResult, SafetySignal
from triage.tickets import TicketStore, normalize_phone
from triage.support_ui import ensure_operation_id


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


def test_ticket_write_rollback_does_not_enqueue_creation_email(backend):
    message = "Please let me speak to a person."
    request_id = uuid4().hex
    with backend.store._connect() as db:
        db.execute("""CREATE TRIGGER reject_ticket_event BEFORE INSERT ON ticket_events
            BEGIN SELECT RAISE(ABORT, 'simulated ticket transaction failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated ticket transaction failure"):
        backend.store.create_ticket(
            actor=backend.people["alice"], message=message, details="",
            phone=backend.people["alice"].phone, result=direct_human_result(message),
            request_id=request_id, direct_human=True,
        )
    with backend.store._connect() as db:
        assert db.execute("SELECT count(*) FROM tickets WHERE request_id=?", (request_id,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM mail_outbox WHERE event_key LIKE 'ticket:%'").fetchone()[0] == 0
    with backend.store._connect() as db:
        db.execute("DROP TRIGGER reject_ticket_event")


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


def early_classification(*, category="Billing", confidence=0.89, review=False, security=False):
    return ClassificationResult(
        category=category,
        confidence=confidence,
        probabilities={category: confidence, "Security / Fraud": 0.9 if security else 0.0},
        needs_human_review=review or security,
        review_reason="Security review required." if security else "Classifier requested review." if review else None,
        safety=SafetySignal(triggered=security, score=0.8 if security else 0.0),
        model_confidence=confidence,
        review_reason_code="security_review" if security else "classifier_review" if review else "low_confidence",
    )


def test_early_ticket_has_no_fabricated_ai_assistance_and_keeps_raw_score(backend):
    person = backend.people["alice"]
    request_id = uuid4().hex
    classification = early_classification(confidence=0.42)
    decision = review_decision_from_classification(classification)
    ticket_id = backend.store.create_ticket(
        actor=person, message="My subscription payment is unclear.", details="",
        phone=person.phone, classification=classification, decision=decision,
        request_id=request_id,
    )
    ticket = backend.store.get_ticket(backend.people["rahul"], ticket_id)
    assert ticket["ai_state"] == "pending"
    assert ticket["suggested_reply"] is None and ticket["sources"] == []
    assert ticket["confidence"] == 0.42
    assert ticket["classifier_confidence"] == 0.42
    assert ticket["creation_reason"] == "low_confidence"
    assert backend.store.ticket_id_for_request(person, request_id) == ticket_id


def test_security_ticket_does_not_persist_rule_score_as_model_confidence(backend):
    person = backend.people["alice"]
    classification = early_classification(category="Security / Fraud", confidence=0.83, security=True)
    ticket_id = backend.store.create_ticket(
        actor=person, message="An unknown login accessed my account.", details="",
        phone=person.phone, classification=classification,
        decision=review_decision_from_classification(classification), request_id=uuid4().hex,
    )
    ticket = backend.store.get_ticket(backend.people["rahul"], ticket_id)
    assert ticket["priority"] == "Urgent"
    assert ticket["confidence"] is None
    assert ticket["classifier_confidence"] == 0.83


def test_same_message_with_new_operation_id_creates_a_new_incident(backend):
    message = "Please let me speak to a person."
    first = raise_for(backend, request_id=uuid4().hex)
    second = backend.store.create_ticket(
        actor=backend.people["alice"], message=message, details="", phone=backend.people["alice"].phone,
        result=direct_human_result(message), request_id=uuid4().hex, direct_human=True,
    )
    assert first != second
    assert len(backend.store.list_tickets(backend.people["alice"])) == 2


def test_concurrent_duplicate_operations_converge_on_one_ticket(backend):
    request_id = uuid4().hex
    def create():
        return raise_for(backend, request_id=request_id)
    with ThreadPoolExecutor(max_workers=6) as pool:
        ticket_ids = list(pool.map(lambda _: create(), range(12)))
    assert len(set(ticket_ids)) == 1
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1
    with backend.store._connect() as db:
        assert db.execute("SELECT count(*) FROM ticket_events WHERE ticket_id=?", (ticket_ids[0],)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM mail_outbox WHERE event_key=?", (f"ticket:{ticket_ids[0]}:0",)).fetchone()[0] == 1


def test_operation_id_survives_reconstructed_ui_state_and_reuses_ticket(backend):
    first_browser = {}
    request_id = ensure_operation_id(first_browser)
    ticket_id = raise_for(backend, request_id=request_id)
    refreshed_browser = {"operation_id": request_id}
    assert ensure_operation_id(refreshed_browser) == request_id
    assert backend.store.ticket_id_for_request(backend.people["alice"], refreshed_browser["operation_id"]) == ticket_id
    assert raise_for(backend, request_id=refreshed_browser["operation_id"]) == ticket_id
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1


def test_legacy_ticket_schema_migrates_without_losing_ticket_events(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE tickets (
            id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
            message TEXT NOT NULL, details TEXT NOT NULL, customer_name TEXT NOT NULL, phone TEXT NOT NULL,
            category TEXT NOT NULL, confidence REAL NOT NULL, priority TEXT NOT NULL,
            review_reason TEXT NOT NULL, needs_human_review INTEGER NOT NULL,
            suggested_reply TEXT NOT NULL, sources TEXT NOT NULL, tracking_hash TEXT NOT NULL,
            status TEXT NOT NULL, assigned_to TEXT NOT NULL DEFAULT '', resolution TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
            tenant_id TEXT NOT NULL DEFAULT '', owner_id TEXT NOT NULL DEFAULT '', callback_requested INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE ticket_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL REFERENCES tickets(id),
            actor TEXT NOT NULL, status TEXT NOT NULL, occurred_at TEXT NOT NULL
        );
        INSERT INTO tickets VALUES
            ('TKT-LEGACY','0123456789abcdef0123456789abcdef','Old ticket','','Alice','+12025550111',
             'Billing',0.95,'Normal','Legacy reason',1,'Old reply','["KB-004"]','',
             'Open','Rahul','', '2026-01-01','2026-01-01',0,'team-a','alice',1);
        INSERT INTO ticket_events(ticket_id,actor,status,occurred_at)
            VALUES ('TKT-LEGACY','Customer','Open','2026-01-01');
    """)
    db.close()
    TicketStore(path)
    migrated = sqlite3.connect(path)
    migrated.row_factory = sqlite3.Row
    ticket = migrated.execute("SELECT * FROM tickets WHERE id='TKT-LEGACY'").fetchone()
    assert ticket["message"] == "Old ticket" and ticket["category"] == "Billing"
    assert ticket["suggested_reply"] == "Old reply" and ticket["creation_reason"] == "legacy"
    assert migrated.execute("SELECT count(*) FROM ticket_events WHERE ticket_id='TKT-LEGACY'").fetchone()[0] == 1
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    nullable = {row[1]: row[3] for row in migrated.execute("PRAGMA table_info(tickets)")}
    assert all(nullable[field] == 0 for field in ("category", "confidence", "suggested_reply", "sources"))
    migrated.close()
