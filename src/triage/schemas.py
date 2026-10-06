from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SafetySignal:
    triggered: bool
    score: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    probabilities: Dict[str, float]
    needs_human_review: bool
    review_reason: str | None
    safety: SafetySignal


@dataclass
class RetrievalHit:
    source_id: str
    title: str
    path: str
    text: str
    score: float
    lexical_score: float
    semantic_score: float
    answerable: bool | None = None
    query_coverage: float = 0.0
    raw_bm25: float = 0.0


@dataclass
class DraftResult:
    text: str
    grounded: bool
    generation_mode: str
    cited_sources: List[str]
    reason: str | None = None


@dataclass
class TriageResult:
    classification: ClassificationResult
    retrieval: List[RetrievalHit]
    draft: DraftResult
