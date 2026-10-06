from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .schemas import SafetySignal


# High-recall lexical detector. It is intentionally broader than the classifier because
# false negatives in Security/Fraud are materially more expensive than false positives.
SECURITY_PATTERNS: list[tuple[str, str, float]] = [
    (r"\bunauthori[sz]ed\b", "unauthorized activity", 0.45),
    (r"\b(card|charge|payment|transaction)s?\b.{0,35}\b(not mine|unknown|fraud|stolen)\b", "suspicious financial activity", 0.55),
    (r"\b(phish|phishing|scam|scammer)\b", "phishing/scam language", 0.55),
    (r"\b(hack|hacked|compromis|takeover|breach)\w*\b", "account compromise language", 0.55),
    (r"\b(took|take|taken)\s+over\b.{0,25}\b(account|profile)\b", "account takeover language", 0.55),
    (r"\b(suspicious|unrecognized|unknown)\b.{0,30}\b(login|sign[ -]?in|device|session)\b", "suspicious login/device", 0.45),
    (r"\b(reset|changed)\b.{0,30}\b(password|email|2fa|mfa)\b.{0,30}\b(not me|without me|unknown)\b", "credential change not initiated by user", 0.60),
    (r"\b(stolen|lost)\b.{0,25}\b(card|phone|device|account)\b", "stolen/lost security-sensitive asset", 0.35),
    (r"\b(otp|verification code|2fa|mfa)\b.{0,35}\b(shared|asked|received|unknown|prompt)\b", "verification-code risk", 0.45),
    (r"\b(shared|gave|sent)\b.{0,35}\b(otp|verification code|2fa|mfa)\b", "verification-code exposure", 0.55),
    (r"\b(charge|transaction|invoice)\b.{0,35}\b(don.?t recognize|do not recognize|never made|never bought|not mine)\b", "unrecognized financial activity", 0.55),
    (r"\b(mfa|2fa|verification)\b.{0,25}\b(prompt|request|code)\b.{0,35}\b(wasn.?t|was not|not)\b.{0,20}\b(log|sign)\w*\b", "unexpected authentication prompt", 0.55),
    (r"\bidentity theft\b", "identity theft", 0.65),
]

NEGATION_SAFE_PATTERNS = [
    r"\bhow do i protect\b",
    r"\bsecurity best practices\b",
    r"\bis this email legitimate\b",
]

FINANCIAL_OBJECTS = r"\b(purchases?|orders?|charges?|payments?|transactions?|debits?|withdrawals?)\b"
ACCOUNT_OBJECTS = r"\b(accounts?|profiles?|passwords?|emails?|credentials?|messages?)\b"
UNAUTHORIZED_INTENT = (
    r"\b(?:(?:did not|didn't|never)\s+(?:authori[sz](?:e|ed)|approve(?:d)?|ma(?:ke|de)|request(?:ed)?)|"
    r"(?:do not|don't|dont)\s+recogni[sz]e|not mine|without (?:my )?(?:permission|consent)|"
    r"not authori[sz]ed by me|someone else|stranger|another person)\b"
)
ACCOUNT_ACTIONS = r"\b(chang\w*|edit\w*|access\w*|us\w*|read\w*|send\w*|different)\b"


def _compositional_signals(text: str) -> list[str]:
    reasons = []
    # Pair activity with unauthorized intent within the same short sentence rather
    # than treating a financial noun alone as proof of fraud.
    for clause in re.split(r"[.!?;\n]", text):
        if not re.search(UNAUTHORIZED_INTENT, clause):
            continue
        if re.search(FINANCIAL_OBJECTS, clause):
            reasons.append("financial activity not authorized by the customer")
        if re.search(ACCOUNT_OBJECTS, clause) and re.search(ACCOUNT_ACTIONS, clause):
            reasons.append("account activity not requested by the customer")
    return list(dict.fromkeys(reasons))


def detect_security_signals(text: str) -> SafetySignal:
    cleaned = " ".join(text.lower().replace("’", "'").split())
    if not cleaned:
        return SafetySignal(triggered=False, score=0.0, reasons=[])

    reasons: list[str] = []
    score = 0.0
    for reason in _compositional_signals(cleaned):
        reasons.append(reason)
        score = max(score, 0.60)
    for pattern, reason, weight in SECURITY_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE | re.DOTALL):
            reasons.append(reason)
            score = max(score, weight)

    # Security questions are still safety-relevant, but less urgent than an active incident.
    for pattern in NEGATION_SAFE_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            # A guidance question must not downgrade an accompanying incident.
            score = max(score, 0.20)
            if "security guidance request" not in reasons:
                reasons.append("security guidance request")

    # Multiple independent signals increase confidence without letting the score exceed 1.
    if len(reasons) >= 2:
        score = min(1.0, score + 0.15)

    return SafetySignal(triggered=bool(reasons), score=round(score, 4), reasons=reasons)


def audit_label_conflicts(texts: Iterable[str], labels: Iterable[str]) -> list[int]:
    """Return row indexes where explicit security signals conflict with a non-security label."""
    conflicts: list[int] = []
    for idx, (text, label) in enumerate(zip(texts, labels)):
        signal = detect_security_signals(str(text))
        if signal.score >= 0.45 and label != "Security / Fraud":
            conflicts.append(idx)
    return conflicts
