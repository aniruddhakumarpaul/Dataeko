# Support triage improvement plan

Prepared on 2026-10-06. This plan is based on the local source and supplied analysis.
The early human-ticket persistence slice is recorded as delivered below; the
remaining evidence, evaluation, and model changes are still proposed and are not
approved for public deployment.

## Decision

Freeze the evaluation baseline and persist required human handoffs before optional
AI stages, then strengthen evidence handling and evaluation. Adopt semantic models
only when a controlled comparison demonstrates an improvement. Keep deterministic
Security/Fraud escalation and the customer's direct-human option independent of
model generation.

No architecture can promise that arbitrary future messages will always be
classified correctly or that every cited answer will be applicable. A defensible
guarantee is narrower: accepted automated factual text can be restricted to
complete, approved evidence blocks, with citations constructed by the application.
Source accuracy, policy applicability, answer completeness, and routing recall
must still be evaluated separately.

## Findings from the current code

| Finding | Evidence | Implication |
|---|---|---|
| Structured generation and exact-source validation already exist | src/triage/generation.py, _validated_claims | Avoid replacing this control with a weaker probabilistic verifier. |
| The answerable field measures overlap and similarity | src/triage/retrieval.py, search | A related article may still omit the requested fact. |
| Both retrieval backends share an absolute semantic threshold of 0.14 | src/triage/retrieval.py | TF-IDF and dense model score distributions need separate validation. |
| Fallback selects the first paragraph and truncates it at 560 characters | src/triage/generation.py, _extractive_fallback | It can omit the relevant action or a qualifying condition. |
| Citation IDs depend on sorted file position | src/triage/kb.py, load_kb | Adding an earlier filename can change existing source identities. |
| Security confidence can combine a rule score and classifier probability | src/triage/classifier.py, classify_ticket | The displayed percentage is not consistently a calibrated probability. |
| Training uses a random stratified row split over template-generated data | scripts/train_classifier.py; scripts/generate_synthetic_data.py | Template families may occur on both sides. Generalization requires a separate evaluation. |
| The documented security holdout has one example; the safety challenge has 15 protected cases | docs/EVALUATION.md | Passing these cases does not establish population-wide security recall. |
| The KB is shared globally | app.py, load_pipeline; src/triage/kb.py | This is acceptable for the current shared demo KB. Future private tenant KBs must be filtered before retrieval. |
| Optional generator failure falls back without a structured failure record | src/triage/generation.py | Reports may hide that an enhanced backend was unavailable. |
| Automatic escalation follows the complete pipeline run | app.py, submission handler | Generation latency can delay a ticket whose classification already requires review. |

The pasted Billing > Transactions example is illustrative, not a current product
procedure. Actual KB-004 distinguishes temporary authorizations from posted
charges and describes what to send to support. Do not introduce the illustrative
procedure as product guidance.

Existing synthetic metrics remain useful as a reproducibility baseline:
macro F1 0.8793, weighted F1 0.9463, protected challenge handling 15/15, and
retrieval MRR@3 0.9667. These are recorded results, not newly rerun measurements
or expected performance on real tickets.

## Corrections to the supplied proposal

1. Semantic classification is a candidate, not an automatic improvement. Compare
   lexical, frozen-embedding, and combined features on the same independent data.
2. Calibration maps model scores using separate labeled data. It does not make a
   particular 90% prediction a guarantee. Keep the user's below-90% review rule,
   but distinguish calibrated class probability from rule-based risk.
3. A retrieval cross-encoder scores relevance. It is not inherently an
   answerability model.
4. NLI examines whether an evidence premise supports a declarative claim. Passing
   a question and an article to a generic NLI model does not prove that the article
   answers every part of the question.
5. An NLI acceptance is a model judgment, not a deterministic proof. Use it for
   additional rejection or staff diagnostics; it cannot override strict evidence
   membership or authorize unsupported paraphrases in the strict mode.
6. Checking that a number occurs somewhere in evidence is insufficient. The unit,
   object, condition, negation, and time qualifier must also match.
7. Ordinary conformal coverage is marginal under its sampling assumptions, not a
   guarantee for each prediction or for a rare security class. Defer it until
   sufficiently representative calibration data exists.
8. Exact quotations can still be obsolete, irrelevant, malicious, incomplete, or
   inapplicable. Add trusted publication and applicability controls.
9. No paid inference API is feasible. Hardware, downloads, memory, latency, and
   hosting limits must still be measured; total operational cost is not literally zero.

