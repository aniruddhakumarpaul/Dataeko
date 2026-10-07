# Accounts, tenants, support tickets, and email

Support staff issue an Employee ID tied to a tenant, email, and phone number.
For local testing, customers can instead choose an unused ID in the `EM-2026`
format (EM- followed by four digits) and enter their own name, phone, email, and
password without an invitation. These accounts join the Dataeko demo tenant as
customers only. Their private demo inbox is created in the same transaction as the
account, OTP challenge, and email outbox entry. It uses the same email and password
entered in Create account, including before OTP verification. Support access remains
blocked until verification. Passwords are never displayed or downloaded. Verified
accounts cannot be replaced through Create account. An unverified demo registration
retry must use its original password and cannot change inbox access.
The assigned-contact registration described below applies outside testing.
The ID identifies a person; a shared organisation code is used only by local
operators to select a tenant. Registration matches the assigned email and phone.
The chosen support password is activated only after email OTP verification.
Sign-in requires Employee ID, phone, password, and a fresh email OTP.

Customers may analyze a message or choose **Talk to a person**. The direct-human
action validates the message and commits its ticket and notification outbox without
loading the classifier, retrieval index, or generator. For analyzed messages, the
shared review policy checks Security/Fraud, confidence below 90%, explicit or
unresolved-language review, and classifier review immediately after classification.
If any applies, the app commits the ticket before retrieval or generation. A later
insufficient-evidence decision creates a ticket only when one does not already
exist. Human-required tickets are committed before optional retrieval/generation.

The customer page URL carries a random 128-bit hexadecimal operation ID for the
current submission. It contains no customer data and remains available through a
full refresh. TicketStore validates its format and scopes lookups to the signed-in
tenant and owner. A unique database request ID and an immediate SQLite write
transaction make retries and concurrent submits for the same operation converge on
one ticket. Reusing another account's ID is rejected. **Start a new request**
rotates the ID, so the same message can represent a later incident and create a new
ticket.

Early tickets contain only fields known at that point: message, review reason,
priority, and classifier category/raw model score when classification ran. Direct
human tickets have no fabricated classification or confidence. Suggested reply and
sources remain null until assistance is available; `ai_state` records `not_required`,
`pending`, `complete`, or `failed`. Later assistance updates the same ticket and
cannot lower Security/Fraud priority or remove the human-review flag. The schema
migration keeps existing tickets and ticket events while making those AI fields
nullable. The older `confidence` column may contain legacy security rule scores;
new `classifier_confidence` stores the raw model score separately and is null where
that value is unavailable.

The user's callback number is available to their own tenant's support team. My
tickets shows only requests owned by the signed-in account. Staff can see only
their tenant's queue. Resolving a ticket requires a customer-facing response;
version checks prevent stale updates from overwriting another agent's work.

Rahul, Priya, and Amit are explicitly fictional demo executives. A friendly
introduction records the requested callback preference of within two minutes;
it does not claim that a real call has been scheduled or placed.

Ticket creation, staff handoff, and status updates enqueue email records in the
same SQLite transaction as the ticket change. SMTP sends only after commit. Failure
leaves the ticket saved and the outbox entry retryable; email delivery failure does
not turn a committed ticket into a failed submission. A database failure produces
no ticket receipt and no committed notification. The UI distinguishes queued email
from SMTP acceptance; ticket receipt rendering does not wait for SMTP. The independent
`scripts/send_pending_mail.py --watch` worker retries every 30
seconds, excludes expired OTPs, and recovers stale delivery claims. A crash after
SMTP acceptance but before recording it can duplicate an email; delivery is not
claimed to be exactly once.

## Local setup

Run `run_windows.ps1`. The launcher provisions the demo tenant, starts the local
SMTP/mailbox service when configured, starts the email retry worker, and launches
Streamlit. Existing SMTP settings are preserved. Setup without a secrets file
creates local-only settings for **Dataeko Support <dataeko@support.test>**.
This is not a public mailbox or internet email delivery.

- Support app: http://127.0.0.1:8501
- Private demo mailbox: http://127.0.0.1:8025 (loopback SMTP on port 1025).
- `var/demo-employee-invitation.json`: initial Employee ID, assigned email/phone,
  and bootstrap inbox access before signup. After Create account, the inbox uses
  the chosen support password.
