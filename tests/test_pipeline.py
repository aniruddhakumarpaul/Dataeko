from pathlib import Path

import pytest

from triage.pipeline import TriagePipeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pipeline():
    return TriagePipeline(ROOT / "artifacts" / "classifier.joblib", ROOT / "kb")


def test_security_ticket_is_never_silent_general(pipeline):
    result = pipeline.run("I see an unknown login and a charge I did not make.")
    c = result.classification
    assert c.category == "Security / Fraud" or c.needs_human_review
    assert not (c.category == "General Inquiry" and not c.needs_human_review)


def test_no_match_abstains(pipeline):
    result = pipeline.run("Tell me the cafeteria lunch menu for next Tuesday.")
    assert result.draft.grounded is False
