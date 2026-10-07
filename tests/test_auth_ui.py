from pathlib import Path
import time
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import PASSWORD, otp_for, session_for
from triage.mailboxes import MailboxService

ROOT = Path(__file__).resolve().parents[1]


def test_login_gate_and_email_otp_flow(backend, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB_PATH", str(backend.store.path))
    st.cache_resource.clear()
    with patch("triage.mail.MailService", return_value=backend.mail):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        assert not at.exception
        assert not at.text_area
        at.text_input(key="login_employee").set_value("EMP-ALICE")
        at.text_input(key="login_phone").set_value(backend.people["alice"].phone)
        at.text_input(key="login_password").set_value(PASSWORD)
        next(b for b in at.button if b.label == "Send email code").click().run()
        assert not at.exception
        challenge = at.session_state["pending_challenge"]
        assert not at.text_area
        at.text_input(key="login_otp").set_value(otp_for(backend, challenge))
        next(b for b in at.button if b.label == "Verify and sign in").click().run()
        assert not at.exception
        assert at.text_area(key="ticket_text")
        next(b for b in at.button if b.label == "Sign out").click().run()
        assert not at.text_area
    st.cache_resource.clear()


def test_create_account_requires_email_verification(backend, monkeypatch):
    monkeypatch.setenv("SUPPORT_DB_PATH", str(backend.store.path))
    st.cache_resource.clear()
    backend.accounts.invite_employee(tenant_id=backend.people["alice"].tenant_id, employee_id="EMP-UI", name="New UI customer", phone="+12025550117", email="ui@example.test")
    with patch("triage.mail.MailService", return_value=backend.mail):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        for key, value in {"register_employee":"EMP-UI", "register_name":"New UI customer", "register_phone":"+12025550117", "register_email":"ui@example.test", "register_password":PASSWORD, "register_confirm":PASSWORD}.items():
            at.text_input(key=key).set_value(value)
        next(b for b in at.button if b.label == "Create account and send code").click().run()
        assert not at.exception and not at.text_area
        challenge = at.session_state["pending_challenge"]
        at.text_input(key="login_otp").set_value(otp_for(backend, challenge))
        next(b for b in at.button if b.label == "Verify and sign in").click().run()
        assert not at.exception and at.text_area(key="ticket_text")
    st.cache_resource.clear()


def test_custom_demo_signup_explains_shared_inbox_credentials_and_verifies_otp(backend,monkeypatch):
    monkeypatch.setenv("SUPPORT_DB_PATH",str(backend.store.path))
    st.cache_resource.clear()
    with patch("triage.mail.MailService",return_value=backend.mail):
        at = AppTest.from_file(str(ROOT / "app.py"),default_timeout=15).run()
        assert at.text_input(key='register_employee').proto.max_chars == 40
        for key,value in {"register_employee":"EM-2026","register_name":"Test person",
            "register_phone":"+12025550124","register_email":"selfserve@example.test",
            "register_password":"1","register_confirm":"1"}.items():
            at.text_input(key=key).set_value(value)
        next(b for b in at.button if b.label=="Create account and send code").click().run()
        assert not at.exception
        assert any('same email and password' in caption.value for caption in at.caption)
        assert 'demo_mailbox_access' not in at.session_state
        c = at.session_state["pending_challenge"]
        at.text_input(key="login_otp").set_value(otp_for(backend,c))
        next(b for b in at.button if b.label=="Verify and sign in").click().run()
        assert not at.exception and at.text_area(key="ticket_text")
    st.cache_resource.clear()


def test_staff_invitation_provisions_inbox_before_delivery(backend, monkeypatch):
    monkeypatch.setenv('SUPPORT_DB_PATH', str(backend.store.path))
    st.cache_resource.clear()
    with patch('triage.mail.MailService', return_value=backend.mail):
        at = AppTest.from_file(str(ROOT/'app.py'),default_timeout=15)
        at.session_state['auth_session'] = session_for(backend,backend.people['rahul'])
        at.run()
        for label, value in {'Employee ID':'EMP-INVITEE','Employee name':'Invitation customer',
                             'Employee phone number':'+12025550144','Employee email address':'invitee@example.test'}.items():
            next(field for field in at.text_input if field.label==label).set_value(value)
        next(button for button in at.button if button.label=='Assign Employee ID').click().run()
        assert not at.exception and backend.mail.event_status('invite:EMP-INVITEE') == 'Sent'
        access = at.session_state['new_mailbox_credentials']
        boxes = MailboxService(backend.store)
        assert 'EMP-INVITEE' in boxes.messages(boxes.resolve_session(boxes.sign_in(access['email'],access['password'])))[0]['body']
    st.cache_resource.clear()


def test_pending_otp_survives_reload_resends_and_clears_continuation_after_verify(backend, monkeypatch):
    monkeypatch.setenv('SUPPORT_DB_PATH', str(backend.store.path))
    st.cache_resource.clear()
    challenge = backend.accounts.register_customer(employee_id='EM-2043',name='Refresh customer',
        phone='+12025550143',email='refresh@example.test',password='refresh-password')
    with backend.store._connect() as db:
        db.execute('UPDATE login_challenges SET expires_at=? WHERE id=?',(time.time()-1,challenge))
    with patch('triage.mail.MailService',return_value=backend.mail):
        at = AppTest.from_file(str(ROOT/'app.py'),default_timeout=15)
        at.query_params['auth_challenge'] = challenge
        at.run()
        assert not at.exception and at.session_state['pending_challenge'] == challenge
        assert at.query_params['auth_challenge'] == challenge
        assert any('expired' in warning.value for warning in at.warning)
        next(b for b in at.button if b.label=='Resend email code').click().run()
        new = at.session_state['pending_challenge']
        assert new != challenge and at.query_params['auth_challenge'] == new
        at.text_input(key='login_otp').set_value(otp_for(backend,new))
        next(b for b in at.button if b.label=='Verify and sign in').click().run()
        assert not at.exception and at.text_area(key='ticket_text')
        assert 'auth_challenge' not in at.query_params
    st.cache_resource.clear()