## Proposed flow

    Authenticated request
        -> resolve tenant and owner on the server
        -> direct-human override, independent security assessment, classification
        -> commit required support ticket immediately
        -> retrieve authorized, current KB evidence
        -> optional dense retrieval and cross-encoder ranking
        -> assess requested facts and evidence applicability
        -> select complete evidence blocks
        -> validate IDs, versions, permissions, conditions, and coverage
        -> render citations and approved text deterministically
        -> answer, qualified partial guidance plus review, or abstention plus review

The generator and reranker have no permissions to create accounts, update tickets,
send arbitrary email, or read other tenants' data. Business actions are controlled
by validated server-side application code.

## Phase 1: Fix evidence contracts

Create stable article IDs in metadata and an immutable corpus version. Each
approved evidence block records article ID, block ID, complete text, content hash,
source offsets, tenant/shared visibility, supported intent, prerequisites,
effective dates, and policy version. Persist the cited version with each reply.

For the current 15-article KB, manually reviewing complete answer blocks is
manageable. Keep conditions and their associated actions together. Never cut a
policy sentence at a character boundary or choose the first paragraph solely
because it appears first.

Separate relatedness from sufficiency. Use three internal states: sufficient,
partial, and insufficient. For unsupported details, mark the affected issue
unanswered and route it for review. Do not label a partial reply as a complete
resolution. Ambiguous or contradictory policy goes to review.

Initially support a bounded catalog of known intents and required facts.
Unrecognized or ambiguous requests must abstain rather than allowing an LLM to
certify its own coverage. This intentionally favors review over answer coverage.

### Required-fact matrix and applicability

Define required facts for each supported intent explicitly. Evidence blocks must
declare which facts they support, not merely which topic they mention.

| Supported intent | Required facts |
|---|---|
| duplicate_charge.report | posted-charge condition; support submission action; requested supporting details |
| duplicate_charge.refund_timing | applicable refund timeframe; its qualifying conditions |
| duplicate_charge.refund_status | account-specific refund state from an authorized system or verified staff |

Match all requested issues, then check coverage for each issue separately. A fully
covered reporting question does not make an unanswered refund-timing question
complete. Metadata is reviewed against actual article text; a generated supports
field cannot establish evidence by itself.

Condition handling distinguishes known applicable, known inapplicable, and unknown.
Unknown account facts must not be treated as confirmed. Approved general guidance
may retain an explicit conditional instruction, but a personalized assertion about
eligibility or status requires an authorized record or staff verification.

Coverage checks can be deterministic after intent mapping and metadata approval.
Intent recognition, source interpretation, and condition assessment remain possible
failure points. Ambiguous intent mapping, unknown required account facts, or
conflicting evidence keeps the request in review.

Example: a duplicate-charge article without a refund duration may support how to
request investigation, but cannot answer when the money will arrive. Account
eligibility and completed refunds require authorized system records or staff
confirmation; generic KB text cannot establish them.

Both extractive fallback and optional generation must use the same validator and
renderer. Source HTML/Markdown is sanitized before display. Publication review,
not the generation prompt alone, prevents instructions embedded in KB text from
being presented as approved procedure.

Acceptance: stale/foreign/unknown evidence is rejected; conditions remain intact;
unsupported timelines are not rendered; partial answers retain review; citations
survive file additions and refer to the version used for the response.

## Phase 2: Repair the evaluation design

Freeze the current baseline and label new evaluation examples independently of
training templates. Track template family, duplicate cluster, label source, and
label-review status. Keep groups out of multiple splits. Use chronological
holdout where genuine ticket history is available.

Maintain separate training, tuning/calibration, and untouched final evaluation
data. With the current tiny security sample, do not force unstable five-class
cross-validation or claim robust security calibration. Add reviewed security data
and keep the independent safety route while that gap remains.

Proposed initial take-home evaluation scope, subject to label availability:

- 150–200 independently written classification cases.
- A separate safety suite with 50–75 security incidents and 50–75 benign
  security lookalikes.
- 75–100 RAG cases covering complete, partial, no-answer, numerical traps,
  conflicts, injection, and mixed requests.

Keep final evaluation cases separate from tuning/calibration. The safety suite is
reported separately from a prevalence-representative classification sample. The
current scarcity of security training/calibration labels remains a distinct issue;
reducing test scope does not resolve it.

Expanded evaluation scope for a subsequent internal deployment:

- At least 300 independently written classification examples across five classes.
- A separate challenge suite with at least 100 diverse security scenarios and
  100 benign lookalikes, including quoted attacks, negation, misspellings, indirect
  incident descriptions, mixed intents, and explicit human requests.
- At least 150 RAG queries covering complete answers, partial answers, no answer,
  keyword-overlap negatives, conflicting policies, numerical traps, injection,
  long inputs, and private-tenant sources.

