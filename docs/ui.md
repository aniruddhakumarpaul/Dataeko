# Ticket triage interface

## Audience and primary task

A support engineer should be able to paste a customer's message, understand its
category, see whether someone needs to review it, and prepare a first reply.
The default screen uses a centered single-column layout with a neutral background,
dark text, and a green primary action. Native Streamlit controls provide labels,
keyboard interaction, focus indication, and responsive layout.

## Information priority

1. Customer message and one primary action: Analyze ticket.
2. Category and confidence, retained to satisfy the exercise brief.
3. Plain-language action when security review, category review, or manual handling
   is needed. Routine results do not show an extra routing banner.
4. Suggested reply with inline citations and an optional Save reply action.
5. Help articles used, collapsed initially and limited to cited articles.
6. Technical details, collapsed initially, containing probabilities, retrieval scores,
   search/generation methods, and internal review explanations for evaluation.

Examples are optional and collapsed. The architecture sidebar is removed.
Synthetic-data disclosure remains in a small footer.
Streamlit's developer toolbar is hidden in the support interface.

## Interaction and exceptional states

- Empty submissions request a customer message and do not run the pipeline.
- Examples populate the input and clear any previous result.
- Form submission analyzes the complete input in one action.
- Successful results persist across Streamlit reruns; saving a reply does not rerun
  the app. Start over clears the input, example selection, and result.
- Failed analysis preserves the message, shows a short retry instruction, and logs
  the technical exception on the server rather than showing it to the user.
- Security review instructions identify the next action in plain language.
- Response abstention always requests manual handling, even when the classifier's
  own review flag is false. It never displays an unrelated article as a suggested
  reply or as an article used. A security case with abstention shows both relevant
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

Streamlit 1.65 or newer is required for the UI's supported width APIs, matching the
tested lock file. AppTest covers empty input, persisted results, manual handling,
security review, security plus abstention, example changes, reset, and failure/retry.
Browser checks cover the actual local pipeline and desktop/mobile layouts.

Validation on 2026-10-06: `python -m pytest` passed all 14 tests. The browser was
checked at desktop and 390-pixel mobile widths with Billing, Security/Fraud, and
out-of-domain no-answer examples. Review instructions and inline citations remain
visible while diagnostics stay collapsed.