- `var/demo-staff-credentials.json`: staff Employee IDs, support passwords, and
  separate mailbox passwords. Staff also verify their email OTP.
- `.streamlit/secrets.toml`: ignored SMTP configuration.
- `var/support.sqlite3`: ignored accounts, tickets, notifications, and received email.

Customers log into the demo mailbox with their support email and password. Fictional
staff retain their separately assigned inbox credentials. It shows only that
recipient's messages in the associated tenant, never a global mailbox listing.
It provides Back to support, Refresh inbox, and Sign out. A short-lived challenge
continuation restores the local OTP step when returning; it never grants an
account session without a valid OTP and is disabled for internet SMTP settings.
Mailbox cookies are HttpOnly and SameSite=Strict; forms check CSRF tokens, the
local origin, and the Host header. Failed login redirects to a refreshable inbox URL.
Plain HTTP is restricted to the loopback development service.

The OTP step keeps only an opaque challenge ID in the URL so refresh and Back to
support restore the step. Resend rotates the challenge, invalidates earlier codes,
preserves the pending password, and enforces a 30-second cooldown. Expired requests
remain recoverable for ten minutes after code expiry; used, attempt-locked, and older
requests require starting again. Delivery failures leave the committed account and
inbox available and can be retried without re-registration. The latest email is
labeled. Successful delivery clears the OTP body from the outbox; the inbox retains
the delivered message.

Both `MAIL_MODE=demo` and loopback SMTP deliver to the private mailbox. The former
no longer writes a separate filesystem mail store while claiming inbox delivery.
Missing inboxes and tenant mismatches fail delivery; SMTP rejects unknown recipients
at RCPT time. Local startup migrates existing customer inboxes to the current support
password and revokes sessions using the old independent credential. Existing staff
credentials, tickets, and messages are preserved.

Staff can assign Employee IDs and create local mailbox access from Invite employee.
Give temporary demo mailbox details to the employee privately for reading the
invitation before signup. After customer registration, the chosen support password
is also their inbox password. Local operators may
also run `scripts/manage_employee.py` with tenant code, Employee ID, name, phone,
and email. For real SMTP use `.streamlit/secrets.example.toml` and a sender you
control. Port 587 uses STARTTLS; 465 uses direct TLS. Plaintext is permitted only
for explicitly configured loopback SMTP. No provider account or public Dataeko
email address was created.

## Identity, security, and limits

Tenant and user identity come from server-resolved sessions. Ticket reads, writes,
events, and assignee selection verify tenant boundaries; customer access also
checks ownership. Staff roles cannot be chosen during public registration. Legacy
unowned records are preserved but hidden pending an explicit owner migration.

Passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations.

In the local demo, any non-empty password is accepted without a length or complexity
policy for support and mailbox accounts. Non-demo support registration keeps the
12-to-128-character policy. Hashing, OTP checks, and tenant isolation still apply.

Because a local customer uses one credential for both screens, demo email OTP is
a workflow simulation, not an independent authentication factor or proof of owning
the internet address. Non-demo SMTP registration and external email verification
retain their existing flow. Administrative access to the local database can read
delivered emails; normal signup and browser verification must read codes through the
authenticated mailbox rather than database queries.

OTP verification values and session tokens are hashed in storage. Codes expire after five minutes,
allow five attempts, and are consumed atomically; passwords chosen at registration
remain pending until email verification. Login failures persist across sessions.
Support and mailbox sessions last eight hours. Support login survives browser refresh
through an eight-hour SameSite=Strict cookie and is revoked on sign-out. The cookie
uses the Secure flag over HTTPS. Mailbox sessions remain separate from support
sessions, even when local customer credentials are shared.

The hashing parameters were checked against the
[OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
This is a local prototype, not a production-readiness claim: durable hosting,
HTTPS, real SMTP/provider credentials, real staffing, account recovery, retention,
and operational monitoring remain necessary for public operation. Phone ownership
is not verified through SMS. Callback contact fields are not supplied to the model;
phone numbers pasted into free text are not automatically redacted. Do not use
real sensitive records in the synthetic demo.
