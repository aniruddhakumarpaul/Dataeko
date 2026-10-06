from pathlib import Path
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
    pipeline.run.return_value = sample_result()
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
    pipeline.run.assert_called_once_with("I was charged twice.")


def test_no_answer_requests_manual_handling_without_suggested_reply(app):
    at, pipeline = app
    pipeline.run.return_value = sample_result(category="General Inquiry", grounded=False)
    analyze(at, "What is the cafeteria menu?")
    assert "Manual reply needed" in at.info[0].value
    assert "support engineer" in at.info[0].value
    assert not any(item.value == "Suggested reply" for item in at.subheader)
    assert not any("Automatic routing allowed" in item.value for item in at.success)


def test_security_review_explains_next_action(app):
    at, pipeline = app
    pipeline.run.return_value = sample_result(category="Security / Fraud", review=True)
    analyze(at, "My account was hacked.")
    assert "Security review needed" in at.warning[0].value
    assert "security specialist" in at.warning[0].value


def test_security_abstention_keeps_review_and_no_answer_explanations(app):
    at, pipeline = app
    pipeline.run.return_value = sample_result(category="Security / Fraud", grounded=False, review=True)
    analyze(at, "My account was hacked and I need help.")
    assert "Security review needed" in at.warning[0].value
    assert "Manual reply needed" in at.info[0].value


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


def test_analysis_failure_preserves_message_and_allows_retry(app):
    at, pipeline = app
    pipeline.run.side_effect = RuntimeError("Internal failure details")
    analyze(at)
    assert "Try again" in at.error[0].value
    assert "Internal failure" not in at.error[0].value
    assert at.text_area(key="ticket_text").value == "I was charged twice."
    pipeline.run.side_effect = None
    analyze(at)
    assert not at.error
    assert any(item.value == "Suggested reply" for item in at.subheader)


def test_direct_human_service_raises_ticket_without_model_and_is_idempotent(app, backend):
    at, pipeline = app
    at.text_area(key="ticket_text").set_value("I need to talk to a person about my app crash.")
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    assert not at.exception
    pipeline.run.assert_not_called()
    rows = backend.store.list_tickets(backend.people["alice"])
    assert len(rows) == 1
    ticket = backend.store.get_ticket(backend.people["rahul"], rows[0]["id"])
    assert ticket["phone"] == backend.people["alice"].phone
    assert ticket["needs_human_review"] and ticket["callback_requested"]
    assert any("No real call" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Talk to a person").click().run()
    assert len(backend.store.list_tickets(backend.people["alice"])) == 1


@pytest.mark.parametrize("confidence, expected_tickets", [(0.8999,1), (0.90,0), (0.95,0)])
def test_confidence_boundary_automatically_raises_human_ticket(app, backend, confidence, expected_tickets):
    at, pipeline = app
    pipeline.run.return_value.classification.confidence = confidence
    analyze(at)
    tickets = backend.store.list_tickets(backend.people["alice"])
    assert len(tickets) == expected_tickets
    if expected_tickets:
        row = backend.store.get_ticket(backend.people["rahul"], tickets[0]["id"])
        assert row["needs_human_review"] and row["phone"] == backend.people["alice"].phone
        assert "below 90%" in row["review_reason"]