These are proposed sample sizes, not a proof of production safety. Challenge sets
are targeted tests, not random population samples. Augmented variants of one
template do not count as independent evidence.

Report per-class precision/recall/F1, confusion matrices, security false negatives
and benign escalation rate, automated-route error rate versus coverage, Brier/log
loss and reliability plots, evidence Recall@k/MRR/nDCG, answerability errors,
unsupported-claim rate, completeness, citation correctness, and p50/p95 latency.
Report sample counts and appropriate uncertainty intervals for representative
held-out estimates; do not apply population intervals to convenience challenge cases.

## Phase 3: Compare semantic classification

Evaluate three candidates: the existing word/character TF-IDF classifier,
class-balanced logistic regression over frozen sentence embeddings, and a model
combining lexical and embedding features. Use BGE-small or MiniLM as initial
candidates, not preselected winners. Treat encoder fine-tuning/SetFit as a later
experiment if frozen features demonstrably underperform.

Separate predicted category probability, security risk signals, and review
reasons in the data contract. Preserve all five categories. A mixed-intent ticket
can have issue-level evidence needs while a security signal raises the entire
request's handling priority.

Calibrate on disjoint, representative data using a method selected on tuning
data. The security rule score must never be displayed as calibrated probability.
Evaluate the error and throughput of the below-90% policy explicitly. Calibration
data should reflect intended prevalence rather than an artificially balanced
sample unless an appropriate adjustment is justified.

Promote a candidate only for a meaningful held-out benefit, acceptable calibration,
and no safety or latency regression. If evidence is inconclusive, retain the
baseline. Do not adjust the final test set or thresholds after seeing its results.

## Phase 4: Compare retrieval and reranking

Evaluate current hybrid retrieval, BM25 plus dense embeddings with reciprocal rank
fusion, and those candidates with a cross-encoder. A small MS MARCO MiniLM
cross-encoder is an initial candidate. Pin its revision and confirm its license.

At this corpus size, benchmark scoring all approved passages against scoring only
the fused top candidates. Top six is a starting parameter, not a requirement.
Use in-memory indexes; a vector database is unnecessary unless measured scale or
filtering requirements justify one.

Use backend-specific answer eligibility thresholds selected on held-out negatives.
Never reuse the TF-IDF cosine threshold as a dense-model probability threshold.
Preserve absolute rejection checks: reciprocal rank fusion always creates an
ordering even when every document is a poor answer.

Every private-source index and cache is scoped to tenant, corpus version, and model
revision. Shared approved documentation must be explicitly identified as shared.

Acceptance: improved evidence retrieval on the expanded benchmark without worse
false-answer acceptance, isolation failures, or unacceptable p95 latency.

## Phase 5: Optional constrained Qwen selection

Use a pinned local Qwen3-4B/Ollama installation only after measuring available RAM,
model loading, concurrency, and response latency. The lightweight hosted mode must
remain runnable without Ollama or model downloads.

Give the model a small approved evidence packet. Have it select evidence block IDs
through a strict JSON schema with bounded array length and no extra properties.
The application reconstructs complete block text and citations from the catalog;
the model cannot supply arbitrary final facts, citation labels, or callback promises.
Validate the schema and each selected ID again server-side.

Permit an empty selection as abstention. Do not accept a generated complete=true
field as proof of answer completeness. NLI, if added, uses evidence as premise
and a proposed claim as hypothesis; verify label mapping and truncation handling,
benchmark it on domain counterexamples, and use it only as an additional rejection
signal in strict mode.

Do not delete an unsupported sentence and silently call the rest complete.
Reject the affected issue or dependent claim group, then use validated fallback
blocks or human review. Default to no automatic generation retry; permit one
bounded retry only if measured benefit justifies the total latency budget.

Record model/backend versions, selected evidence IDs, rejection reason codes,
stage timings, and fallback usage. Redact private text from general diagnostics.

## Phase 6: Reliable human handoff and clean UX

Direct human service, security risk, confidence below 90%, and absent sufficient
evidence all trigger support handling. Commit tickets before slow generation when
review is already known. If sufficiency fails later, create the ticket at that
point. Generator failure must not prevent an already-required ticket from existing.

Use a durable request operation ID and transactional uniqueness for retries,
refreshes, worker restarts, and email events. Do not deduplicate every future
ticket solely by matching text; customers can have repeated incidents.
Queued email and a saved ticket are separate states. Show a ticket receipt only
after the database commit, and expose retry/recovery if saving fails.

Keep the customer's chosen abstention copy:

> A support engineer will review it and resolve it at the earliest.

