"""Private local demo mailboxes with independent credentials and tenant boundaries."""
from dataclasses import dataclass
import hashlib
import secrets
import time
from uuid import uuid4

from .accounts import password_hash, check_password, validate_email


@dataclass(frozen=True)
class MailboxPrincipal:
    mailbox_id: str
    tenant_id: str
    email: str


class MailboxService:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mailboxes (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mailbox_sessions (
                    token_hash TEXT PRIMARY KEY, mailbox_id TEXT NOT NULL REFERENCES mailboxes(id), expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mailbox_attempts (
                    identity TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS received_mail (
                    id TEXT PRIMARY KEY, mailbox_id TEXT NOT NULL REFERENCES mailboxes(id),
                    tenant_id TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, received_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mailbox_csrf (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
            """)

    def provision(self, tenant_id: str, email: str, password: str | None = None) -> str | None:
        email = validate_email(email)
        with self.store._connect() as db:
            existing = db.execute("SELECT tenant_id FROM mailboxes WHERE email=?", (email,)).fetchone()
            if existing:
                if existing["tenant_id"] != tenant_id:
                    raise ValueError("This demo email address belongs to a different tenant.")
                return None
            password = password or secrets.token_urlsafe(24)
            db.execute("INSERT INTO mailboxes VALUES (?,?,?,?)", (uuid4().hex,tenant_id,email,password_hash(password,demo=True)))
            return password

    def sign_in(self, email: str, password: str) -> str:
        email = email.strip().lower()
        identity = hashlib.sha256(email.encode()).hexdigest()
        now, token, failed = time.time(), secrets.token_urlsafe(32), False
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempts = db.execute("SELECT count,since FROM mailbox_attempts WHERE identity=?", (identity,)).fetchone()
            if attempts and now - attempts["since"] < 900 and attempts["count"] >= 5:
                raise ValueError("Too many attempts. Wait 15 minutes before trying again.")
            row = db.execute("SELECT * FROM mailboxes WHERE email=?", (email,)).fetchone()
            valid = row is not None and check_password(password, row["password_hash"])
            if not valid:
                if row is None:
                    hashlib.pbkdf2_hmac("sha256",password[:128].encode(),b"unknown-mailbox",600000)
                count = attempts["count"]+1 if attempts and now-attempts["since"]<900 else 1
                since = attempts["since"] if attempts and now-attempts["since"]<900 else now
                db.execute("INSERT OR REPLACE INTO mailbox_attempts VALUES (?,?,?)", (identity,count,since))
                failed = True
            else:
                db.execute("DELETE FROM mailbox_attempts WHERE identity=?", (identity,))
                db.execute("INSERT INTO mailbox_sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(),row["id"],now+8*3600))
        if failed:
            raise ValueError("The email address or password is incorrect.")
        return token

    def resolve_session(self, token: str) -> MailboxPrincipal | None:
        if not token:
            return None
        with self.store._connect() as db:
            row = db.execute("""SELECT m.* FROM mailbox_sessions s JOIN mailboxes m ON m.id=s.mailbox_id
                WHERE s.token_hash=? AND s.expires_at>?""", (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return MailboxPrincipal(row["id"],row["tenant_id"],row["email"]) if row else None

    def logout(self, token: str) -> None:
        with self.store._connect() as db:
            db.execute("DELETE FROM mailbox_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def csrf_token(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.store._connect() as db:
            db.execute("DELETE FROM mailbox_csrf WHERE expires_at<?", (time.time(),))
            db.execute("INSERT INTO mailbox_csrf VALUES (?,?)", (hashlib.sha256(token.encode()).hexdigest(),time.time()+3600))
        return token

    def valid_csrf(self, cookie: str, submitted: str) -> bool:
        if not cookie or not submitted or not secrets.compare_digest(cookie,submitted):
            return False
        with self.store._connect() as db:
            return db.execute("SELECT 1 FROM mailbox_csrf WHERE token_hash=? AND expires_at>?",
                              (hashlib.sha256(cookie.encode()).hexdigest(),time.time())).fetchone() is not None

    def receive(self, recipient: str, subject: str, body: str) -> bool:
        with self.store._connect() as db:
            row = db.execute("SELECT id,tenant_id FROM mailboxes WHERE email=?", (recipient.lower().strip(),)).fetchone()
            if not row:
                return False
            db.execute("INSERT INTO received_mail VALUES (?,?,?,?,?,?)", (uuid4().hex,row["id"],row["tenant_id"],subject[:500],body[:100000],time.time()))
        return True

    def messages(self, principal: MailboxPrincipal | None) -> list[dict]:
        if principal is None:
            raise PermissionError("Sign in to this mailbox.")
        with self.store._connect() as db:
            actual = db.execute("SELECT id FROM mailboxes WHERE id=? AND tenant_id=? AND email=?",
                                (principal.mailbox_id,principal.tenant_id,principal.email)).fetchone()
            if not actual:
                raise PermissionError("This mailbox is unavailable to this account.")
            return [dict(row) for row in db.execute("SELECT subject,body,received_at FROM received_mail WHERE mailbox_id=? AND tenant_id=? ORDER BY received_at DESC LIMIT 50",
                        (principal.mailbox_id,principal.tenant_id))]
