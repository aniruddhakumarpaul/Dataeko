"""Persistent support queue and private customer status lookup."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from uuid import uuid4

from .review import review_decision
from .schemas import TriageResult
from .mail import enqueue_mail

STATUSES = ("Open", "In progress", "Resolved")


def normalize_phone(phone: str, required: bool) -> str:
    phone = phone.strip()
    if not phone and not required:
        return ""
    if not re.fullmatch(r"\+[0-9 ()\-]{8,25}", phone):
        raise ValueError("Enter a phone number with a country code, for example +91 9876543210.")
    normalized = "+" + re.sub(r"\D", "", phone)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", normalized):
        raise ValueError("Enter a valid phone number with 8 to 15 digits, including the country code.")
    return normalized


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TicketStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    message TEXT NOT NULL, details TEXT NOT NULL,
                    customer_name TEXT NOT NULL, phone TEXT NOT NULL,
                    category TEXT NOT NULL, confidence REAL NOT NULL,
                    priority TEXT NOT NULL, review_reason TEXT NOT NULL,
                    needs_human_review INTEGER NOT NULL,
                    suggested_reply TEXT NOT NULL, sources TEXT NOT NULL,
                    tracking_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('Open','In progress','Resolved')),
                    assigned_to TEXT NOT NULL DEFAULT '', resolution TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ticket_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL REFERENCES tickets(id),
                    actor TEXT NOT NULL, status TEXT NOT NULL, occurred_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tickets)")}
            for name in ("tenant_id", "owner_id"):
                if name not in columns:
                    db.execute(f"ALTER TABLE tickets ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            if "callback_requested" not in columns:
                db.execute("ALTER TABLE tickets ADD COLUMN callback_requested INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE INDEX IF NOT EXISTS tickets_scope ON tickets(tenant_id,owner_id)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _scope(self, db, actor, staff_only=False):
        if actor is None:
            raise PermissionError("Sign in before accessing support tickets.")
        account = db.execute("SELECT * FROM accounts WHERE id=? AND tenant_id=? AND verified=1",
                             (actor.user_id, actor.tenant_id)).fetchone()
        if not account or account["role"] != actor.role or (staff_only and account["role"] != "staff"):
            raise PermissionError("This account cannot access the requested support operation.")
        return account

    def create_ticket(self, *, actor, message: str, details: str,
                      phone: str, result: TriageResult, request_id: str,
                      direct_human: bool = False) -> str:
        review = review_decision(result)
        phone = normalize_phone(phone, required=True)
        if not message.strip() or len(message) > 20000:
            raise ValueError("The customer message must contain between 1 and 20,000 characters.")
        if len(details) > 10000 or not request_id:
            raise ValueError("Keep extra details under 10,000 characters and include a submission identifier.")
        now = _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            account = self._scope(db, actor)
            if account["role"] != "customer":
                raise PermissionError("Customer requests must be raised from a customer account.")
            existing = db.execute("SELECT id,tenant_id,owner_id FROM tickets WHERE request_id = ?", (request_id,)).fetchone()
            if existing:
                if existing["tenant_id"] != actor.tenant_id or existing["owner_id"] != actor.user_id:
                    raise PermissionError("The submission identifier belongs to a different account.")
                return existing["id"]
            ticket_id = "TKT-" + uuid4().hex[:12].upper()
            staff = db.execute("SELECT name,email FROM accounts WHERE tenant_id=? AND role='staff' ORDER BY CASE name WHEN 'Rahul' THEN 0 ELSE 1 END,name LIMIT 1",
                               (actor.tenant_id,)).fetchone()
            assigned = staff["name"] if staff else ""
            db.execute("""
                INSERT INTO tickets
                (id,request_id,message,details,customer_name,phone,category,confidence,
                 priority,review_reason,needs_human_review,suggested_reply,sources,tracking_hash,
                 status,created_at,updated_at,tenant_id,owner_id,callback_requested,assigned_to)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticket_id, request_id, message.strip(), details.strip(), account["name"], phone,
                result.classification.category, result.classification.confidence,
                "Urgent" if review.security else "Normal",
                "Customer requested direct human support." if direct_human else review.reason,
                1, result.draft.text if result.draft.grounded else "",
                json.dumps(result.draft.cited_sources), "",
                "Open", now, now, actor.tenant_id, actor.user_id, int(direct_human or review.required), assigned,
            ))
            db.execute("INSERT INTO ticket_events(ticket_id,actor,status,occurred_at) VALUES (?,?,?,?)",
                       (ticket_id, "Customer", "Open", now))
            enqueue_mail(db, tenant_id=actor.tenant_id, recipient=account["email"], kind="ticket",
                         subject=f"Support ticket {ticket_id} raised",
                         body=f"Hello {account['name']},\n\nYour ticket {ticket_id} is Open.\nSupport contact: {assigned or 'Awaiting assignment'}.\n"
                              "Your callback number has been shared with your organisation's support team.\n"
                              "Sign in to check your ticket and its resolution.\n\nDataeko support",
                         event_key=f"ticket:{ticket_id}:0")
            if staff:
                enqueue_mail(db, tenant_id=actor.tenant_id, recipient=staff["email"], kind="staff_ticket",
                    subject=f"New support request {ticket_id}",
                    body=f"Ticket {ticket_id} is assigned to {staff['name']}.\nCustomer: {account['name']}\nCallback phone: {phone}\n"
                         f"Category: {result.classification.category}\nHuman callback requested: {'Yes' if direct_human or review.required else 'No'}\n"
                         "Sign in to your organisation's support inbox to review the message and resolve the ticket.",
                    event_key=f"staff-ticket:{ticket_id}")
        return ticket_id

    def list_tickets(self, actor, status: str = "All") -> list[dict]:
        with self._connect() as db:
            account = self._scope(db, actor)
            sql = "SELECT id,category,priority,status,assigned_to,created_at,version FROM tickets WHERE tenant_id=?"
            args = [actor.tenant_id]
            if account["role"] == "customer":
                sql += " AND owner_id=?"
                args.append(actor.user_id)
            if status != "All":
                if status not in STATUSES:
                    raise ValueError("Unknown ticket status.")
                sql += " AND status = ?"
                args.append(status)
            sql += " ORDER BY CASE priority WHEN 'Urgent' THEN 0 ELSE 1 END, created_at DESC, id"
            return [dict(row) for row in db.execute(sql, args)]

    def get_ticket(self, actor, ticket_id: str) -> dict | None:
        with self._connect() as db:
            account = self._scope(db, actor)
            sql, args = "SELECT * FROM tickets WHERE id=? AND tenant_id=?", [ticket_id, actor.tenant_id]
            if account["role"] == "customer":
                sql += " AND owner_id=?"
                args.append(actor.user_id)
            row = db.execute(sql, args).fetchone()
            if not row:
                return None
            ticket = dict(row)
            ticket.pop("tracking_hash")
            ticket.pop("request_id")
            ticket["sources"] = json.loads(ticket["sources"])
            return ticket

    def update_ticket(self, actor, ticket_id: str, *, status: str, assigned_to: str,
                      resolution: str, expected_version: int) -> None:
        if status not in STATUSES:
            raise ValueError("Choose a valid ticket status.")
        if not assigned_to.strip():
            raise ValueError("Enter the support agent's name before updating the ticket.")
        if status == "Resolved" and not resolution.strip():
            raise ValueError("Write a customer-facing resolution before marking the ticket resolved.")
        if len(resolution) > 10000 or len(assigned_to) > 100:
            raise ValueError("The update is too long.")
        now = _now()
        with self._connect() as db:
            self._scope(db, actor, staff_only=True)
            assignee = db.execute("SELECT name FROM accounts WHERE tenant_id=? AND role='staff' AND name=?",
                                  (actor.tenant_id, assigned_to.strip())).fetchone()
            if not assignee:
                raise ValueError("Choose a support executive from this organisation.")
            updated = db.execute("""
                UPDATE tickets SET status=?, assigned_to=?, resolution=?, updated_at=?, version=version+1
                WHERE id=? AND version=? AND tenant_id=?
            """, (status, assigned_to.strip(), resolution.strip(), now, ticket_id, expected_version, actor.tenant_id))
            if updated.rowcount != 1:
                raise ValueError("This ticket changed or is no longer available. Refresh it before updating.")
            db.execute("INSERT INTO ticket_events(ticket_id,actor,status,occurred_at) VALUES (?,?,?,?)",
                       (ticket_id, actor.name, status, now))
            owner = db.execute("SELECT a.email,a.name FROM tickets t JOIN accounts a ON a.id=t.owner_id AND a.tenant_id=t.tenant_id WHERE t.id=? AND t.tenant_id=?",
                               (ticket_id, actor.tenant_id)).fetchone()
            enqueue_mail(db, tenant_id=actor.tenant_id, recipient=owner["email"], kind="ticket",
                         subject=f"Support ticket {ticket_id}: {status}",
                         body=f"Hello {owner['name']},\n\nTicket {ticket_id} is now {status}.\nSupport contact: {assigned_to.strip()}.\n\n"
                              f"{resolution.strip() or 'A support executive is reviewing your request.'}\n\nSign in to view your ticket.\nDataeko support",
                         event_key=f"ticket:{ticket_id}:{expected_version + 1}")

    def events(self, actor, ticket_id: str) -> list[dict]:
        if self.get_ticket(actor, ticket_id) is None:
            return []
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT actor,status,occurred_at FROM ticket_events WHERE ticket_id=? ORDER BY id", (ticket_id,))]

    def staff_members(self, actor) -> list[dict]:
        with self._connect() as db:
            self._scope(db, actor)
            return [dict(row) for row in db.execute("SELECT name,demo FROM accounts WHERE tenant_id=? AND role='staff' ORDER BY CASE name WHEN 'Rahul' THEN 0 ELSE 1 END,name", (actor.tenant_id,))]
