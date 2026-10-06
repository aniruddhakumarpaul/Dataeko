# Evaluation Report

This report is generated from the bundled synthetic dataset with a fixed random seed. It is evidence for engineering behavior, not a claim about production accuracy. The Security/Fraud holdout contains only one example, so the dedicated challenge set is the more useful safety check.

The rounded results below were reproduced locally on 2026-10-06 with Python 3.12.10
and the versions captured in `requirements-lock.txt`. All 6 tests passed; the local
browser check covered Billing with KB citations, protected Security/Fraud routing,
and the out-of-domain abstention path. See [environment.md](environment.md) for
setup and verification details. Remote CI and optional Ollama/embedding paths
remain unverified in this setup run.

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

The six backend tests cover security-signal detection, normal billing non-escalation,
unauthorized-charge retrieval, password-reset retrieval, the protected routing
invariant, and RAG abstention for an out-of-domain query. Eight UI tests additionally
cover empty input, persisted results, manual handling, security review, security with
abstention, examples, reset, and failure/retry. After the UI update, the current local
run originally passed **14/14 tests**. The subsequent workflow/security update passes
**68/68 tests**, including account/OTP lifecycle, tenant/owner authorization, independent
mailbox access, automatic escalation below 90%, direct human requests, out-of-domain
keyword overlap, unsupported generated claims, persistence, status updates, retries,
and concurrent/stale update handling. This remains synthetic/local evidence, not a
claim of production accuracy or zero failures for arbitrary future inputs.

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