Show the ticket number/status and the direct-human action beside it. Category and
confidence remain available for the exercise, with technical diagnostics collapsed.
Pass callback details to authorized staff, retain assigned executive/status
history, and make callback timing a recorded request rather than a guaranteed call.
Verified staff resolution triggers the existing customer email outbox.

Acceptance includes login-refresh persistence, sign-out revocation, customer/staff
and tenant boundaries, duplicate-submit handling, generator outages, SMTP failure,
database-write failure, and concurrent staff resolution.

### Early human-ticket persistence phase

This delivery implements the ticket-persistence slice first; it does not begin the
evidence-contract or required-fact work above. `TriagePipeline.classify` exposes the
classifier/safety result without loading the KB. The app applies the shared review
policy and commits a required ticket plus its notification outbox before calling
retrieval or generation. The direct-human path commits from authenticated input and
the deterministic safety signal only, without loading the model or retrieval stack.

The browser URL carries an opaque random 128-bit operation ID. It is validated as a
32-character lowercase hexadecimal value, persisted as the ticket's unique request
ID, and resolved only within the authenticated tenant/owner scope. Reusing it returns
the original ticket; **Start over** creates a new ID, so identical message text can
raise a later incident. SQLite's immediate transaction serializes duplicate creates.

Ticket persistence records explicit AI-assistance states and nullable fields instead
of fabricated drafts. New model confidence is stored separately from security/rule
signals. Existing ticket rows/events are preserved by the nullable-field migration;
legacy confidence values are not reinterpreted. Ticket and outbox writes commit
together, while the SMTP retry worker runs independently. A later evidence abstention
reuses an early ticket or creates one with the same operation ID if none exists.

The evidence contracts, required-fact matrix, new datasets, classifiers, retrieval
ranking, generation grounding, and model/retrieval metrics remain unchanged in this
phase. No metric improvement is claimed.

## Release gates and rollback

| Gate | Required evidence |
|---|---|
| Source control | Stable IDs, versioned approved evidence, intact qualifiers, tenant filtering |
| Grounding | All supported facts rendered from validated blocks; no unsupported promises in the release suite |
| Review | All known security and explicit-human challenge cases reach review; below-90% boundary is preserved |
| Evaluation | Independent held-out comparisons, counts, uncertainty, quality/coverage trade-offs |
| Operations | Successful browser journey and controlled failures; durable tickets and scoped notifications |
| Performance | Measured memory, cold start, concurrency, p50/p95 latency in the target environment |
| Reproducibility | Locked packages, model revisions/licenses, dataset/corpus hashes, seed and run manifest |
| Submission | Brief mapping, public code hygiene, accurate README/reflection, recording or supported free demo |

Zero observed violations is a release criterion for the defined suite, not a
universal guarantee. A release blocker prevents promoting the enhanced path.
Backend configuration can return to the approved lexical/extractive mode without
altering ticket history. Bad or conflicting KB evidence requires review; replacing
a neural model with lexical retrieval does not repair invalid source material.

## Primary-source evidence and limits

Sources were checked on 2026-10-06. Documentation describes APIs; it is not evidence
that a model improves this project's metrics.

| Source | Support | Limit |
|---|---|---|
| [scikit-learn calibration API](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV) | Calibration fitting must be separated from model fitting | Does not establish probability quality with the current sparse labels |
| [Sentence Transformers retrieve/rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) | Cross-encoders rank query/passage relevance; tiny collections can be scored directly | Does not prove answer completeness or gains in this KB |
| [BGE-small model card](https://huggingface.co/BAAI/bge-small-en-v1.5) | MIT license; similarity thresholds depend on the task's score distribution | Provider benchmarks are not local evaluation |
| [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) | The format field can enforce a JSON schema | Schema compliance alone does not establish semantic correctness |
| [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B) | Apache-2.0 weights and local runtime support | Hardware feasibility and this task's quality remain unmeasured |
| [McCoy et al., ACL 2019](https://aclanthology.org/P19-1334/) | NLI models can exploit overlap heuristics and fail controlled counterexamples | Historical models do not quantify the error of a proposed modern verifier |
| [Angelopoulos and Bates, conformal introduction](https://arxiv.org/abs/2107.07511) | Ordinary coverage concerns prediction sets and sampling assumptions | It is not a per-ticket or rare-class correctness certificate |

Implementation order: freeze the baseline -> immediate human-ticket persistence ->
evidence contracts and required-fact matrix -> independent evaluations -> classifier
comparison/calibration -> retrieval comparison -> optional constrained selection ->
operational failure checks and submission. Ticket persistence is an early delivery
priority even though its complete workflow requirements are grouped in Phase 6.
Each phase has its own report; no claimed metric improvement precedes a measured
comparison.
