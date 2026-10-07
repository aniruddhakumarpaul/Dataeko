from pathlib import Path
import sqlite3
from unittest.mock import Mock, patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from triage.schemas import ClassificationResult, DraftResult, SafetySignal, TriageResult

ROOT = Path(__file__).resolve().parents[1]


def sample_result(category="Billing", grounded=True, review=False):
    return TriageResult(
        classification=ClassificationResult(
            category=category,
            confidence=0.87,
            probabilities={category: 0.87},
            needs_human_review=review,
            review_reason=None,
            safety=SafetySignal(triggered=False, score=0.0),
        ),
        retrieval=[],
        draft=DraftResult(
            text="Check the two charges. [KB-004]",
            grounded=grounded,
            generation_mode="extractive-fallback" if grounded else "abstain",
            cited_sources=["KB-004"] if grounded else [],
        ),
    )


@pytest.fixture
def app(backend, monkeypatch):
    pipeline = Mock()
    pipeline.retriever.backend = "tfidf"
    pipeline.classify.return_value = sample_result().classification
    pipeline.complete.side_effect = lambda message, classification: TriageResult(
        classification=classification,
        retrieval=[],
        draft=sample_result().draft,
    )
    st.cache_resource.clear()
    from conftest import session_for
    monkeypatch.setenv("SUPPORT_DB_PATH", str(backend.store.path))
    with patch("triage.pipeline.TriagePipeline", return_value=pipeline), patch("triage.mail.MailService", return_value=backend.mail):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
        at.session_state["auth_session"] = session_for(backend, backend.people["alice"])
        at.run()
        assert not at.exception
        yield at, pipeline
    st.cache_resource.clear()


def analyze(at, message="I was charged twice."):
    at.text_area(key="ticket_text").set_value(message)
    next(button for button in at.button if button.label == "Analyze ticket").click().run()
    assert not at.exception


def test_empty_message_does_not_analyze(app):
    at, pipeline = app
    next(button for button in at.button if button.label == "Analyze ticket").click().run()
    assert at.warning[0].value == "Paste a customer message before analyzing."
    pipeline.run.assert_not_called()


def test_reply_survives_rerun_and_details_are_optional(app):
    at, pipeline = app
    analyze(at)
    at.run()
    assert any("Check the two charges" in item.value for item in at.markdown)
    assert all(not expander.proto.expanded for expander in at.expander)
    assert not at.sidebar.children
    pipeline.classify.assert_called_once_with("I was charged twice.")
    pipeline.complete.assert_called_once()


def test_no_answer_requests_manual_handling_without_suggested_reply(app):
    at, pipeline = app
    pipeline.complete.side_effect = lambda message, classification: TriageResult(
        classification=classification, retrieval=[], draft=sample_result(category="General Inquiry", grounded=False).draft
    )
    analyze(at, "What is the cafeteria menu?")
    assert at.info[0].value == "A support engineer will review it and resolve it at the earliest."
    assert "support engineer" in at.info[0].value
    assert not any(item.value == "Suggested reply" for item in at.subheader)
    assert not any("Automatic routing allowed" in item.value for item in at.success)


def test_security_review_explains_next_action(app):
    at, pipeline = app
    pipeline.classify.return_value = sample_result(category="Security / Fraud", review=True).classification
    pipeline.complete.side_effect = lambda message, classification: TriageResult(
        classification=classification, retrieval=[], draft=sample_result(category="Security / Fraud", review=True).draft
    )
    analyze(at, "My account was hacked.")
    assert "Security review needed" in at.warning[0].value
    assert "security specialist" in at.warning[0].value


def test_security_abstention_keeps_review_and_no_answer_explanations(app):
    at, pipeline = app
    pipeline.classify.return_value = sample_result(category="Security / Fraud", grounded=False, review=True).classification
    pipeline.complete.side_effect = lambda message, classification: TriageResult(
        classification=classification, retrieval=[], draft=sample_result(category="Security / Fraud", grounded=False, review=True).draft
    )
    analyze(at, "My account was hacked and I need help.")
    assert "Security review needed" in at.warning[0].value
    assert at.info[0].value == "A support engineer will review it and resolve it at the earliest."


def test_selecting_example_clears_previous_result(app):
    at, _ = app
    analyze(at)
    at.selectbox(key="example").select("Account safety").run()
    assert "unknown login" in at.text_area(key="ticket_text").value
    assert not any(item.value == "Suggested reply" for item in at.subheader)


