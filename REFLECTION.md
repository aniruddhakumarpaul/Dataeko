# Reflection

## Class imbalance and protecting Security/Fraud

The data is intentionally imbalanced, so accuracy is not my primary decision metric. I use a cost-sensitive logistic-regression classifier and report macro F1 in addition to accuracy. More importantly, Security/Fraud is treated as an asymmetric-risk class: a separate high-recall safety gate looks for explicit fraud, phishing, account-compromise, suspicious-login, credential-change, and OTP signals before ordinary routing. A ticket is escalated to Security/Fraud when that gate is strong or when the model's Security/Fraud probability crosses a conservative threshold. A lower review threshold ensures that a plausible security case cannot be silently routed as General Inquiry. Low-confidence cases are also held for human review.

The synthetic training file intentionally contains weak-label noise. Before training I quarantine rows where explicit security language conflicts with a non-security label, rather than teaching the classifier that obvious security incidents are harmless. I also evaluate a separate safety benchmark containing paraphrases not used as training templates. The key safety metric is the number of Security/Fraud cases silently routed to General Inquiry without review; the target is zero.

## Baseline before complexity

My baseline is word + character TF-IDF with multinomial one-vs-rest logistic regression and no class weighting. This is fast, deterministic, explainable, and appropriate for only ~500 loosely labeled examples. The production version adds explicit cost-sensitive class weights and the protected-class review gate. I would not start with an LLM classifier because the small/noisy dataset makes evaluation and calibration more important than model size, and the exercise requires zero cost.

## Evaluating retrieval grounding

Grounding is tested separately from classification. I maintain a small retrieval benchmark mapping representative user questions to the expected KB article and report Hit@3 and MRR@3. At runtime the response generator receives only the retrieved articles. A relevance threshold forces abstention when the KB is not a good match. With Ollama enabled, generated responses must cite only IDs from the retrieved set; citation validation failure falls back to an extractive answer. The app therefore has an explicit failure mode—"I could not find enough KB information"—instead of inventing policy or troubleshooting steps.

## First changes with real budget and data volume

First, I would invest in label quality and evaluation data: adjudicated ticket labels, a larger Security/Fraud challenge set, and production-derived retrieval judgments. Then I would replace heuristic safety detection with a separately trained high-recall risk model, calibrate per-class probabilities, add drift monitoring, and use a stronger local embedding/reranking stack. For generation I would evaluate a larger open-weight instruction model on citation faithfulness and policy compliance before increasing model size. I would also add PII redaction, audit logging, feedback capture from support agents, and an offline replay suite so model changes can be compared before deployment.
