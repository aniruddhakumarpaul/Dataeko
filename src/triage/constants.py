from __future__ import annotations

CATEGORIES = [
    "General Inquiry",
    "Billing",
    "Technical Issue",
    "Feature Request",
    "Security / Fraud",
]

SECURITY_CATEGORY = "Security / Fraud"

# Deliberately conservative. The protected class is rare and has asymmetric cost.
LOW_CONFIDENCE_THRESHOLD = 0.58
SECURITY_FORCE_THRESHOLD = 0.24
SECURITY_REVIEW_THRESHOLD = 0.08
RETRIEVAL_MIN_RELEVANCE = 0.20

COST_SENSITIVE_CLASS_WEIGHTS = {
    "General Inquiry": 1.0,
    "Billing": 1.5,
    "Technical Issue": 1.7,
    "Feature Request": 1.8,
    "Security / Fraud": 10.0,
}
