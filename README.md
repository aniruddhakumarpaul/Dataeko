# Support Ticket Triage Assistant

A zero-cost support triage system that combines **imbalanced multi-class ticket classification**, **protected Security/Fraud routing**, and **grounded knowledge-base retrieval** to draft a cited first response.

> **Data note:** the exercise brief's original CSV/KB were not included with this build, so this repository uses a clearly marked synthetic 500-ticket dataset and 15 synthetic help-center articles. Replace them with the provided files without changing the architecture.

## What the app does

1. Classifies a pasted ticket into **General Inquiry, Billing, Technical Issue, Feature Request, or Security / Fraud** and displays a confidence score.
2. Protects Security/Fraud with a high-recall safety gate and a conservative human-review threshold so a plausible security incident is not silently treated as General Inquiry.
3. Retrieves relevant KB articles with hybrid lexical + semantic search.
4. Drafts a response only from retrieved evidence and cites source IDs inline.
5. Abstains when retrieval is weak instead of fabricating an answer.

## Why this design

The task has ~500 noisy, heavily imbalanced examples. A large fine-tuned model is not automatically the best engineering choice. The classifier therefore starts from a strong, inspectable baseline: word + character TF-IDF with logistic regression. The final version adds cost-sensitive weighting and a separate protected-class gate. This makes the failure mode explicit and testable.

For RAG, the app uses hybrid retrieval. If `sentence-transformers` is installed it loads the open local model `BAAI/bge-small-en-v1.5`; otherwise it falls back to TF-IDF semantic similarity. BM25-style lexical scoring is always included. The response layer can use an open-weight Ollama model (`qwen3:4b` by default) but does not depend on it: a grounded extractive fallback keeps the demo functional on free hosting.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full diagram and rationale.

## Quick start

Use **Python 3.12** for the tested development environment. The Windows launcher
creates `.venv`, installs locked dependencies (including pytest), trains the classifier,
evaluates retrieval, runs tests, and launches the app:

```powershell
.\run_windows.ps1
```

To prepare and verify the environment without starting a server:

```powershell
.\run_windows.ps1 -SkipLaunch
```

On macOS/Linux, use `bash run_unix.sh` (or add `--skip-launch`). Existing data is
preserved. Regenerate synthetic fixtures only when intended, using `-RegenerateData`
on Windows or `--regenerate-data` on macOS/Linux. See
[`docs/environment.md`](docs/environment.md) for commands used during development.

Manual setup:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

python -m pip install -r requirements-lock.txt
python -m pip check
python scripts/train_classifier.py
python scripts/evaluate.py
python -m pytest
python -m streamlit run app.py
```

`requirements-lock.txt` captures the verified lightweight development environment;
`requirements-dev.txt` expresses runtime plus test dependency ranges for deliberate
upgrades. `requirements.txt` remains the smaller runtime-only hosting manifest.

For local sentence-transformer embeddings:

```bash
pip install -r requirements-full.txt
```

### Optional open-weight LLM through Ollama

The app works without an LLM. To enable local generation:

```bash
ollama pull qwen3:4b
# Windows PowerShell
$env:USE_OLLAMA="1"
$env:OLLAMA_MODEL="qwen3:4b"
streamlit run app.py
```

macOS/Linux:

```bash
export USE_OLLAMA=1
export OLLAMA_MODEL=qwen3:4b
streamlit run app.py
```

Only retrieved KB text is supplied to the generator. If citations are missing/invalid, the system falls back to a deterministic grounded response.

## Data and label-noise handling

`data/tickets.csv` contains exactly 500 synthetic tickets with an intentionally skewed distribution and deliberate weak-label noise. `scripts/train_classifier.py` audits explicit security signals that conflict with a non-security label and quarantines those rows before training. This is a defensive data-quality step, not silent relabeling.

`data/safety_eval.csv` is a separate challenge set used to measure the protected-class rule. The key metric is:

**Security/Fraud tickets silently routed as General Inquiry without human review = 0**

Because the protected class is tiny, a single holdout split is not enough evidence for production. The safety challenge set is included precisely to make that limitation visible.

## Evaluation

Run:

```bash
python scripts/train_classifier.py
python scripts/evaluate.py
```

Classifier metrics are written to `artifacts/metrics.json`; retrieval metrics are written to `artifacts/retrieval_metrics.json`. Generated model weights remain ignored by Git.

Metrics reported:

- Accuracy (context only)
- Macro F1 (primary overall classification metric)
- Weighted F1
- Raw model Security/Fraud recall
- Protected Security/Fraud safe-handling rate
- Silent Security/Fraud → General Inquiry misroutes
- Retrieval Hit@3 and MRR@3


## Reproducible benchmark from the bundled synthetic data

| Metric | Result |
|---|---:|
| Baseline macro F1 | 0.685 |
| Final cost-sensitive macro F1 | **0.879** |
| Final weighted F1 | **0.946** |
| Security/Fraud safe-handling challenge set | **100% (15/15)** |
| Silent Security/Fraud → General Inquiry misroutes | **0** |
| Retrieval Hit@3 | **100%** |
| Retrieval MRR@3 | **0.967** |
| Tests | **6/6 passing** |

See [`docs/EVALUATION.md`](docs/EVALUATION.md) for the detailed report and caveats. The Security/Fraud holdout contains only one row, so the separate 15-case challenge set is intentionally reported alongside it.

## Grounding / hallucination controls

The system does **not** assume that retrieval always found an answer.

- A minimum relevance threshold gates generation.
- Below threshold, the app explicitly abstains.
- The LLM prompt forbids using facts outside retrieved KB context.
- Only open-weight Ollama inference is supported.
- Generated citations must match retrieved source IDs.
- Invalid LLM output falls back to an extractive grounded response.

This does not prove zero hallucinations under every possible input; it creates measurable, enforceable boundaries and a safe fallback.

## Free deployment

### Streamlit Community Cloud

Use `requirements.txt` for the smallest reliable deployment. The app will use TF-IDF semantic retrieval plus BM25 and the deterministic grounded response fallback, so no paid key or GPU is required.

1. Push this repository to GitHub.
2. Create a Streamlit Community Cloud app.
3. Set the main file to `app.py`.
4. Deploy.

If you prefer the sentence-transformer backend on a host that can install PyTorch, use `requirements-full.txt` instead.

## Tests

```bash
pytest
```

Tests cover the security gate, high-value retrieval cases, protected-class routing, and the no-KB-match abstention path. GitHub Actions runs data generation, training, and tests on every push/PR.

## Known limitations

- Synthetic data cannot reproduce real ticket language, annotation error, or production drift.
- Only four Security/Fraud labels exist in the synthetic dataset (three in the training split), so the lexical safety gate carries meaningful responsibility.
- Logistic-regression probabilities are useful scores but are not fully calibrated probabilities. With more data I would add per-class calibration.
- The lightweight hosted path uses a deterministic fallback rather than an LLM; local Ollama provides the richer generative path.
- The 15-article KB is too small to stress-test chunking, ANN indexing, or cross-encoder reranking.

## Submission artifacts

- Working app: `app.py`
- Source package: `src/triage/`
- Synthetic ticket data: `data/tickets.csv`
- Synthetic KB: `kb/`
- Evaluation scripts: `scripts/`
- Reflection: [`REFLECTION.md`](REFLECTION.md)
- Architecture notes: [`docs/architecture.md`](docs/architecture.md)
- Demo / submission checklist: [`SUBMISSION.md`](SUBMISSION.md)
