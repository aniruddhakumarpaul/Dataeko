# Engineering decisions

## 2026-10-06: Import and local development setup

The connected repository contained only a placeholder README. Imported the supplied
`support-ticket-triage-assistant.zip` into the repository root, preserving its Git
history and remote. The archive did not include the original exercise brief or real
Dataeko data; claims about brief compliance remain unverified.

Use Python 3.12 with a project-local `.venv`. Keep hosting dependencies in
`requirements.txt`, development dependencies in `requirements-dev.txt`, and the
tested lightweight environment in `requirements-lock.txt`. Optional sentence-transformer
and Ollama enhancements are separate from this baseline.

The original launchers called pytest without installing it, depended on shell
activation, and regenerated ticket data on every launch. Windows native process
failures were not explicitly checked. Launchers now use the environment's Python
directly, install the locked development environment, check each command, and
preserve existing fixtures by default. Explicit regeneration remains available.
`-SkipLaunch` / `--skip-launch` prepares and verifies the environment without a server;
`-SkipInstall` / `--skip-install` reuses installed dependencies.

CI uses the same Python version and lock file, evaluates retrieval, and tests the
committed fixtures rather than replacing them. No GitHub publication or deployment
is part of this environment-setup change.

## Follow-up issues observed during verification

- In the cafeteria no-answer example, classification reports human review is not
  required while the abstention message recommends manual handling. Consider a
  pipeline-level review decision that incorporates response abstention.
- Streamlit 1.65.0 reports deprecated `use_container_width` calls. Replace them with
  supported width arguments when updating the UI, with a matching runtime version
  requirement.
- Training and first-boot app fitting use different sample sets (training split
  versus all cleaned rows). Make model provenance explicit before claiming demo
  behavior and evaluation cover the same fitted model.

## 2026-10-06: Simplify the support interface

The primary user needs a customer message, category/confidence, review action, and
suggested reply. Remove the architecture sidebar and move probabilities, retrieval
scores, and generation methods into a collapsed Technical details panel. Show only
cited help articles in the optional sources panel. Use plain language for review
and no-answer messages. Preserve results through reruns and provide reset/save
actions. See `docs/ui.md` for the interaction specification.

The earlier no-answer presentation inconsistency is resolved at the UI layer:
response abstention always asks for manual handling. Backend routing and grounding
findings remain separate. The earlier placeholder-only state describes the time of
import.

## 2026-10-06: Employee accounts and operational human handoff

The user requested tenant-level accounts, phone/password plus email OTP, real raised
tickets, callback contact handoff, email status updates, and an always-available
direct human-service action. They subsequently replaced shared organisation-code
entry with individual Employee IDs and required automatic escalation below 90%.
Employee IDs are assigned to an email/phone and resolve the tenant on the server.
Registration passwords activate only after email verification. Public registration
cannot grant staff roles. Staff and customers see tenant/owner-scoped records.

Use SQLite and a transactional email outbox for the local prototype. Callback
requests and resolutions are persisted; failed email delivery does not discard them.
Retain legacy unowned records without exposing them to new tenant users.
Demo executive identities are labeled fictional and two-minute callback timing is
a requested preference, never a claim that a real call was scheduled.

No SMTP provider credentials or owned domain were supplied. The user's request for
a Dataeko email identity is implemented as the explicit local sender
`dataeko@support.test` with an SMTP receiver and private mailbox UI. It is not a
public email account. Mailbox passwords are separate from support passwords, and
each mailbox is scoped to its recipient and tenant. Back to support preserves the
local OTP challenge; no authentication is granted without successful verification.

The earlier audit's security paraphrases, sparse-overlap abstention, and unsupported
claim acceptance received regressions and fixes. Confidence below 90% is a user
policy rather than a threshold claimed to be empirically calibrated. Current local
verification passed 68 tests and a browser journey from OTP signup through automatic
ticket raising, staff contact handoff, resolution, and a private update email.

## 2026-10-06: Relax password policy in the demo

The user explicitly requested unrestricted demo passwords. Local demo support and
mailbox accounts now accept any non-empty password, including one character and
more than 128 characters. The form guidance matches that behavior. Non-demo support
registration retains its existing length policy. Password hashing and verification,
email OTP, tenant boundaries, and existing credentials are preserved.

## 2026-10-06: Custom testing accounts

