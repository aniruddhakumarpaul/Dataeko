from __future__ import annotations

from pathlib import Path

from .classifier import classify_ticket, load_classifier
from .generation import generate_grounded_response
from .kb import load_kb
from .retrieval import HybridRetriever
from .review import review_decision
from .schemas import TriageResult


class TriagePipeline:
    def __init__(self, model_path: str | Path, kb_dir: str | Path):
        self.model_path = Path(model_path)
        self.kb_dir = Path(kb_dir)
        self.classifier = load_classifier(self.model_path)
        self._retriever = None

    @property
    def retriever(self) -> HybridRetriever:
        if self._retriever is None:
            self._retriever = HybridRetriever(load_kb(self.kb_dir))
        return self._retriever

    def classify(self, ticket_text: str):
        """Run only classification and safety checks; no KB or generator is loaded."""
        return classify_ticket(self.classifier, ticket_text)

    def complete(self, ticket_text: str, classification, top_k: int = 4) -> TriageResult:
        """Retrieve and draft after the caller has made and persisted early decisions."""
        hits = self.retriever.search(ticket_text, k=top_k)
        draft = generate_grounded_response(ticket_text, hits)
        result = TriageResult(classification=classification, retrieval=hits, draft=draft)
        review = review_decision(result)
        if review.required:
            classification.needs_human_review = True
            classification.review_reason = review.reason
            classification.review_reason_code = review.creation_reason
        return result

    def run(self, ticket_text: str, top_k: int = 4) -> TriageResult:
        return self.complete(ticket_text, self.classify(ticket_text), top_k=top_k)
