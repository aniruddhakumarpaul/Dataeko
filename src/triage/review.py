from dataclasses import dataclass

from .constants import SECURITY_CATEGORY, SECURITY_REVIEW_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
from .schemas import TriageResult, ClassificationResult, DraftResult
from .safety import detect_security_signals


@dataclass(frozen=True)
class ReviewDecision:
    required: bool
    security: bool
    reason: str
    creation_reason: str | None = None


def review_decision_from_classification(
    classification: ClassificationResult | None,
    *,
    explicit_human_request: bool = False,
    safety_signal=None,
    evidence_sufficient: bool | None = None,
) -> ReviewDecision:
    """Authoritative early handoff policy shared by all pre-retrieval routes."""
    security = (
        (classification is not None and (
            classification.category == SECURITY_CATEGORY
            or classification.safety.triggered
            or classification.probabilities.get(SECURITY_CATEGORY, 0.0) >= SECURITY_REVIEW_THRESHOLD
        ))
        or (safety_signal is not None and (safety_signal.triggered or safety_signal.score >= 0.45))
    )
    if security:
        return ReviewDecision(True, True, "Possible account access or payment misuse needs review.", "security_review")
    if explicit_human_request:
        return ReviewDecision(True, False, "Customer requested direct human support.", "explicit_human")
    if classification is None:
        return ReviewDecision(False, False, "No classification decision is available.")
    if evidence_sufficient is False:
        return ReviewDecision(True, False, "No help article answers this message; a person must review it.", "insufficient_evidence")
    c = classification
    if c.confidence < LOW_CONFIDENCE_THRESHOLD:
        return ReviewDecision(True, False, "Confidence is below 90%; a support executive must review this request.", "low_confidence")
    if c.review_reason_code == "explicit_human":
        return ReviewDecision(True, False, c.review_reason or "The customer requested a person or reported that the issue remains unresolved.", "explicit_human")
    if c.needs_human_review and c.review_reason_code != "insufficient_evidence":
        return ReviewDecision(True, False, c.review_reason or "A support engineer needs to review this message.", "classifier_review")
    return ReviewDecision(False, False, "Help article guidance is available; you can still request support.")


def review_decision(result: TriageResult) -> ReviewDecision:
    """One review decision for the pipeline, customer UI, and support inbox."""
    return review_decision_from_classification(
        result.classification, evidence_sufficient=result.draft.grounded
    )


def direct_human_result(message: str) -> TriageResult:
    """A direct request must not wait for a model or optional generation service."""
    safety = detect_security_signals(message)
    category = SECURITY_CATEGORY if safety.score >= 0.45 else "General Inquiry"
    return TriageResult(
        classification=ClassificationResult(category, safety.score, {}, True,
            "Customer explicitly requested a person.", safety,
            review_reason_code="explicit_human"),
        retrieval=[],
        draft=DraftResult("A support executive will review your request.", False, "human-request", []),
    )


def direct_human_decision(message: str) -> ReviewDecision:
    """Resolve direct-human/security routing without loading or invoking a model."""
    safety = detect_security_signals(message)
    return review_decision_from_classification(
        None, explicit_human_request=True, safety_signal=safety
    )
