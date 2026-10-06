"""Provision an employee invitation within an existing tenant as a local operator."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from triage.accounts import AccountService
from triage.mail import MailService
from triage.tickets import TicketStore

parser = argparse.ArgumentParser()
for field in ("tenant-code", "employee-id", "name", "phone", "email"):
    parser.add_argument("--" + field, required=True)
args = parser.parse_args()
store = TicketStore(os.getenv("SUPPORT_DB_PATH", str(ROOT / "var" / "support.sqlite3")))
mail = MailService(store, ROOT)
accounts = AccountService(store, mail)
with store._connect() as db:
    tenant = db.execute("SELECT id FROM tenants WHERE join_code=?", (args.tenant_code.strip().upper(),)).fetchone()
if not tenant:
    raise SystemExit("This tenant has not been provisioned.")
accounts.invite_employee(tenant_id=tenant["id"], employee_id=args.employee_id, name=args.name, phone=args.phone, email=args.email)
mail.deliver_pending(event_key="invite:" + args.employee_id.strip().upper())
print("Employee invitation saved.")
