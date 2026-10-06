# Evaluation Report

This report is generated from the bundled synthetic dataset with a fixed random seed. It is evidence for engineering behavior, not a claim about production accuracy. The Security/Fraud holdout contains only one example, so the dedicated challenge set is the more useful safety check.

The classifier and retrieval figures below were recorded from the synthetic
benchmark. Their fresh pre-upgrade reproduction and the current test count are
reported separately at the end of this document. See [environment.md](environment.md)
for setup and verification details. Remote CI and optional Ollama/embedding paths
remain unverified in this local run.

## Dataset

- Total tickets: **500**
- Class counts after intentional weak-label noise: {'General Inquiry': 392, 'Billing': 43, 'Technical Issue': 32, 'Feature Request': 29, 'Security / Fraud': 4}
- Label conflicts quarantined before training: **1**
- Security/Fraud prevalence: **0.8%**

## Classifier comparison

| Metric | Baseline (unweighted) | Final (cost-sensitive) |
|---|---:|---:|
| Accuracy | 0.944 | 0.952 |
| Macro F1 | 0.685 | **0.879** |
| Weighted F1 | 0.934 | **0.946** |
| Raw Security/Fraud recall | 0.000 | **1.000** |

The baseline misses the rare Security/Fraud holdout case entirely. The cost-sensitive model recovers it while also improving macro and weighted F1. Because the holdout support is only one Security/Fraud row, this result is not treated as statistically sufficient by itself.

## Final per-class holdout metrics

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| General Inquiry | 0.961 | 1.000 | 0.980 | 98 |
| Billing | 0.846 | 1.000 | 0.917 | 11 |
| Technical Issue | 1.000 | 0.500 | 0.667 | 8 |
| Feature Request | 1.000 | 0.714 | 0.833 | 7 |
| Security / Fraud | 1.000 | 1.000 | 1.000 | 1 |

## Security/Fraud challenge set

- Protected cases: **15**
- Safely handled (Security/Fraud route or explicit human review): **100%**
- Silent Security/Fraud → General Inquiry misroutes: **0**
- Non-security challenge cases incorrectly forced to Security/Fraud: **0%**

The target safety invariant is simple: **a plausible Security/Fraud case must never be silently routed as General Inquiry.** The challenge set currently satisfies that invariant.

## Retrieval grounding benchmark

- Backend used for this run: **tfidf**
- Queries: **15**
- Hit@3: **100.0%**
- MRR@3: **0.967**

The production app additionally applies an absolute relevance gate. An out-of-domain query with zero lexical/semantic support is rejected before response drafting.

## Test suite

Earlier reports recorded smaller test counts (6, 14, and later 68) as the suite grew.
They describe those runs only; they are not the current suite size. The pre-upgrade
reproduction below reports the current exact count. The test suite covers account/OTP
lifecycle, tenant and owner authorization, independent mailbox access, automatic
escalation below 90%, direct human requests, out-of-domain keyword overlap, unsupported
generated claims, persistence, status updates, retries, and concurrent/stale updates.
This remains synthetic/local evidence, not a claim of production accuracy or zero
failures for arbitrary future inputs.

Browser verification completed an Employee ID registration, email OTP in a separately
authenticated demo mailbox, automatic ticket creation for an 87.07% Billing result,
staff receipt of the callback number, a recorded resolution, and the customer's
private resolution email. The mailbox Back to support link restored the OTP step.
Retraining retained macro F1 0.8793, weighted F1 0.9463, challenge safe handling 15/15,
Hit@3 1.0, and MRR@3 0.9667. The 90% review threshold affects routing, not raw model F1.

The subsequent demo password-policy update was checked with 8 focused account/password
tests and 1 mailbox test. These verified short and long demo passwords, registration
with a one-character password, matching password verification, empty-password rejection,
and retention of the non-demo policy. The 68-test workflow run above predates this
small follow-up; it was not repeated for this change.

## Fresh pre-upgrade baseline reproduction

On 2026-10-06, the unchanged application, classifier, retrieval code, data, and KB were
run in the project `.venv` with Python 3.12.10 and the locked lightweight environment.
`USE_OLLAMA=0`; retrieval used TF-IDF fallback and no optional model was downloaded.
The pre-run metrics are preserved byte-for-byte in `artifacts/baseline/`. The manifest
at `artifacts/baseline_manifest.json` records the commit, dependency versions and lock
hashes, dataset and KB hashes, backend, thresholds, and test summary. The reproduction
commands were `python -m pip check`, `scripts/train_classifier.py`,
`scripts/evaluate.py`, and `python -m pytest --junitxml=<temporary-junit-report>` using
the `.venv` Python executable.

| Metric | Recorded | Reproduced | Delta |
|---|---:|---:|---:|
| Classifier accuracy | 0.952 | 0.952 | 0 |
| Macro F1 | 0.8793333 | 0.8793333 | 0 |
| Weighted F1 | 0.9463200 | 0.9463200 | 0 |
| Raw Security/Fraud holdout recall | 1.000 | 1.000 | 0 |
| Protected challenge safe handling | 15/15 (100%) | 15/15 (100%) | 0 |
| Silent Security/Fraud → General Inquiry challenge misroutes | 0 | 0 | 0 |
| Non-security challenge forced to Security/Fraud | 0% | 0% | 0 |
| Retrieval Hit@3 | 1.000 | 1.000 | 0 |
| Retrieval MRR@3 | 0.9666667 | 0.9666667 | 0 |
| Full test suite | 68 passed in the prior report | 86 passed | +18 collected cases |

The Security/Fraud holdout recall still has support of only one ticket. The challenge
suite is targeted rather than prevalence-representative. The test-count difference
reflects the older report and later test-suite growth; the current run also includes
three new baseline-manifest tests. It is not a model-quality comparison.

`pip check` returned “No broken requirements found.” Training and retrieval evaluation
exited successfully, and all four recorded metric comparisons were identical. The
first full test attempt exposed AppTest limitations: its browser URL and cookie context
were absent, and two assertions still expected the removed “Manual reply needed” copy.
The test fixture now supplies a local URL and empty cookie mapping, and those assertions
check the approved sentence. This changes test setup and expectations only; no app,
classifier, retrieval, generation, KB, data, ticket, or authentication behavior changed.
The final full run passed 86/86 with no failures, errors, or skipped tests. Classifier,
safety, and retrieval metrics all matched the preserved values; no unexplained metric
drift remains.
