import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from triage.generation import _validated_claims, generate_grounded_response
from triage.kb import load_kb
from triage.retrieval import HybridRetriever
from triage.pipeline import TriagePipeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def retriever():
    return HybridRetriever(load_kb(ROOT / "kb"))


@pytest.mark.parametrize("query", [
    "Where can I download the cafeteria lunch menu?", "How do I change the oil in my car?",
    "How do I appeal a parking charge?", "What is the weather tomorrow?",
    "What is the cafeteria lunch menu?", "My laptop battery is overheating.",
    "What is my annual salary?", "Where can I book a flight?",
])
def test_out_of_domain_abstains_even_with_keyword_overlap(retriever, query, monkeypatch):
    monkeypatch.setenv("USE_OLLAMA", "0")
    result = generate_grounded_response(query, retriever.search(query))
    assert not result.grounded and result.generation_mode == "abstain"


def test_unsupported_guarantee_is_rejected_even_with_valid_citation(retriever, monkeypatch):
    hits = retriever.search("I was charged twice for my subscription.")
    fake = Mock()
    invented = "Your refund is guaranteed within 24 hours."
    fake.json.return_value = {"message":{"content":json.dumps({"claims":[{"source_id":hits[0].source_id,"text":invented,"evidence":invented}]})}}
    monkeypatch.setenv("USE_OLLAMA", "1")
    with patch("triage.generation.requests.post", return_value=fake):
        result = generate_grounded_response("I was charged twice.", hits)
    assert result.generation_mode == "extractive-fallback"
    assert "24 hours" not in result.text


def test_only_exact_source_evidence_is_accepted(retriever):
    hits = retriever.search("I was charged twice.")
    h = hits[0]
    evidence = h.text.split("\n\n")[0]
    payload = {"claims":[{"source_id":h.source_id,"text":evidence,"evidence":evidence}]}
    assert _validated_claims(json.dumps(payload), hits)
    payload["claims"][0]["text"] += " A refund is guaranteed."
    assert _validated_claims(json.dumps(payload), hits) is None


def test_no_answer_always_sets_backend_human_review(monkeypatch):
    monkeypatch.setenv("USE_OLLAMA", "0")
    p = TriagePipeline(ROOT / "artifacts" / "classifier.joblib", ROOT / "kb")
    r = p.run("Where can I download the cafeteria lunch menu?")
    assert not r.draft.grounded and r.classification.needs_human_review