The user requested free account creation during testing with IDs shaped like
`EM-2026`. Uninvited local-demo registration now validates EM- plus four digits,
accepts tester-entered name/phone/email, and creates a customer account in the
server-selected Dataeko demo tenant. Account, invitation binding, and private inbox
creation are transactional. Existing IDs and contact accounts cannot be replaced,
and the flow cannot grant staff privileges. Assigned registration outside the demo
is preserved. Separate inbox credentials are shown only in the registering user's
OTP step and cleared after verification. Seven focused backend cases and three
authentication UI cases passed for this update.

## 2026-10-06: Persist support login across refresh

Streamlit session state is cleared by a full browser refresh, which discarded the
support login even while its server-side session remained valid. Keep the existing
random session token in an eight-hour SameSite=Strict browser cookie, resolve it
against the hashed server-side session on each page load, and clear/revoke it on
sign-out. Set the Secure cookie flag when the app URL uses HTTPS. The local prototype
uses a browser-side cookie component; production deployment should use an
HttpOnly cookie set by the server.

## 2026-10-06: Persist early human-review tickets

Requests that already require a person now persist a ticket before optional retrieval
and generation. The direct-human path does not load the classifier or retrieval stack.
`review_decision_from_classification` is the shared early policy; the final evidence
decision extends it without replacing an existing handoff. A later model failure
marks assistance failed while preserving the Open ticket and its original priority.

The authenticated customer URL stores an opaque random operation ID, while SQLite's
unique request ID and tenant/owner checks enforce idempotency. The same ID returns the
same ticket across refresh and concurrent submits; Start over rotates it, allowing a
new incident with identical text. Ticket schema migration preserves existing tickets
and events, makes unavailable classification/draft fields nullable, and records raw
classifier confidence and ticket creation reason separately. SMTP remains an
after-commit outbox operation and cannot change ticket-creation success.

## 2026-10-07: Repair demo mailbox onboarding

The user explicitly requested that Create account provision the demo inbox with
the same email and password entered in the form. This replaces the earlier separate,
one-time generated password for local customers. The inbox resolves the customer's
salted support-password hash, while the support login rejects unverified accounts.
Fictional staff inbox credentials stay independent. Existing local customer inboxes
are migrated without plaintext passwords; earlier inbox sessions are revoked.

Signup now commits account, invitation, inbox, OTP challenge, and outbox atomically.
A pending demo registration cannot replace its password through a retry. A resend
keeps the pending password, rotates and invalidates codes, and enforces the existing
cooldown and attempt cap. The OTP URL survives refresh and mailbox round trips.
Demo-mode delivery uses the actual inbox store rather than a disconnected JSON mail
directory. Successful delivery removes OTP bodies from the outbox. The inbox marks
the latest email, preserves tenant/recipient isolation, and uses redirects after
failed sign-in so refresh stays valid. HTTP checks the local Host and Origin plus
CSRF; SMTP rejects unknown recipients before accepting message data.

Browser acceptance must authenticate the mailbox and read the email there. Direct
database OTP extraction is not evidence that the user flow works. Since the customer
demo shares one password, this is a local verification simulation; external SMTP
verification retains its separate internet-email flow.

Verification: the complete 118-test suite passed, followed by 21 final focused
checks covering onboarding, concurrent schema migration, HTTP/SMTP isolation,
staff invitations, and the updated support message. Browser verification created
a temporary customer, signed into the inbox with the signup credentials, read the
OTP there, tested refresh and resend, and completed support verification. The
existing EM-2026 account also signed into its inbox and support using a mailbox-read
OTP. Temporary browser-test data was removed; existing customer data was preserved.
The support message now reads: "A support engineer will review it and resolve it
at the earliest."

## 2026-10-07: Keep generated replies in the staff interface

The customer screen inherited an agent-oriented Suggested reply card and instructions
to review wording before sending it to a customer. Remove that card, its download,
and technical diagnostics from the customer page. Security notices now explain the
customer's escalation status. Optional help articles remain collapsed and omit
internal source IDs in their headings. The existing role-restricted staff inbox
retains the generated draft with its review instruction. Customers continue to see
only the response submitted by staff in their ticket receipt and My tickets.

Verification: all 24 application UI regression tests passed, including hidden
customer drafts, retained staff drafts, visible submitted resolutions, ticket
persistence, and retry handling. The existing hacked-device request was checked
in the browser: its security notice and ticket receipt were shown without the
Suggested reply, Save reply, staff review instructions, or technical diagnostics.
