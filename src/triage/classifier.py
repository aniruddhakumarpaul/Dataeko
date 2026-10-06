from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from .constants import (
    CATEGORIES,
    LOW_CONFIDENCE_THRESHOLD,
    SECURITY_CATEGORY,
    SECURITY_FORCE_THRESHOLD,
    SECURITY_REVIEW_THRESHOLD,
)
from .safety import detect_security_signals
from .schemas import ClassificationResult


def build_classifier(class_weight: str | dict | None = "balanced") -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    max_df=0.98,
                    sublinear_tf=True,
                    strip_accents="unicode",
                    max_features=18_000,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                    max_features=20_000,
                ),
            ),
        ]
    )
    clf = LogisticRegression(
        max_iter=2500,
        class_weight=class_weight,
        C=3.0,
        solver="lbfgs",
        random_state=42,
    )
    return Pipeline([("features", features), ("clf", clf)])


def fit_classifier(texts: Iterable[str], labels: Iterable[str], class_weight="balanced") -> Pipeline:
    model = build_classifier(class_weight=class_weight)
    model.fit(list(texts), list(labels))
    return model


def save_classifier(model: Pipeline, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load_classifier(path: str | Path) -> Pipeline:
    return joblib.load(path)


def classify_ticket(model: Pipeline, text: str) -> ClassificationResult:
    safety = detect_security_signals(text)
    probs = model.predict_proba([text])[0]
    classes = list(model.classes_)
    prob_map = {label: float(prob) for label, prob in zip(classes, probs)}
    for category in CATEGORIES:
        prob_map.setdefault(category, 0.0)

    model_category = classes[int(np.argmax(probs))]
    model_confidence = float(np.max(probs))
    security_prob = prob_map.get(SECURITY_CATEGORY, 0.0)

    # Protected-class override: explicit incident language or meaningful model risk goes to
    # Security/Fraud. This trades some precision for recall by design.
    force_security = safety.score >= 0.45 or security_prob >= SECURITY_FORCE_THRESHOLD
    if force_security:
        category = SECURITY_CATEGORY
        confidence = max(model_confidence if model_category == SECURITY_CATEGORY else 0.0, security_prob, safety.score)
        return ClassificationResult(
            category=category,
            confidence=float(min(confidence, 1.0)),
            probabilities=prob_map,
            needs_human_review=True,
            review_reason="Security/Fraud is protected: safety signal or security probability crossed the escalation threshold.",
            safety=safety,
        )

    review_reason = None
    needs_review = False

    if model_confidence < LOW_CONFIDENCE_THRESHOLD:
        needs_review = True
        review_reason = f"Low classifier confidence ({model_confidence:.0%})."

    # Even if another class wins, a non-trivial Security/Fraud probability cannot be silently ignored.
    if security_prob >= SECURITY_REVIEW_THRESHOLD:
        needs_review = True
        review_reason = (
            f"Security/Fraud probability is {security_prob:.0%}, above the review floor; ticket requires human review."
        )

    if safety.triggered:
        needs_review = True
        review_reason = "Security-adjacent language detected; ticket requires human review."

    if re.search(
        r"\b(?:human|real person|support agent|support engineer|someone from support)\b|"
        r"\b(?:call|contact) me\b|\b(?:still|not) (?:working|resolved|fixed)\b",
        text, re.IGNORECASE,
    ):
        needs_review = True
        review_reason = "The customer requested a person or reported that the issue remains unresolved."

    return ClassificationResult(
        category=model_category,
        confidence=model_confidence,
        probabilities=prob_map,
        needs_human_review=needs_review,
        review_reason=review_reason,
        safety=safety,
    )
