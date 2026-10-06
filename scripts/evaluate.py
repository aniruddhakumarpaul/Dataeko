from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from triage.kb import load_kb  # noqa: E402
from triage.retrieval import HybridRetriever  # noqa: E402


def main():
    retriever = HybridRetriever(load_kb(ROOT / "kb"))
    bench = pd.read_csv(ROOT / "data" / "retrieval_eval.csv")

    rr = []
    hit_at_3 = []
    rows = []
    for _, r in bench.iterrows():
        hits = retriever.search(r["query"], k=3)
        got = [h.source_id for h in hits]
        expected = r["expected_source_id"]
        rank = next((i + 1 for i, x in enumerate(got) if x == expected), None)
        rr.append(1.0 / rank if rank else 0.0)
        hit_at_3.append(1.0 if rank else 0.0)
        rows.append({"query": r["query"], "expected": expected, "retrieved": got, "rank": rank})

    metrics = {
        "retrieval_backend": retriever.backend,
        "queries": len(bench),
        "mrr_at_3": sum(rr) / len(rr),
        "hit_rate_at_3": sum(hit_at_3) / len(hit_at_3),
        "details": rows,
    }
    (ROOT / "artifacts" / "retrieval_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "details"}, indent=2))


if __name__ == "__main__":
    main()
