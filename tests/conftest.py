import hashlib
import json
import re
import secrets
from types import SimpleNamespace

import pytest

from triage.accounts import AccountService, Principal
from triage.mail import MailService
from triage.tickets import TicketStore


PASSWORD = "test-password-with-12-plus-characters"


@pytest.fixture
def backend(tmp_path):
    store = TicketStore(tmp_path / "support.sqlite3")
    mail = MailService(store, tmp_path, mode="demo")
    accounts = AccountService(store, mail)
    a, b = accounts.create_tenant("Team A", "TEAM-A"), accounts.create_tenant("Team B", "TEAM-B")
    people = {}
    for name, tenant, phone, role in [
        ("Alice", a, "+12025550111", "customer"),
        ("Bob", a, "+12025550112", "customer"),
        ("Rahul", a, "+12025550113", "staff"),
        ("Eve", b, "+12025550114", "customer"),
        ("Priya", b, "+12025550115", "staff"),
    ]:
        user_id = accounts.provision_account(tenant_id=tenant, name=name, phone=phone,
            email=f"{name.lower()}@example.test", password=PASSWORD, role=role, demo=role == "staff", employee_id=f"EMP-{name.upper()}")
        with store._connect() as db:
            db.execute("UPDATE accounts SET verified=1 WHERE id=?", (user_id,))
        people[name.lower()] = Principal(user_id, tenant, role, name, phone, f"{name.lower()}@example.test", "Team A" if tenant == a else "Team B", f"EMP-{name.upper()}")
    return SimpleNamespace(store=store, mail=mail, accounts=accounts, people=people, root=tmp_path)


def otp_for(backend, challenge):
    with backend.store._connect() as db:
        body = db.execute("SELECT body FROM mail_outbox WHERE event_key=?", (f"otp:{challenge}",)).fetchone()["body"]
    return re.search(r"code is (\d{6})", body).group(1)


def session_for(backend, principal):
    import time
    token = secrets.token_urlsafe(32)
    with backend.store._connect() as db:
        db.execute("INSERT INTO auth_sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), principal.user_id, time.time() + 3600))
    return token
