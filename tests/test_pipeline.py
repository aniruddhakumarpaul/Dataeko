from unittest.mock import Mock

from triage import pipeline as pipeline_module
from triage.pipeline import TriagePipeline
from triage.schemas import ClassificationResult, SafetySignal


def test_classification_stage_does_not_load_or_call_retrieval(monkeypatch, tmp_path):
    model = object()
    classification = ClassificationResult(
        category="Billing", confidence=0.95, probabilities={"Billing": 0.95},
        needs_human_review=False, review_reason=None, safety=SafetySignal(False, 0.0),
    )
    monkeypatch.setattr(pipeline_module, "load_classifier", lambda _path: model)
    classify = Mock(return_value=classification)
    monkeypatch.setattr(pipeline_module, "classify_ticket", classify)
    load_kb = Mock(side_effect=AssertionError("KB should remain lazy during early routing"))
    monkeypatch.setattr(pipeline_module, "load_kb", load_kb)

    pipeline = TriagePipeline(tmp_path / "classifier.joblib", tmp_path / "kb")
    assert pipeline.classify("Where is my invoice?") is classification
    assert pipeline._retriever is None
    classify.assert_called_once_with(model, "Where is my invoice?")
    load_kb.assert_not_called()
