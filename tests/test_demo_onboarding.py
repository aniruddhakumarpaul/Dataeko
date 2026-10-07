"""Regression coverage for real inbox delivery and the registration lifecycle."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import re
from threading import Thread
import time
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch

import pytest

from conftest import PASSWORD, otp_for
from scripts.demo_mail_server import Mailbox, Viewer
from triage.mail import enqueue_mail
from triage.mailboxes import MailboxService
from triage.accounts import AccountService, password_hash


def signup(backend, password='customer-demo-password'):
    return backend.accounts.register_customer(employee_id='EM-2042', name='Demo test customer',
        phone='+12025550142', email='journey@example.test', password=password)


def test_signup_inbox_uses_entered_password_and_support_waits_for_otp(backend):
    challenge = signup(backend)
    boxes = MailboxService(backend.store)
    token = boxes.sign_in('journey@example.test', 'customer-demo-password')
    messages = boxes.messages(boxes.resolve_session(token))
    code = re.search(r'code is (\d{6})', messages[0]['body']).group(1)
    with pytest.raises(ValueError, match='incorrect'):
        backend.accounts.begin_login('EM-2042', '+12025550142', 'customer-demo-password')
    assert backend.accounts.resolve_session(backend.accounts.verify_otp(challenge, code)).employee_id == 'EM-2042'
    with backend.store._connect() as db:
        assert db.execute('SELECT body FROM mail_outbox WHERE event_key=?', ('otp:'+challenge,)).fetchone()['body'] == ''
    assert not (backend.root / 'var' / 'demo-mail').exists()


def test_registration_transaction_rolls_back_account_inbox_and_invite(backend):
    with patch.object(backend.accounts, '_issue_challenge', side_effect=RuntimeError('injected failure')):
        with pytest.raises(RuntimeError):
            signup(backend)
    with backend.store._connect() as db:
        assert not db.execute("SELECT id FROM accounts WHERE employee_id='EM-2042'").fetchone()
        assert not db.execute("SELECT id FROM mailboxes WHERE email='journey@example.test'").fetchone()
        assert not db.execute("SELECT employee_id FROM employee_invites WHERE employee_id='EM-2042'").fetchone()


def test_registration_retry_cannot_change_existing_demo_credentials(backend):
    original = signup(backend)
    with patch('triage.accounts.time.time', return_value=time.time()+31):
        with pytest.raises(ValueError, match='password you chose'):
            signup(backend, password='different-password')
        new = signup(backend)
    assert new != original
    boxes = MailboxService(backend.store)
    assert boxes.resolve_session(boxes.sign_in('journey@example.test', 'customer-demo-password'))
    with pytest.raises(ValueError):
        boxes.sign_in('journey@example.test', 'different-password')


def test_resend_preserves_pending_password_invalidates_old_code_and_throttles(backend):
    old = signup(backend)
    old_code = otp_for(backend, old)
    with pytest.raises(ValueError, match='30 seconds'):
        backend.accounts.resend_challenge(old)
    with patch('triage.accounts.time.time', return_value=time.time()+31):
        new = backend.accounts.resend_challenge(old)
    with pytest.raises(ValueError, match='already used'):
        backend.accounts.verify_otp(old, old_code)
    token = backend.accounts.verify_otp(new, otp_for(backend,new))
    assert backend.accounts.resolve_session(token).employee_id == 'EM-2042'
    with pytest.raises(ValueError, match='ended'):
        backend.accounts.resend_challenge(new)


def test_expired_code_can_be_resent_but_locked_or_old_requests_cannot(backend):
    c = signup(backend)
    with backend.store._connect() as db:
        db.execute('UPDATE login_challenges SET expires_at=? WHERE id=?', (time.time()-1,c))
    assert not backend.accounts.active_challenge(c)
    assert backend.accounts.recoverable_challenge(c)
    new = backend.accounts.resend_challenge(c)
    with backend.store._connect() as db:
        db.execute('UPDATE login_challenges SET attempts=5 WHERE id=?', (new,))
    with pytest.raises(ValueError, match='ended'):
        backend.accounts.resend_challenge(new)


def test_customer_inbox_migration_uses_current_support_hash_and_revokes_old_inbox_sessions(backend):
    boxes = MailboxService(backend.store)
    person = backend.people['alice']
    with backend.store._connect() as db:
        db.execute('UPDATE mailboxes SET password_hash=? WHERE email=?', (password_hash('old-inbox-password',demo=True),person.email))
    old = boxes.sign_in(person.email, 'old-inbox-password')
    boxes.use_customer_credentials()
    assert boxes.resolve_session(old) is None
    assert boxes.resolve_session(boxes.sign_in(person.email, PASSWORD)).email == person.email
    with pytest.raises(ValueError):
        boxes.sign_in(person.email, 'old-inbox-password')
    with backend.store._connect() as db:
        assert db.execute('SELECT auth_source FROM mailboxes WHERE email=?', (person.email,)).fetchone()['auth_source'] == 'support'
        assert db.execute('SELECT auth_source FROM mailboxes WHERE email=?', (backend.people['rahul'].email,)).fetchone()['auth_source'] == 'independent'


def test_external_smtp_does_not_migrate_inbox_credentials(backend):
    backend.mail.mode = 'smtp'
    backend.mail.settings = {'host':'smtp.example.test', 'from':'support@example.test'}
    AccountService(backend.store, backend.mail)
    with backend.store._connect() as db:
        assert db.execute('SELECT auth_source FROM mailboxes WHERE email=?', (backend.people['alice'].email,)).fetchone()['auth_source'] == 'independent'


def test_failed_delivery_keeps_signup_inbox_and_can_be_retried(backend):
    with patch.object(backend.mail,'_send',side_effect=ConnectionError('temporary delivery failure')):
        c = signup(backend)
    assert backend.mail.event_status('otp:'+c) == 'Failed'
    boxes = MailboxService(backend.store)
    assert boxes.resolve_session(boxes.sign_in('journey@example.test','customer-demo-password'))
    backend.mail.deliver_pending(event_key='otp:'+c)
    assert backend.mail.event_status('otp:'+c) == 'Sent'
    assert backend.accounts.resolve_session(backend.accounts.verify_otp(c,otp_for(backend,c)))


def test_demo_delivery_refuses_missing_inbox_or_wrong_tenant(backend):
    for key, email, tenant in [('missing','missing@example.test',backend.people['alice'].tenant_id),
                               ('wrongtenant',backend.people['eve'].email,backend.people['alice'].tenant_id)]:
        with backend.store._connect() as db:
            enqueue_mail(db,tenant_id=tenant,recipient=email,subject='Private notice',body='Private content',kind='ticket',event_key=key)
        backend.mail.deliver_pending(event_key=key)
        assert backend.mail.event_status(key) == 'Failed'


@pytest.fixture
def inbox_http(backend):
    boxes = MailboxService(backend.store)
    handler = type('TestViewer', (Viewer,), {'mailboxes': boxes})
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], boxes
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(port, method, path, data=None, cookies='', origin=None, host=None):
    conn = HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'Cookie':cookies}
    if origin:
        headers['Origin'] = origin
    if host:
        headers['Host'] = host
    body = urlencode(data) if data else None
    if data:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode()
    conn.close()
    return result


def csrf_cookie(headers):
    parsed = SimpleCookie()
    parsed.load(headers['Set-Cookie'])
    token = parsed['mailbox_csrf'].value
    return token, 'mailbox_csrf='+token


def test_mailbox_failed_signin_redirect_is_refreshable_and_preserves_continuation(inbox_http):
    port, _ = inbox_http
    code = 'a'*32
    status, headers, _ = request(port,'GET','/?continue='+code)
    csrf, cookie = csrf_cookie(headers)
    status, headers, _ = request(port,'POST','/login', {'csrf':csrf,'continue':code,'email':'alice@example.test','password':'wrong'},
                                 cookies=cookie, origin=f'http://127.0.0.1:{port}')
    assert status == 303 and headers['Location'].startswith('/?continue='+code)
    for _ in range(2):
        status, refreshed, body = request(port,'GET',headers['Location'])
        assert status == 200 and 'password is incorrect' in body and '?auth_challenge='+code in body


def test_mailbox_http_authentication_csrf_origin_and_private_messages(inbox_http):
    port, boxes = inbox_http
    boxes.receive('alice@example.test','Alice private','Only Alice')
    boxes.receive('bob@example.test','Bob private','Only Bob')
    _, headers, _ = request(port,'GET','/')
    csrf, cookie = csrf_cookie(headers)
    # Opening another inbox tab must not invalidate the first tab's login form.
    _, other_headers, _ = request(port,'GET','/',cookies=cookie)
    assert csrf_cookie(other_headers)[0] == csrf
    data = {'csrf':csrf,'email':'alice@example.test','password':PASSWORD}
    assert request(port,'POST','/login',data,cookies=cookie,origin='https://evil.example')[0] == 403
    assert request(port,'POST','/login',{**data,'csrf':'invalid'},cookies=cookie,origin=f'http://127.0.0.1:{port}')[0] == 403
    assert request(port,'GET','/',host='evil.example')[0] == 403
    status, headers, _ = request(port,'POST','/login',data,cookies=cookie,origin=f'http://127.0.0.1:{port}')
    assert status == 303 and 'HttpOnly' in headers['Set-Cookie']
    session = headers['Set-Cookie'].split(';')[0]
    status, headers, body = request(port,'GET','/',cookies=session)
    assert status == 200 and 'Only Alice' in body and 'Only Bob' not in body and 'Latest email' in body
    csrf, cookie = csrf_cookie(headers)
    status, headers, _ = request(port,'POST','/logout',{'csrf':csrf},cookies=cookie+'; '+session,origin=f'http://127.0.0.1:{port}')
    assert status == 303 and 'Max-Age=0' in headers['Set-Cookie']
    assert 'Only Alice' not in request(port,'GET','/',cookies=session)[2]


def test_smtp_rejects_unprovisioned_recipient_before_accepting_data(backend):
    smtp = Mailbox(MailboxService(backend.store))
    envelope = SimpleNamespace(rcpt_tos=[])
    assert asyncio.run(smtp.handle_RCPT(None,None,envelope,'missing@example.test',[])).startswith('550')
    assert not envelope.rcpt_tos
    assert asyncio.run(smtp.handle_RCPT(None,None,envelope,'alice@example.test',[])).startswith('250')
    assert envelope.rcpt_tos == ['alice@example.test']


def test_provisioned_staff_can_start_first_otp_login_without_customer_signup(backend):
    staff = backend.people['rahul']
    with backend.store._connect() as db:
        db.execute('UPDATE accounts SET verified=0 WHERE id=?',(staff.user_id,))
    challenge = backend.accounts.begin_login(staff.employee_id,staff.phone,PASSWORD)
    assert backend.accounts.resolve_session(backend.accounts.verify_otp(challenge,otp_for(backend,challenge))).role == 'staff'


def test_concurrent_services_migrate_legacy_inbox_schema_once(backend):
    with backend.store._connect() as db:
        db.execute('ALTER TABLE mailboxes DROP COLUMN auth_source')
    def initialize(_):
        return AccountService(backend.store, backend.mail)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(initialize, range(4)))) == 4
    assert MailboxService(backend.store).resolve_session(MailboxService(backend.store).sign_in('alice@example.test',PASSWORD))
