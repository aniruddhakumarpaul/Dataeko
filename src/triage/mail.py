from __future__ import annotations

from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import ssl
import time
import tomllib
from uuid import uuid4


def enqueue_mail(db, *, tenant_id: str, recipient: str, subject: str, body: str,
                 kind: str, event_key: str, expires_at: float | None = None) -> None:
    db.execute("""INSERT OR IGNORE INTO mail_outbox
        (id,tenant_id,recipient,subject,body,kind,event_key,status,created_at,expires_at)
        VALUES (?,?,?,?,?,?,?,'Pending',?,?)""",
        (uuid4().hex, tenant_id, recipient, subject, body, kind, event_key, time.time(), expires_at))


class MailService:
    def __init__(self, store, root: Path, *, mode: str | None = None):
        self.store, self.root = store, root
        path = root / ".streamlit" / "secrets.toml"
        config = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.settings = config.get("smtp", {})
        self.mode = mode or os.getenv("MAIL_MODE", config.get("mail_mode", "smtp"))
        if self.mode not in {"smtp", "demo"}:
            raise ValueError("MAIL_MODE must be smtp or demo.")
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mail_outbox (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, recipient TEXT NOT NULL,
                    subject TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL,
                    event_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
                    expires_at REAL, last_error TEXT NOT NULL DEFAULT '', claimed_at REAL
                );
            """)
            db.execute('BEGIN IMMEDIATE')
            columns = {row["name"] for row in db.execute("PRAGMA table_info(mail_outbox)")}
            if "claimed_at" not in columns:
                db.execute("ALTER TABLE mail_outbox ADD COLUMN claimed_at REAL")

    def setting(self, key: str, default=""):
        return os.getenv("SMTP_" + key.upper(), self.settings.get(key, default))

    @property
    def configured(self) -> bool:
        return self.mode == "demo" or bool(self.setting("host") and self.setting("from"))

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo" or (
            self.setting("host") in {"127.0.0.1", "localhost", "::1"}
            and str(self.setting("allow_local_plaintext", False)).lower() == "true"
        )

    def require_ready(self) -> None:
        if not self.configured:
            raise ValueError("Email delivery is not configured yet. The support team needs to connect its SMTP service before sign-in can work.")

    def _send(self, row: dict) -> None:
        if self.mode == "demo":
            from .mailboxes import MailboxService
            if not MailboxService(self.store).receive(row['recipient'], row['subject'], row['body'], tenant_id=row['tenant_id']):
                raise ValueError('The local recipient inbox has not been provisioned for this tenant.')
            return
        self.require_ready()
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = self.setting("from"), row["recipient"], row["subject"]
        email.set_content(row["body"])
        host, port = self.setting("host"), int(self.setting("port", 587))
        context = ssl.create_default_context()
        transport = smtplib.SMTP_SSL(host, port, context=context, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
        with transport as smtp:
            local_plaintext = str(self.setting("allow_local_plaintext", False)).lower() == "true" and host in {"127.0.0.1", "localhost", "::1"}
            if port != 465 and not local_plaintext:
                smtp.starttls(context=context)
            if self.setting("username"):
                smtp.login(self.setting("username"), self.setting("password"))
            smtp.send_message(email)

    def deliver_pending(self, *, event_key: str | None = None, tenant_id: str | None = None) -> None:
        if not self.configured:
            return
        now = time.time()
        with self.store._connect() as db:
            db.execute("UPDATE mail_outbox SET status='Expired',body='' WHERE expires_at IS NOT NULL AND expires_at<=?", (now,))
            db.execute("UPDATE mail_outbox SET status='Pending' WHERE status='Sending' AND claimed_at<?", (now - 120,))
            sql, args = "SELECT * FROM mail_outbox WHERE status IN ('Pending','Failed') AND attempts<5", []
            if event_key:
                sql += " AND event_key=?"
                args.append(event_key)
            if tenant_id:
                sql += " AND tenant_id=?"
                args.append(tenant_id)
            sql += " ORDER BY created_at LIMIT 20"
            rows = [dict(row) for row in db.execute(sql, args)]
        for row in rows:
            with self.store._connect() as db:
                claimed = db.execute("UPDATE mail_outbox SET status='Sending',attempts=attempts+1,claimed_at=? WHERE id=? AND status IN ('Pending','Failed')",
                                     (time.time(), row["id"]))
            if claimed.rowcount != 1:
                continue
            try:
                self._send(row)
            except Exception as error:
                # Do not persist SMTP responses that may include recipient or account details.
                with self.store._connect() as db:
                    db.execute("UPDATE mail_outbox SET status='Failed',last_error=? WHERE id=?", (type(error).__name__, row["id"]))
            else:
                with self.store._connect() as db:
                    db.execute("UPDATE mail_outbox SET status='Sent',last_error='',body=CASE WHEN kind='otp' THEN '' ELSE body END WHERE id=?",
                               (row["id"],))

    def event_status(self, event_key: str) -> str:
        with self.store._connect() as db:
            row = db.execute("SELECT status FROM mail_outbox WHERE event_key=?", (event_key,)).fetchone()
        return row["status"] if row else "Not queued"
