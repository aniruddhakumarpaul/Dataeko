from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score, recall_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from triage.classifier import classify_ticket, fit_classifier, save_classifier  # noqa: E402
from triage.constants import COST_SENSITIVE_CLASS_WEIGHTS, SECURITY_CATEGORY  # noqa: E402
from triage.safety import audit_label_conflicts  # noqa: E402


def evaluate_model(model, X_test, y_test):
    preds = model.predict(X_test)
    return {
        "accuracy": accuracy_score(y_test, preds),
        "macro_f1": f1_score(y_test, preds, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_test, preds, average="weighted", zero_division=0),
        "security_recall_raw_model": recall_score(
            y_test,
            preds,
            labels=[SECURITY_CATEGORY],
            average="macro",
            zero_division=0,
        ),
        "report": classification_report(y_test, preds, output_dict=True, zero_division=0),
    }


def evaluate_safety(model, safety_df):
    rows = []
    for _, row in safety_df.iterrows():
        result = classify_ticket(model, row["text"])
        rows.append(
            {
                "ticket_id": row["ticket_id"],
                "expected": row["expected_label"],
                "predicted": result.category,
                "review": result.needs_human_review,
                "confidence": result.confidence,
            }
        )
    result_df = pd.DataFrame(rows)
    security = result_df[result_df["expected"] == SECURITY_CATEGORY]
    # A protected case counts as safely handled if it is routed to Security/Fraud OR explicitly held for human review.
    safe = (security["predicted"] == SECURITY_CATEGORY) | security["review"]
    normal = result_df[result_df["expected"] != SECURITY_CATEGORY]
    return {
        "protected_cases": int(len(security)),
        "protected_safe_handling_rate": float(safe.mean()) if len(security) else 0.0,
        "protected_silent_general_misroutes": int(((security["predicted"] == "General Inquiry") & ~security["review"]).sum()),
        "non_security_force_security_rate": float((normal["predicted"] == SECURITY_CATEGORY).mean()) if len(normal) else 0.0,
        "details": rows,
    }


def main():
    data = pd.read_csv(ROOT / "data" / "tickets.csv")
    safety = pd.read_csv(ROOT / "data" / "safety_eval.csv")

    conflicts = audit_label_conflicts(data["text"], data["label"])
    clean = data.drop(index=conflicts).reset_index(drop=True)

    train, test = train_test_split(
        clean,
        test_size=0.25,
        random_state=42,
        stratify=clean["label"],
    )

    baseline = fit_classifier(train["text"], train["label"], class_weight=None)
    # Cost-sensitive weights: modestly upweight minority classes and strongly protect Security/Fraud.
    # This preserves the baseline's precision while encoding the asymmetric business cost explicitly.
    final = fit_classifier(train["text"], train["label"], class_weight=COST_SENSITIVE_CLASS_WEIGHTS)

    baseline_metrics = evaluate_model(baseline, test["text"], test["label"])
    final_metrics = evaluate_model(final, test["text"], test["label"])
    safety_metrics = evaluate_safety(final, safety)

    save_classifier(final, ROOT / "artifacts" / "classifier.joblib")

    metrics = {
        "dataset_rows": int(len(data)),
        "training_rows_after_label_conflict_quarantine": int(len(clean)),
        "quarantined_label_conflicts": int(len(conflicts)),
        "class_counts": data["label"].value_counts().to_dict(),
        "baseline": baseline_metrics,
        "final_cost_sensitive": final_metrics,
        "safety_benchmark": safety_metrics,
    }
    (ROOT / "artifacts" / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("Baseline macro F1:", round(baseline_metrics["macro_f1"], 4))
    print("Final macro F1   :", round(final_metrics["macro_f1"], 4))
    print("Safety handling  :", f"{safety_metrics['protected_safe_handling_rate']:.1%}")
    print("Silent security->general misroutes:", safety_metrics["protected_silent_general_misroutes"])
    print("Saved -> artifacts/classifier.joblib")


if __name__ == "__main__":
    main()
