from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from .tickets import TicketStore, normalize_phone
from .mail import MailService, enqueue_mail


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    name: str
    phone: str
    email: str
    tenant_name: str
    employee_id: str = ""


def password_hash(password: str, *, demo: bool = False) -> str:
    if not password:
        raise ValueError("Enter a password.")
    if not demo and not 12 <= len(password) <= 128:
        raise ValueError("Use a password with 12 to 128 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        method, rounds, salt, expected = stored.split("$")
        if method != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return secrets.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", email):
        raise ValueError("Enter a valid email address for OTPs and ticket updates.")
    return email


class AccountService:
    def __init__(self, store: TicketStore, mail: MailService):
        self.store, self.mail = store, mail
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, join_code TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('customer','staff')),
                    verified INTEGER NOT NULL DEFAULT 0, demo INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(tenant_id,phone), UNIQUE(tenant_id,email)
                );
                CREATE TABLE IF NOT EXISTS login_challenges (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES accounts(id),
                    otp_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES accounts(id),
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    identity TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL
                );
            """)
            db.execute('BEGIN IMMEDIATE')
            columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
            if "employee_id" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN employee_id TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS account_employee_id ON accounts(employee_id) WHERE employee_id<>''")
            for row in db.execute("SELECT id FROM accounts WHERE employee_id=''").fetchall():
                db.execute("UPDATE accounts SET employee_id=? WHERE id=?", ("EMP-" + row["id"][:12].upper(), row["id"]))
            db.execute("""CREATE TABLE IF NOT EXISTS employee_invites (
                employee_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, claimed_by TEXT
            )""")
            challenge_columns = {row["name"] for row in db.execute("PRAGMA table_info(login_challenges)")}
            if "pending_password" not in challenge_columns:
                db.execute("ALTER TABLE login_challenges ADD COLUMN pending_password TEXT")
        if self.mail.is_demo:
            from .mailboxes import MailboxService
            MailboxService(self.store).use_customer_credentials()

    def create_tenant(self, name: str, join_code: str) -> str:
        code = join_code.strip().upper()
        if not name.strip() or not re.fullmatch(r"[A-Z0-9-]{6,40}", code):
            raise ValueError("Use a tenant name and an organisation code of 6 to 40 letters, numbers, or hyphens.")
        with self.store._connect() as db:
            existing = db.execute("SELECT id FROM tenants WHERE join_code=?", (code,)).fetchone()
            if existing:
                return existing["id"]
            tenant = uuid4().hex
            db.execute("INSERT INTO tenants VALUES (?,?,?)", (tenant, name.strip(), code))
            return tenant

    def provision_account(self, *, tenant_id: str, name: str, phone: str, email: str,
                          password: str, role: str = "customer", demo: bool = False, employee_id: str | None = None) -> str:
        if role not in {"customer", "staff"} or not name.strip() or len(name) > 100:
            raise ValueError("Enter a name and a valid account role.")
        phone, email = normalize_phone(phone, True), validate_email(email)
        encoded = password_hash(password, demo=self.mail.is_demo)
        account_id = uuid4().hex
        employee_id = (employee_id or "EMP-" + account_id[:12]).upper()
        try:
            with self.store._connect() as db:
                db.execute("""INSERT INTO accounts(id,tenant_id,name,phone,email,password_hash,role,demo,employee_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (account_id, tenant_id, name.strip(), phone, email, encoded, role, int(demo), employee_id))
        except sqlite3.IntegrityError:
            raise ValueError("This phone number or email is already registered for the organisation, or the organisation is invalid.") from None
        return account_id

    def invite_employee(self, *, tenant_id: str, employee_id: str, name: str, phone: str, email: str, actor=None) -> None:
        employee_id = employee_id.strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]{5,40}", employee_id) or not name.strip():
            raise ValueError("Enter a name and Employee ID with 5 to 40 letters, numbers, or hyphens.")
        phone, email = normalize_phone(phone, True), validate_email(email)
        with self.store._connect() as db:
            if actor is not None:
                self.store._scope(db, actor, staff_only=True)
                if tenant_id != actor.tenant_id:
                    raise PermissionError("Employees must be invited into your own organisation.")
            existing = db.execute("SELECT tenant_id,email,phone FROM employee_invites WHERE employee_id=?", (employee_id,)).fetchone()
            if existing:
                if (existing["tenant_id"],existing["email"],existing["phone"]) != (tenant_id,email,phone):
                    raise ValueError("This Employee ID has already been assigned.")
                return
            if db.execute("SELECT id FROM accounts WHERE employee_id=?", (employee_id,)).fetchone():
                raise ValueError("This Employee ID is already registered.")
            db.execute("INSERT INTO employee_invites(employee_id,tenant_id,name,email,phone) VALUES (?,?,?,?,?)", (employee_id,tenant_id,name.strip(),email,phone))
            enqueue_mail(db,tenant_id=tenant_id,recipient=email,kind="invite",subject="Your Dataeko support Employee ID",
                body=f"Hello {name.strip()},\n\nYour Employee ID is {employee_id}.\nCreate your account using this ID, your assigned phone number, and this email address.\n"
                     "Verify the email code to finish registration.\nDataeko support",event_key=f"invite:{employee_id}")

    def register_customer(self, *, employee_id: str, name: str, phone: str,
                          email: str, password: str) -> str:
        self.mail.require_ready()
        employee_id, phone, email = employee_id.strip().upper(), normalize_phone(phone, True), validate_email(email)
        pending_hash = password_hash(password, demo=self.mail.is_demo)
        # Account, inbox, challenge, and outbox are one transaction. SMTP runs after commit.
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            invite = db.execute("SELECT * FROM employee_invites WHERE employee_id=?", (employee_id,)).fetchone()
            existing = db.execute("SELECT * FROM accounts WHERE employee_id=?", (employee_id,)).fetchone()
            if not invite and self.mail.is_demo:
                if not re.fullmatch(r"EM-[0-9]{4}", employee_id):
                    raise ValueError("Use an Employee ID like EM-2026: EM- followed by four digits.")
                if not name.strip() or len(name) > 100:
                    raise ValueError("Enter your name (up to 100 characters).")
                tenant = db.execute("SELECT id FROM tenants WHERE join_code='DATAEKO-DEMO'").fetchone()
                tenant_id = tenant['id'] if tenant else uuid4().hex
                if not tenant:
                    db.execute("INSERT INTO tenants VALUES (?, 'Dataeko demo', 'DATAEKO-DEMO')", (tenant_id,))
                if existing:
                    raise ValueError("This Employee ID is already in use. Choose another ID or sign in.")
                if db.execute("SELECT id FROM accounts WHERE tenant_id=? AND (phone=? OR email=?)", (tenant_id,phone,email)).fetchone():
                    raise ValueError("This phone or email already has a test account. Sign in or use different details.")
                if db.execute("SELECT id FROM mailboxes WHERE email=?", (email,)).fetchone():
                    raise ValueError("This email already has a demo inbox. Use its assigned Employee ID.")
                user_id = uuid4().hex
                db.execute("""INSERT INTO accounts(id,tenant_id,name,phone,email,password_hash,role,demo,employee_id)
                    VALUES (?,?,?,?,?,?,'customer',1,?)""", (user_id,tenant_id,name.strip(),phone,email,pending_hash,employee_id))
                db.execute("INSERT INTO employee_invites(employee_id,tenant_id,name,email,phone) VALUES (?,?,?,?,?)",
                           (employee_id,tenant_id,name.strip(),email,phone))
            else:
                if not invite or invite['email'] != email or invite['phone'] != phone:
                    if self.mail.is_demo and re.fullmatch(r"EM-[0-9]{4}", employee_id):
                        raise ValueError("This Employee ID is already in use. Choose another ID or sign in.")
                    raise ValueError("Check the Employee ID, phone, and email assigned by your support team.")
                if invite['claimed_by'] or (existing and (existing['verified'] or existing['role'] != 'customer')):
                    raise ValueError("This Employee ID is already registered. Please sign in.")
                tenant_id = invite['tenant_id']
                user_id = existing['id'] if existing else uuid4().hex
                if self.mail.is_demo and existing:
                    previous = db.execute("""SELECT pending_password FROM login_challenges
                        WHERE user_id=? AND pending_password IS NOT NULL ORDER BY expires_at DESC LIMIT 1""", (user_id,)).fetchone()
                    original = previous['pending_password'] if previous else existing['password_hash']
                    if not check_password(password, original):
                        raise ValueError("This account is awaiting verification. Use the password you chose when creating it.")
                if not existing:
                    db.execute("""INSERT INTO accounts(id,tenant_id,name,phone,email,password_hash,role,demo,employee_id)
                        VALUES (?,?,?,?,?,?,'customer',?,?)""", (user_id,tenant_id,invite['name'],phone,email,pending_hash,int(self.mail.is_demo),employee_id))
            if self.mail.is_demo:
                inbox = db.execute("SELECT id,tenant_id FROM mailboxes WHERE email=?", (email,)).fetchone()
                if inbox and inbox['tenant_id'] != tenant_id:
                    raise ValueError("This demo email address belongs to a different tenant.")
                if inbox:
                    db.execute("UPDATE mailboxes SET auth_source='support',password_hash=? WHERE id=?", (pending_hash,inbox['id']))
                    db.execute("DELETE FROM mailbox_sessions WHERE mailbox_id=?", (inbox['id'],))
                else:
                    db.execute("INSERT INTO mailboxes(id,tenant_id,email,password_hash,auth_source) VALUES (?,?,?,?,'support')",
                               (uuid4().hex,tenant_id,email,pending_hash))
                db.execute("UPDATE accounts SET password_hash=? WHERE id=?", (pending_hash,user_id))
            cid = self._issue_challenge(db, user_id, pending_hash)
        self.mail.deliver_pending(event_key=f"otp:{cid}")
        return cid

    def _issue_challenge(self, db, user_id: str, pending_hash: str | None = None) -> str:
        now, cid, otp = time.time(), uuid4().hex, f"{secrets.randbelow(1000000):06d}"
        user = db.execute("SELECT * FROM accounts WHERE id=?", (user_id,)).fetchone()
        if not user or (pending_hash and user['verified']):
            raise ValueError("Please sign in to this existing account.")
        recent = db.execute("SELECT expires_at FROM login_challenges WHERE user_id=? ORDER BY expires_at DESC LIMIT 1", (user_id,)).fetchone()
        if recent and recent['expires_at'] - 300 > now - 30:
            raise ValueError("A code was just sent. Wait 30 seconds before requesting another.")
        db.execute("UPDATE mail_outbox SET status='Expired',body='' WHERE event_key IN (SELECT 'otp:'||id FROM login_challenges WHERE user_id=?)", (user_id,))
        db.execute("UPDATE login_challenges SET used=1,pending_password=NULL WHERE user_id=?", (user_id,))
        db.execute("INSERT INTO login_challenges(id,user_id,otp_hash,expires_at,pending_password) VALUES (?,?,?,?,?)",
                   (cid,user_id,hashlib.sha256((cid+otp).encode()).hexdigest(),now+300,pending_hash))
        subject = "Verify your Dataeko employee account" if pending_hash else "Your support sign-in code"
        enqueue_mail(db,tenant_id=user['tenant_id'],recipient=user['email'],kind='otp',subject=subject,
            body=f"Your one-time {'account verification' if pending_hash else 'support sign-in'} code is {otp}.\n"
                 "It expires in 5 minutes. Do not share it.",event_key=f"otp:{cid}",expires_at=now+300)
        return cid

    def resend_challenge(self, challenge_id: str) -> str:
        self.mail.require_ready()
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM login_challenges WHERE id=?", (challenge_id,)).fetchone()
            if not row or row['used'] or row['attempts'] >= 5 or row['expires_at'] <= time.time()-600:
                raise ValueError("This verification request has ended. Return to sign-in or create account.")
            cid = self._issue_challenge(db, row['user_id'], row['pending_password'])
        self.mail.deliver_pending(event_key=f"otp:{cid}")
        return cid

    def begin_login(self, employee_id: str, phone: str, password: str) -> str:
        self.mail.require_ready()
        phone = normalize_phone(phone, True)
        identity = hashlib.sha256(employee_id.strip().upper().encode()).hexdigest()
        now = time.time()
        challenge_id = ""
        failure = False
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempts = db.execute("SELECT count,since FROM auth_attempts WHERE identity=?", (identity,)).fetchone()
            if attempts and now - attempts["since"] < 900 and attempts["count"] >= 5:
                raise ValueError("Too many sign-in attempts. Please wait 15 minutes and try again.")
            row = db.execute("SELECT * FROM accounts WHERE employee_id=? AND phone=?", (employee_id.strip().upper(), phone)).fetchone()
            valid = row is not None and check_password(password, row['password_hash']) and (row['verified'] or row['role'] == 'staff')
            if not valid:
                if row is None:
                    # Spend the same KDF work for unknown identities.
                    hashlib.pbkdf2_hmac("sha256", password[:128].encode(), b"unknown-identity", 600000)
                count = attempts["count"] + 1 if attempts and now - attempts["since"] < 900 else 1
                since = attempts["since"] if attempts and now - attempts["since"] < 900 else now
                db.execute("INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)", (identity, count, since))
                failure = True
            else:
                db.execute("DELETE FROM auth_attempts WHERE identity=?", (identity,))
                challenge_id = self._issue_challenge(db, row['id'])
        if failure:
            raise ValueError("The Employee ID, phone number, or password is incorrect.")
        self.mail.deliver_pending(event_key=f"otp:{challenge_id}")
        return challenge_id

    def verify_otp(self, challenge_id: str, otp: str) -> str:
        now, token = time.time(), secrets.token_urlsafe(32)
        error = None
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM login_challenges WHERE id=?", (challenge_id,)).fetchone()
            if not row or row["used"] or row["expires_at"] <= now or row["attempts"] >= 5:
                error = "This code has expired or was already used. Sign in again for a new code."
            elif not secrets.compare_digest(row["otp_hash"], hashlib.sha256((challenge_id + otp.strip()).encode()).hexdigest()):
                db.execute("UPDATE login_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
                error = "The code is incorrect. Check the latest email and try again."
            else:
                db.execute("UPDATE login_challenges SET used=1 WHERE id=?", (challenge_id,))
                db.execute("UPDATE accounts SET verified=1 WHERE id=?", (row["user_id"],))
                if row["pending_password"]:
                    db.execute("UPDATE accounts SET password_hash=? WHERE id=?", (row["pending_password"],row["user_id"]))
                    db.execute("UPDATE employee_invites SET claimed_by=? WHERE employee_id=(SELECT employee_id FROM accounts WHERE id=?)", (row["user_id"],row["user_id"]))
                    db.execute("UPDATE login_challenges SET pending_password=NULL WHERE id=?", (challenge_id,))
                db.execute("INSERT INTO auth_sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["user_id"], now + 8 * 3600))
        if error:
            raise ValueError(error)
        return token

    def resolve_session(self, token: str) -> Principal | None:
        if not token:
            return None
        with self.store._connect() as db:
            row = db.execute("""SELECT a.*, t.name tenant_name FROM auth_sessions s
                JOIN accounts a ON a.id=s.user_id JOIN tenants t ON t.id=a.tenant_id
                WHERE s.token_hash=? AND s.expires_at>? AND a.verified=1""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if row is None:
            return None
        return Principal(row["id"], row["tenant_id"], row["role"], row["name"], row["phone"], row["email"], row["tenant_name"], row["employee_id"])

    def logout(self, token: str) -> None:
        with self.store._connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def active_challenge(self, challenge: str) -> bool:
        with self.store._connect() as db:
            return db.execute("SELECT id FROM login_challenges WHERE id=? AND used=0 AND attempts<5 AND expires_at>?", (challenge,time.time())).fetchone() is not None

    def recoverable_challenge(self, challenge: str) -> bool:
        with self.store._connect() as db:
            return db.execute("SELECT id FROM login_challenges WHERE id=? AND used=0 AND attempts<5 AND expires_at>?",
                              (challenge,time.time()-600)).fetchone() is not None
