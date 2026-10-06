from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from triage.classifier import fit_classifier, save_classifier  # noqa: E402
from triage.constants import COST_SENSITIVE_CLASS_WEIGHTS  # noqa: E402
from triage.pipeline import TriagePipeline  # noqa: E402
from triage.safety import audit_label_conflicts  # noqa: E402

st.set_page_config(page_title="Support Ticket Triage Assistant", page_icon="🎫", layout="wide")


@st.cache_resource(show_spinner="Loading classifier and knowledge base…")
def load_pipeline() -> TriagePipeline:
    model_path = ROOT / "artifacts" / "classifier.joblib"
    if not model_path.exists():
        # Free-host friendly: model weights are intentionally not committed. Rebuild the tiny
        # classifier from the bundled synthetic CSV on first boot.
        data = pd.read_csv(ROOT / "data" / "tickets.csv")
        conflicts = audit_label_conflicts(data["text"], data["label"])
        clean = data.drop(index=conflicts).reset_index(drop=True)
        model = fit_classifier(
            clean["text"],
            clean["label"],
            class_weight=COST_SENSITIVE_CLASS_WEIGHTS,
        )
        model_path.parent.mkdir(parents=True, exist_ok=True)
        save_classifier(model, model_path)
    return TriagePipeline(model_path=model_path, kb_dir=ROOT / "kb")


pipeline = load_pipeline()

st.title("Support Ticket Triage Assistant")
st.caption("Cost-aware triage + protected Security/Fraud routing + grounded knowledge-base response drafting")

with st.sidebar:
    st.subheader("Design")
    st.markdown(
        """
- **Classifier:** word + character TF-IDF → class-weighted logistic regression
- **Security guard:** high-recall lexical gate + probability review floor
- **Retrieval:** hybrid BM25 + local semantic similarity
- **Generation:** Ollama open-weight model when enabled; grounded extractive fallback otherwise
- **Abstention:** no KB match → no invented answer
        """
    )
    st.caption(f"Retrieval backend: {pipeline.retriever.backend}")

samples = {
    "General": "Where can I see the details of my current plan and update my profile?",
    "Billing": "I was charged twice for my monthly subscription. How do I get the duplicate charge refunded?",
    "Technical": "The app crashes every time I open settings after logging in.",
    "Feature": "Could you add scheduled weekly exports to CSV?",
    "Security": "I see an unknown login and a charge I did not make. I think my account was hacked.",
}

selected = st.selectbox("Sample ticket", ["Custom"] + list(samples.keys()))
default_text = "" if selected == "Custom" else samples[selected]
ticket = st.text_area("Ticket text", value=default_text, height=170, placeholder="Paste a support ticket here…")

if st.button("Analyze ticket", type="primary", use_container_width=True):
    if not ticket.strip():
        st.warning("Enter a ticket first.")
    else:
        with st.spinner("Triaging and retrieving evidence…"):
            result = pipeline.run(ticket.strip())

        c = result.classification
        col1, col2, col3 = st.columns(3)
        col1.metric("Predicted category", c.category)
        col2.metric("Confidence", f"{c.confidence:.1%}")
        col3.metric("Human review", "Required" if c.needs_human_review else "Not required")

        if c.category == "Security / Fraud":
            st.error("Security / Fraud protected route: this ticket should be escalated for human review.")
        elif c.needs_human_review:
            st.warning(c.review_reason or "Human review required.")
        else:
            st.success("Automatic routing allowed under the current thresholds.")

        if c.safety.reasons:
            st.caption("Safety signals: " + ", ".join(c.safety.reasons))

        with st.expander("Classifier probabilities"):
            probs = pd.DataFrame(
                sorted(c.probabilities.items(), key=lambda x: x[1], reverse=True),
                columns=["Category", "Probability"],
            )
            st.dataframe(probs, hide_index=True, use_container_width=True)

        st.subheader("Suggested first response")
        if result.draft.grounded:
            st.markdown(result.draft.text)
            st.caption(f"Generation mode: {result.draft.generation_mode} · Sources: {', '.join(result.draft.cited_sources)}")
        else:
            st.warning(result.draft.text)
            st.caption(result.draft.reason or "Abstained")

        st.subheader("Retrieved evidence")
        evidence = pd.DataFrame(
            [
                {
                    "Source": h.source_id,
                    "Article": h.title,
                    "Hybrid relevance": round(h.score, 3),
                    "Lexical": round(h.lexical_score, 3),
                    "Semantic": round(h.semantic_score, 3),
                }
                for h in result.retrieval
            ]
        )
        st.dataframe(evidence, hide_index=True, use_container_width=True)

        for hit in result.retrieval[:3]:
            with st.expander(f"{hit.source_id} — {hit.title} ({hit.score:.3f})"):
                st.markdown(hit.text)
