from pathlib import Path

from triage.kb import load_kb
from triage.retrieval import HybridRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_unauthorized_charge_retrieves_security_article():
    retriever = HybridRetriever(load_kb(ROOT / "kb"))
    hits = retriever.search("I have a card charge that I did not make", k=3)
    titles = [h.title.lower() for h in hits]
    assert any("unauthorized" in title for title in titles)


def test_password_reset_retrieves_reset_article():
    retriever = HybridRetriever(load_kb(ROOT / "kb"))
    hits = retriever.search("password reset link does not work", k=3)
    titles = [h.title.lower() for h in hits]
    assert any("password reset" in title for title in titles)
