# Architecture

Local setup and dependency details are documented in [environment.md](environment.md).
Import and setup decisions are recorded in [decisions.md](decisions.md).
The support workflow and presentation states are documented in [ui.md](ui.md).
Accounts, Employee IDs, support tickets, and email delivery are documented in
[support_workflow.md](support_workflow.md).

```mermaid
flowchart LR
    A[Customer submission] --> O[Authenticated tenant and owner]
    O --> H{Talk to a person?}
    H -->|yes| V[Commit direct-human ticket and outbox]
    V --> R[Tenant support inbox]
    H -->|no| C[Classifier plus safety policy]
    C --> D{Early human review required?}
    D -->|yes| Q
    D -->|no| G[Hybrid retrieval]
    K[Markdown knowledge base] --> G
    Q --> G
    G --> I{Sufficient evidence?}
    I -->|no, no ticket yet| Q
    I -->|no, ticket exists| R[Tenant support inbox]
    I -->|yes| J[Grounded draft and citation validation]
    J --> U[Update same ticket with optional assistance]
    U --> R
    Q --> R
    R --> S[Staff resolution and email update]
    O --> X[Opaque operation ID in URL]
    X --> Q
```

## Engineering choices

The classifier is intentionally small, inspectable, and cheap. With roughly 500 weak labels, a large fine-tuned model would add operational complexity without enough clean supervision to justify it. Word and character TF-IDF features provide a strong baseline for short support text, while class weighting corrects the dominant General Inquiry class.

Security/Fraud is handled as an asymmetric-risk class. A separate high-recall safety detector runs before normal routing, and a low Security/Fraud probability floor triggers human review even when another class wins. This avoids a design where a high aggregate accuracy hides dangerous minority-class failures.

Retrieval ranks with BM25 and local embeddings when available, or TF-IDF similarity
in the lightweight environment. Answer eligibility is separate from relative ranking:
it checks absolute similarity/raw BM25, query coverage, and meaningful matched terms.
Weak matches abstain and require review. Optional Ollama output must return structured
claims whose text exactly matches evidence in the cited article; otherwise extraction
is used. Valid citation identifiers alone are no longer sufficient.

The user-selected review threshold is 90%. The same review decision controls the
pipeline flag, customer UI, and support queue. Requests below that threshold, security
risks, unsupported queries, and explicit requests for a person create human-review
tickets. Account phone numbers are passed to the tenant's support team, separately
from model input. Ticket events and notification outbox writes are transactional.

`TriagePipeline.classify` runs classification and safety policy only; the retrieval
index is lazy and loads only when `complete` is called. The app uses the shared
classification review decision to commit a required ticket before retrieval or
generation. Direct-human submissions use only input validation and the deterministic
security signal detector before ticket commit; they do not load the classifier,
retriever, generator, or an external service. Later evidence review can create a
ticket when none exists, or update the same ticket's optional assistance fields.

Each customer submission uses a random 32-character hexadecimal operation ID in the
URL. TicketStore validates the format and scopes lookup and idempotent creation to
the authenticated owner and tenant. A unique SQLite request ID is authoritative;
starting a new request rotates the key, so matching message text alone never
deduplicates future incidents. Early ticket rows represent unavailable classifier
and draft values as null. Raw `classifier_confidence` is distinct from rule-based
security scores; legacy confidence values are not reinterpreted during migration.
