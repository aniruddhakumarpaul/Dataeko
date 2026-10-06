"""Operator-owned outbox retry; no customer email delivery is claimed before SMTP accepts it."""
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from triage.mail import MailService
from triage.tickets import TicketStore

store = TicketStore(os.getenv("SUPPORT_DB_PATH", str(ROOT / "var" / "support.sqlite3")))
mail = MailService(store, ROOT)
mail.require_ready()
wait = threading.Event()
if "--watch" in sys.argv:
    print("Email retry worker running; pending messages checked every 30 seconds.", flush=True)
    while not wait.is_set():
        mail.deliver_pending()
        wait.wait(30)
else:
    mail.deliver_pending()
    print("Pending email delivery retried.")
