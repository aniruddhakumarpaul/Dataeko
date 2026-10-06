# Accounts, tenants, support tickets, and email

Support staff issue an Employee ID tied to a tenant, email, and phone number.
For local testing, customers can instead choose an unused ID in the `EM-2026`
format (EM- followed by four digits) and enter their own name, phone, email, and
password without an invitation. These accounts join the Dataeko demo tenant as
customers only. Their private demo inbox is created automatically and its separate
login is shown at the OTP step. Existing accounts and inboxes are not overwritten.
The assigned-contact registration described below applies outside testing.
The ID identifies a person; a shared organisation code is used only by local
operators to select a tenant. Registration matches the assigned email and phone.
The chosen support password is activated only after email OTP verification.
Sign-in requires Employee ID, phone, password, and a fresh email OTP.

Customers may analyze a message or choose **Talk to a person**, which raises a
persisted ticket immediately without waiting for a model. Confidence strictly
below 90% also raises a ticket automatically. Security, explicit requests for a
person, and missing KB evidence independently require review. The user's callback
number is available to their own tenant's support team. My tickets shows only
requests owned by the signed-in account. Staff can see only their tenant's queue.
Resolving a ticket requires a customer-facing response; version checks prevent
stale updates from overwriting another agent's work. Repeating the same current
request reuses the ticket instead of creating another record.

Rahul, Priya, and Amit are explicitly fictional demo executives. A friendly
introduction records the requested callback preference of within two minutes;
it does not claim that a real call has been scheduled or placed.

Ticket creation, staff handoff, and status updates enqueue email records in the
same SQLite transaction as the ticket change. SMTP sends after commit. Failure
leaves the ticket saved and delivery retryable. The UI distinguishes queued email
from SMTP acceptance. `scripts/send_pending_mail.py --watch` retries every 30
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
  and a separate mailbox password. Create account and choose a support password.
- `var/demo-staff-credentials.json`: staff Employee IDs, support passwords, and
  separate mailbox passwords. Staff also verify their email OTP.
- `.streamlit/secrets.toml`: ignored SMTP configuration.
- `var/support.sqlite3`: ignored accounts, tickets, notifications, and received email.

The demo mailbox requires an independent email/password login. It shows only that
recipient's messages in the associated tenant, never a global mailbox listing.
It provides Back to support, Refresh inbox, and Sign out. A short-lived challenge
continuation restores the local OTP step when returning; it never grants an
account session without a valid OTP and is disabled for internet SMTP settings.
Mailbox cookies are HttpOnly and SameSite=Strict; forms check CSRF tokens and the
local origin. Plain HTTP is restricted to the loopback development service.

Staff can assign Employee IDs and create local mailbox access from Invite employee.
Give temporary demo mailbox details to the employee privately. Local operators may
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

OTP verification values and session tokens are hashed in storage. Codes expire after five minutes,
allow five attempts, and are consumed atomically; passwords chosen at registration
remain pending until email verification. Login failures persist across sessions.
Support and mailbox sessions last eight hours. Support login survives browser refresh
through an eight-hour SameSite=Strict cookie and is revoked on sign-out. The cookie
uses the Secure flag over HTTPS. Mailbox login is independent and remains separate.

The hashing parameters were checked against the
[OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
This is a local prototype, not a production-readiness claim: durable hosting,
HTTPS, real SMTP/provider credentials, real staffing, account recovery, retention,
and operational monitoring remain necessary for public operation. Phone ownership
is not verified through SMS. Callback contact fields are not supplied to the model;
phone numbers pasted into free text are not automatically redacted. Do not use
real sensitive records in the synthetic demo.
