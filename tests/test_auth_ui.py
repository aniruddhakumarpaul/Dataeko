from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import PASSWORD, otp_for

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


def test_custom_demo_signup_shows_inbox_access_and_verifies_otp(backend,monkeypatch):
    monkeypatch.setenv("SUPPORT_DB_PATH",str(backend.store.path))
    st.cache_resource.clear()
    with patch("triage.mail.MailService",return_value=backend.mail):
        at = AppTest.from_file(str(ROOT / "app.py"),default_timeout=15).run()
        for key,value in {"register_employee":"EM-2026","register_name":"Test person",
            "register_phone":"+12025550124","register_email":"selfserve@example.test",
            "register_password":"1","register_confirm":"1"}.items():
            at.text_input(key=key).set_value(value)
        next(b for b in at.button if b.label=="Create account and send code").click().run()
        assert not at.exception
        assert at.text_input[0].value=="selfserve@example.test"
        c = at.session_state["pending_challenge"]
        at.text_input(key="login_otp").set_value(otp_for(backend,c))
        next(b for b in at.button if b.label=="Verify and sign in").click().run()
        assert not at.exception and at.text_area(key="ticket_text")
    st.cache_resource.clear()
