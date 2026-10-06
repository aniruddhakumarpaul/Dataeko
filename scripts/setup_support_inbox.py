import argparse
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from triage.tickets import TicketStore
from triage.mail import MailService
from triage.accounts import AccountService
from triage.mailboxes import MailboxService

parser = argparse.ArgumentParser(description='Provision a tenant and fictional local demo support executives.')
parser.add_argument('--organisation-code', default='DATAEKO-DEMO')
parser.add_argument('--organisation-name', default='Dataeko demo')
args = parser.parse_args()
secrets_file = ROOT / '.streamlit' / 'secrets.toml'
secrets_file.parent.mkdir(parents=True, exist_ok=True)
if not secrets_file.exists():
    with secrets_file.open('x',encoding='utf-8') as settings:
        settings.write('mail_mode = "smtp"\n\n[smtp]\nhost = "127.0.0.1"\nport = 1025\nfrom = "Dataeko Support <dataeko@support.test>"\nallow_local_plaintext = true\n')
store = TicketStore(os.getenv('SUPPORT_DB_PATH', str(ROOT / 'var' / 'support.sqlite3')))
mail = MailService(store, ROOT)
accounts = AccountService(store, mail)
tenant_id = accounts.create_tenant(args.organisation_name, args.organisation_code)
mailboxes = MailboxService(store)
credentials = ROOT / 'var' / 'demo-staff-credentials.json'
existing = json.loads(credentials.read_text(encoding='utf-8')) if credentials.exists() else []
for i, name in enumerate(('Rahul', 'Priya', 'Amit'), start=1):
    phone = f'+1202555010{i}'
    with store._connect() as db:
        exists = db.execute('SELECT id FROM accounts WHERE tenant_id=? AND phone=?', (tenant_id, phone)).fetchone()
    if exists:
        employee_id = args.organisation_code + '-' + name.upper()
        with store._connect() as db:
            db.execute('UPDATE accounts SET employee_id=? WHERE id=?', (employee_id, exists['id']))
        for entry in existing:
            if entry.get('phone') == phone and entry.get('organisation_code') == args.organisation_code:
                entry['employee_id'] = employee_id
        continue
    password = secrets.token_urlsafe(24)
    accounts.provision_account(tenant_id=tenant_id, name=name, phone=phone,
        email=f'{name.lower()}@{args.organisation_code.lower()}.support.test', password=password, role='staff', demo=True, employee_id=args.organisation_code + '-' + name.upper())
    existing.append({'name': name, 'organisation_code': args.organisation_code,
        'phone': phone, 'email': f'{name.lower()}@{args.organisation_code.lower()}.support.test', 'password': password, 'employee_id': args.organisation_code + '-' + name.upper()})
for entry in existing:
    if entry.get('organisation_code') == args.organisation_code:
        mailbox_password = mailboxes.provision(tenant_id, entry['email'])
        if mailbox_password:
            entry['mailbox_password'] = mailbox_password
credentials.write_text(json.dumps(existing, indent=2), encoding='utf-8')
invitation = {'employee_id':args.organisation_code+'-EMP-001', 'name':'Demo Employee', 'phone':'+12025550121', 'email':f'demo.employee@{args.organisation_code.lower()}.support.test'}
with store._connect() as db:
    prior = db.execute('SELECT name,email,phone FROM employee_invites WHERE employee_id=?', (invitation['employee_id'],)).fetchone()
    if prior:
        invitation.update(dict(prior))
accounts.invite_employee(tenant_id=tenant_id, **invitation)
prior_path = ROOT / 'var' / 'demo-employee-invitation.json'
prior_invitation = json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.exists() else {}
mailbox_password = mailboxes.provision(tenant_id, invitation['email'])
invitation['mailbox_password'] = mailbox_password or prior_invitation.get('mailbox_password', '')
if prior_invitation.get('employee_id') == invitation['employee_id'] and prior_invitation.get('support_password'):
    invitation['support_password'] = prior_invitation['support_password']
(ROOT / 'var' / 'demo-employee-invitation.json').write_text(json.dumps(invitation, indent=2), encoding='utf-8')
print(f'Demo staff credentials: {credentials}. Employee invitation: var/demo-employee-invitation.json.')
