# Ticket triage interface

## Audience and primary task

A signed-in customer should be able to describe their issue, request help, and
follow their ticket and the response submitted by support. Staff have a separate,
role-restricted inbox for reviewing drafts and preparing customer responses.
The default screen uses a centered single-column layout with a neutral background,
dark text, and a green primary action. Native Streamlit controls provide labels,
keyboard interaction, focus indication, and responsive layout.

## Information priority

1. Customer message and one primary action: Analyze ticket.
2. Category and confidence, retained to satisfy the exercise brief.
3. Plain-language action when security review, category review, or manual handling
   is needed. Routine results do not show an extra routing banner.
4. Ticket receipt, status, callback information, and the engineer's submitted response.
5. Optional Help articles, collapsed initially and limited to relevant cited sources;
   internal source identifiers are omitted from their headings.

Generated suggested replies, draft downloads, staff review instructions, and
technical diagnostics are absent from the customer screen. Drafts are persisted
for the staff inbox's Suggested help article reply panel, with a staff review caption.

Examples are optional and collapsed. The architecture sidebar is removed.
Synthetic-data disclosure remains in a small footer.
Streamlit's developer toolbar is hidden in the support interface.

## Interaction and exceptional states

- Empty submissions request a customer message and do not run the pipeline.
- Examples populate the input and clear any previous result.
- Form submission analyzes the complete input in one action.
- Analysis results and ticket receipts persist across Streamlit reruns.
  Start over clears the input, example selection, and result, and starts a
  fresh submission operation.
- A required human-review ticket is committed before optional retrieval/generation.
  If those stages fail, the ticket receipt remains visible and its optional AI state
  is recorded as failed.
- Failed ticket writes show no receipt; the message stays available for a safe retry.
  A durable URL operation ID lets the retry reuse a committed ticket after refresh.
- Security notices explain the customer's escalation status rather than instructing
  a support agent to review a reply.
- Response abstention always requests manual handling, even when the classifier's
  own review flag is false. It never displays an unrelated help article.
  A security case with abstention shows both relevant
  explanations.

## Scope and verification

The initial presentation change was extended into the operational handoff described
in [support_workflow.md](support_workflow.md): Employee ID/email OTP onboarding,
tenant support queues, callback numbers, status/resolution updates, and private email.
The under-90% confidence case raises a ticket automatically. Direct human requests
remain available for any message. The original generic follow-up paragraph is removed
from extractive replies; the real support action is adjacent to the guidance.

The mailbox has email/password login, recipient/tenant filtering, Back to support,
Refresh inbox, and Sign out. Authentication and technical details are separate from
the primary customer flow. Demo identities and email transport are clearly labeled.
Local customer signup uses the same email and password for the inbox. The OTP step
survives refresh and offers resend and delivery retry; earlier codes are invalidated
after resend. A permanent inbox link remains available after support sign-in.

Streamlit 1.65 or newer is required for the UI's supported width APIs, matching the
tested lock file. AppTest covers empty input, persisted results, manual handling,
security review, security plus abstention, example changes, reset, and failure/retry.
Browser checks cover the actual local pipeline and desktop/mobile layouts.

Validation on 2026-10-06: `.venv\Scripts\python.exe -m pytest` passed all 104 tests,
including AppTest coverage for refresh-restored ticket receipts, early escalation,
and saved-ticket behavior after optional-stage failures. The earlier browser check
covered desktop and 390-pixel mobile widths with Billing, Security/Fraud, and
out-of-domain no-answer examples; no new live-browser visual pass was run for this
persistence phase.
