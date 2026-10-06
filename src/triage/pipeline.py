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
        self.retriever = HybridRetriever(load_kb(self.kb_dir))

    def run(self, ticket_text: str, top_k: int = 4) -> TriageResult:
        classification = classify_ticket(self.classifier, ticket_text)
        hits = self.retriever.search(ticket_text, k=top_k)
        draft = generate_grounded_response(ticket_text, hits)
        result = TriageResult(classification=classification, retrieval=hits, draft=draft)
        review = review_decision(result)
        if review.required:
            classification.needs_human_review = True
            classification.review_reason = review.reason
        return result
