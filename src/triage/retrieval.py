from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .kb import KBChunk
from .schemas import RetrievalHit


STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "to", "of", "for", "from",
    "in", "on", "at", "by", "with", "as", "is", "are", "was", "were", "be", "been", "being",
    "i", "me", "my", "we", "our", "you", "your", "it", "this", "that", "these", "those", "do",
    "does", "did", "can", "could", "would", "should", "have", "has", "had", "tell", "please",
}

QUERY_EXPANSIONS = {
    "otp": "one time verification code phishing",
    "scam": "phishing impersonation suspicious",
    "scammed": "phishing impersonation fraud",
    "hacked": "compromised account takeover",
    "hack": "compromised account takeover",
    "unknown login": "suspicious unrecognized login device",
    "don't recognize": "unrecognized suspicious",
    "dont recognize": "unrecognized suspicious",
    "charged twice": "duplicate charge",
    "billed twice": "duplicate charge",
    "dark mode": "feature request product improvement",
    "add feature": "feature request product improvement",
    "did not authorize": "unauthorized fraudulent charge",
    "didn't authorize": "unauthorized fraudulent charge",
}

GENERIC_QUERY_WORDS = {
    "where", "when", "why", "how", "what", "will", "there", "right", "cannot", "same",
    "change", "download", "help", "support", "need", "want", "find", "get", "using", "use",
    "please", "tell", "someone", "open", "see", "add", "keeps", "got", "last",
}


def _coverage_tokens(text: str) -> set[str]:
    return {"app" if t == "application" else t for t in _tokenize(text) if t not in GENERIC_QUERY_WORDS}

def _expand_query(text: str) -> str:
    lower = text.lower()
    extras = [expansion for phrase, expansion in QUERY_EXPANSIONS.items() if phrase in lower]
    return text if not extras else text + " " + " ".join(extras)

def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


class SimpleBM25:
    """Dependency-free BM25 for a tiny KB."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [_tokenize(d) for d in docs]
        self.k1 = k1
        self.b = b
        self.doc_len = np.array([len(d) for d in self.docs], dtype=float)
        self.avgdl = float(self.doc_len.mean()) if len(self.doc_len) else 1.0
        self.df: dict[str, int] = {}
        for doc in self.docs:
            for token in set(doc):
                self.df[token] = self.df.get(token, 0) + 1
        self.n = len(self.docs)

    def score(self, query: str) -> np.ndarray:
        q = _tokenize(query)
        scores = np.zeros(self.n, dtype=float)
        for token in q:
            df = self.df.get(token, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for i, doc in enumerate(self.docs):
                tf = doc.count(token)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += idf * (tf * (self.k1 + 1) / denom)
        return scores


class HybridRetriever:
    """Hybrid BM25 + semantic retrieval.

    Uses a local sentence-transformer when available; otherwise falls back to TF-IDF semantic
    similarity so the demo remains zero-cost and fully runnable in constrained environments.
    """

    def __init__(self, chunks: Sequence[KBChunk], embedding_model: str = "BAAI/bge-small-en-v1.5"):
        self.chunks = list(chunks)
        self.texts = [f"{c.title}\n{c.text}" for c in self.chunks]
        self.bm25 = SimpleBM25(self.texts)
        self.backend = "tfidf"
        self.embedding_model_name = embedding_model
        self._st_model = None
        self._dense_matrix = None

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._st_model = SentenceTransformer(embedding_model)
            self._dense_matrix = self._st_model.encode(
                self.texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            self.backend = "sentence-transformers"
        except Exception:
            self._tfidf = TfidfVectorizer(
                ngram_range=(1, 2),
                sublinear_tf=True,
                stop_words="english",
            )
            self._dense_matrix = self._tfidf.fit_transform(self.texts)

    @staticmethod
    def _minmax(values: np.ndarray) -> np.ndarray:
        if values.size == 0:
            return values
        lo, hi = float(values.min()), float(values.max())
        if abs(hi - lo) < 1e-12:
            return np.zeros_like(values) if hi == 0 else np.ones_like(values)
        return (values - lo) / (hi - lo)

    def _semantic_scores(self, query: str) -> np.ndarray:
        if self.backend == "sentence-transformers":
            q = self._st_model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
            return np.asarray(self._dense_matrix @ q, dtype=float)
        q = self._tfidf.transform([query])
        return cosine_similarity(q, self._dense_matrix)[0]

    def search(self, query: str, k: int = 4) -> list[RetrievalHit]:
        expanded = _expand_query(query)
        lexical_raw = self.bm25.score(expanded)
        semantic_raw = self._semantic_scores(expanded)

        lexical = self._minmax(lexical_raw)
        semantic = np.clip(semantic_raw, 0.0, 1.0)
        # Dense semantics carries slightly more weight; lexical exact-match helps procedural terms.
        hybrid = 0.42 * lexical + 0.58 * semantic

        order = np.argsort(-hybrid)[:k]
        hits: list[RetrievalHit] = []
        for idx in order:
            c = self.chunks[int(idx)]
            query_tokens = _coverage_tokens(expanded)
            matches = query_tokens & _coverage_tokens(self.texts[int(idx)])
            coverage = len(matches) / len(query_tokens) if query_tokens else 0.0
            # Ranking is query-relative. Eligibility uses absolute evidence instead.
            answerable = (
                bool(query_tokens) and coverage >= 0.35
                and (len(matches) >= 2 or len(query_tokens) == 1)
                and (semantic_raw[idx] >= 0.14 or lexical_raw[idx] >= 2.0)
            )
            hits.append(
                RetrievalHit(
                    source_id=c.source_id,
                    title=c.title,
                    path=c.path,
                    text=c.text,
                    score=float(hybrid[idx]),
                    lexical_score=float(lexical[idx]),
                    semantic_score=float(semantic[idx]),
                    answerable=bool(answerable),
                    query_coverage=float(coverage),
                    raw_bm25=float(lexical_raw[idx]),
                )
            )
        return hits