def test_start_over_clears_input_and_result(app):
    at, _ = app
    analyze(at)
    next(button for button in at.button if button.label == "Start over").click().run()
    assert at.text_area(key="ticket_text").value == ""
    assert not any(item.value == "Suggested reply" for item in at.subheader)


def test_analysis_failure_preserves_ticket_and_retry_reuses_it(app, backend):
    at, pipeline = app
    pipeline.complete.side_effect = RuntimeError("Internal failure details")
    analyze(at)
    assert "ticket is saved" in at.error[0].value
    assert "Internal failure" not in at.error[0].value
    assert at.text_area(key="ticket_text").value == "I was charged twice."
    assert "raised" in at.success[0].value
    pipeline.complete.side_effect = lambda message, classification: TriageResult(
        classification=classification, retrieval=[], draft=sample_result().draft
    )
    analyze(at)
    assert not at.error
    assert any(item.value == "Suggested reply" for item in at.subheader)
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1


def test_direct_human_service_raises_ticket_without_model_and_is_idempotent(app, backend):
    at, pipeline = app
    at.text_area(key="ticket_text").set_value("I need to talk to a person about my app crash.")
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    assert not at.exception
    pipeline.classify.assert_not_called()
    pipeline.complete.assert_not_called()
    rows = backend.store.list_tickets(backend.people["alice"])
    assert len(rows) == 1
    ticket = backend.store.get_ticket(backend.people["rahul"], rows[0]["id"])
    assert ticket["phone"] == backend.people["alice"].phone
    assert ticket["needs_human_review"] and ticket["callback_requested"]
    assert ticket["category"] is None and ticket["confidence"] is None
    assert ticket["ai_state"] == "not_required"
    assert ticket["creation_reason"] == "explicit_human"
    assert any("No real call" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1


def test_full_refresh_restores_receipt_from_durable_url_operation_id(app, backend):
    at, pipeline = app
    at.text_area(key="ticket_text").set_value("Please contact a support engineer.")
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    ticket_id = backend.store.list_tickets(backend.people["alice"])[0]["id"]
    operation_id = at.query_params["operation_id"]

    from conftest import session_for
    refreshed = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
    refreshed.query_params["operation_id"] = operation_id
    refreshed.session_state["auth_session"] = session_for(backend, backend.people["alice"])
    refreshed.run()
    assert not refreshed.exception
    assert any(ticket_id in item.value for item in refreshed.success)
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1
    pipeline.classify.assert_not_called()
    pipeline.complete.assert_not_called()


@pytest.mark.parametrize("confidence, expected_tickets", [(0.8999,1), (0.90,0), (0.95,0)])
def test_confidence_boundary_automatically_raises_human_ticket(app, backend, confidence, expected_tickets):
    at, pipeline = app
    pipeline.classify.return_value.confidence = confidence
    analyze(at)
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == expected_tickets
    if expected_tickets:
        row = backend.store.get_ticket(backend.people["rahul"], tickets[0]["id"])
        assert row["needs_human_review"] and row["phone"] == backend.people["alice"].phone
        assert "below 90%" in row["review_reason"]


@pytest.mark.parametrize(
    "kind, expected_reason, expected_priority",
    [
        ("security", "security_review", "Urgent"),
        ("low_confidence", "low_confidence", "Normal"),
        ("classifier_review", "classifier_review", "Normal"),
    ],
)
def test_early_review_is_committed_before_optional_pipeline_completion(app, backend, kind, expected_reason, expected_priority):
    at, pipeline = app
    classification = sample_result(category="Security / Fraud" if kind == "security" else "Billing", review=True).classification
    classification.confidence = 0.55 if kind == "low_confidence" else 0.97
    classification.model_confidence = classification.confidence
    classification.review_reason_code = "security_review" if kind == "security" else "classifier_review"
    if kind == "security":
        classification.safety.triggered = True
        classification.safety.score = 0.9
        classification.probabilities["Security / Fraud"] = 0.95
    pipeline.classify.return_value = classification

    def complete(message, classified):
        rows = backend.store.list_tickets(backend.people["alice"])
        assert len(rows) == 1
        row = backend.store.get_ticket(backend.people["rahul"], rows[0]["id"])
        assert row["ai_state"] == "pending"
        assert row["suggested_reply"] is None and row["sources"] == []
        assert row["creation_reason"] == expected_reason
        assert row["priority"] == expected_priority
        return TriageResult(classification=classified, retrieval=[], draft=sample_result().draft)

    pipeline.complete.side_effect = complete
    analyze(at, "A message that requires a review.")
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1


@pytest.mark.parametrize("error", [RuntimeError("retriever"), RuntimeError("generator"), TimeoutError("ollama")])
def test_optional_ai_failure_after_early_ticket_keeps_ticket_and_security_priority(app, backend, error):
    at, pipeline = app
    classification = sample_result(category="Security / Fraud", review=True).classification
    classification.confidence = 0.99
    classification.model_confidence = 0.91
    classification.safety.triggered = True
    classification.safety.score = 0.9
    classification.review_reason_code = "security_review"
    pipeline.classify.return_value = classification

    def fail_after_commit(message, classified):
        rows = backend.store.list_tickets(backend.people["alice"])
        assert len(rows) == 1
        ticket = backend.store.get_ticket(backend.people["rahul"], rows[0]["id"])
        assert ticket["priority"] == "Urgent" and ticket["ai_state"] == "pending"
        raise error

    pipeline.complete.side_effect = fail_after_commit
    analyze(at, "I saw an unknown login and need help.")
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == 1
    ticket = backend.store.get_ticket(backend.people["rahul"], tickets[0]["id"])
    assert ticket["priority"] == "Urgent" and ticket["ai_state"] == "failed"
    assert ticket["creation_reason"] == "security_review"


def test_later_insufficient_evidence_reuses_early_ticket(app, backend):
    at, pipeline = app
    def no_evidence(message, classification):
        return TriageResult(
            classification=classification, retrieval=[],
            draft=sample_result(grounded=False).draft,
        )
    pipeline.complete.side_effect = no_evidence
    analyze(at, "A low-confidence request that the KB cannot answer.")
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == 1
    ticket = backend.store.get_ticket(backend.people["rahul"], tickets[0]["id"])
    assert ticket["creation_reason"] == "low_confidence"
    assert ticket["ai_state"] == "complete" and ticket["suggested_reply"] is None


def test_later_insufficient_evidence_creates_ticket_when_no_early_review(app, backend):
    at, pipeline = app
    classification = sample_result().classification
    classification.confidence = 0.95
    classification.model_confidence = 0.95
    classification.needs_human_review = False
    classification.review_reason_code = None
    pipeline.classify.return_value = classification
    pipeline.complete.side_effect = lambda message, classified: TriageResult(
        classification=classified, retrieval=[], draft=sample_result(grounded=False).draft
    )
    analyze(at, "A high-confidence request absent from the knowledge base.")
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == 1
    row = backend.store.get_ticket(backend.people["rahul"], tickets[0]["id"])
    assert row["creation_reason"] == "insufficient_evidence"
    assert row["ai_state"] == "complete" and row["suggested_reply"] is None


def test_smtp_failure_keeps_ticket_and_email_retryable(app, backend, monkeypatch):
    at, _ = app
    def fail_smtp(_row):
        raise OSError("simulated SMTP outage")
    monkeypatch.setattr(backend.mail, "_send", fail_smtp)
    at.text_area(key="ticket_text").set_value("Please connect me with support.")
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == 1
    backend.mail.deliver_pending(event_key=f"ticket:{tickets[0]['id']}:0")
    with backend.store._connect() as db:
        statuses = {row["event_key"]: row["status"] for row in db.execute("SELECT event_key,status FROM mail_outbox")}
    assert statuses[f"ticket:{tickets[0]['id']}:0"] == "Failed"
    assert at.success and tickets[0]["id"] in at.success[0].value
    monkeypatch.setattr(backend.mail, "_send", lambda _row: None)
    backend.mail.deliver_pending(event_key=f"ticket:{tickets[0]['id']}:0")
    assert backend.mail.event_status(f"ticket:{tickets[0]['id']}:0") == "Sent"


def test_database_failure_does_not_show_successful_receipt(app, backend, monkeypatch):
    at, _ = app
    def fail_write(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database write failure")
    monkeypatch.setattr("triage.tickets.TicketStore.create_ticket", fail_write)
    at.text_area(key="ticket_text").set_value("Please connect me with support.")
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    assert not any(item.value.startswith("Ticket TKT-") for item in at.success)
    assert "couldn't save" in at.error[0].value
    assert backend.store.list_tickets(backend.people["alice"]) == []
