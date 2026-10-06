from dataclasses import dataclass

from .constants import SECURITY_CATEGORY, SECURITY_REVIEW_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
from .schemas import TriageResult, ClassificationResult, DraftResult
from .safety import detect_security_signals


@dataclass(frozen=True)
class ReviewDecision:
    required: bool
    security: bool
    reason: str


def review_decision(result: TriageResult) -> ReviewDecision:
    """One review decision for the pipeline, customer UI, and support inbox."""
    c = result.classification
    security = (
        c.category == SECURITY_CATEGORY
        or c.safety.triggered
        or c.probabilities.get(SECURITY_CATEGORY, 0.0) >= SECURITY_REVIEW_THRESHOLD
    )
    if security:
        return ReviewDecision(True, True, "Possible account access or payment misuse needs review.")
    if not result.draft.grounded:
        return ReviewDecision(True, False, "No help article answers this message; a person must review it.")
    if c.confidence < LOW_CONFIDENCE_THRESHOLD:
        return ReviewDecision(True, False, "Confidence is below 90%; a support executive must review this request.")
    if c.needs_human_review:
        return ReviewDecision(True, False, c.review_reason or "A support engineer needs to review this message.")
    return ReviewDecision(False, False, "Help article guidance is available; you can still request support.")


def direct_human_result(message: str) -> TriageResult:
    """A direct request must not wait for a model or optional generation service."""
    safety = detect_security_signals(message)
    category = SECURITY_CATEGORY if safety.score >= 0.45 else "General Inquiry"
    return TriageResult(
        classification=ClassificationResult(category, safety.score, {}, True,
            "Customer explicitly requested a person.", safety),
        retrieval=[],
        draft=DraftResult("A support executive will review your request.", False, "human-request", []),
    )
