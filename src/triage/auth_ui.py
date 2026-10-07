import logging
from urllib.parse import quote

import streamlit as st

from .accounts import AccountService
from .mail import MailService


def render_authentication(accounts: AccountService, mail: MailService) -> None:
    password_limit = None if mail.is_demo else 128
    st.title("Dataeko support")
    st.write("Sign in to get help, request a callback, and follow your tickets.")
    # Old versions retained a generated inbox password in Streamlit memory.
    st.session_state.pop('demo_mailbox_access', None)
    challenge = st.session_state.get("pending_challenge")
    if mail.is_demo and challenge:
        st.query_params['auth_challenge'] = challenge
    if mail.is_demo:
        st.info("Local email demo. OTPs and ticket updates appear in the demo mailbox; they are not sent to internet inboxes.")
        continuation = st.session_state.get("pending_challenge", "")
        st.markdown(f"[Open the Dataeko demo mailbox](http://127.0.0.1:8025/?continue={quote(continuation)})")
    if not mail.configured:
        st.warning("Email sign-in is awaiting SMTP setup. Ask the support team to configure email delivery.")
    if challenge:
        if mail.is_demo:
            st.caption('Customer demo inbox: sign in with the same email and password you entered when creating your account. Staff use their assigned inbox login.')
        if not accounts.active_challenge(challenge):
            st.warning('This code has expired or the verification attempt has ended. Request a new code or return to sign-in.')
        elif mail.event_status(f"otp:{challenge}") == "Sent":
            st.success("A one-time code was delivered. Check your email and enter it below.")
        else:
            st.error("The email wasn't delivered yet. Ask the support team to check delivery or retry sign-in.")
        with st.form("verify_email_otp"):
            otp = st.text_input("Email one-time code", key="login_otp", max_chars=6, placeholder="6-digit code", type="password")
            verify = st.form_submit_button("Verify and sign in", type="primary", width="stretch")
        if verify:
            try:
                st.session_state["auth_session"] = accounts.verify_otp(challenge, otp)
            except ValueError as error:
                st.error(str(error))
            else:
                for key in ("pending_challenge", "login_otp", "login_password", "register_password", "register_confirm", "demo_mailbox_access"):
                    st.session_state.pop(key, None)
                st.query_params.pop('auth_challenge', None)
                st.rerun()
        if st.button('Resend email code'):
            try:
                st.session_state['pending_challenge'] = accounts.resend_challenge(challenge)
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state.pop('login_otp', None)
                st.rerun()
        if st.button('Refresh delivery status'):
            mail.deliver_pending(event_key=f'otp:{challenge}')
            st.rerun()
        if st.button("Back to sign-in"):
            st.session_state.pop("pending_challenge", None)
            st.session_state.pop("login_otp", None)
            st.query_params.pop('auth_challenge', None)
            st.rerun()
        return

    sign_in, register = st.tabs(["Sign in", "Create account"])
    with sign_in:
        with st.form("customer_sign_in"):
            code = st.text_input("Employee ID", key="login_employee", max_chars=40, placeholder="EM-2026" if mail.is_demo else "Your assigned Employee ID")
            phone = st.text_input("Phone number", key="login_phone", placeholder="+91 9876543210", max_chars=25)
            password = st.text_input("Password", type="password", key="login_password", max_chars=password_limit)
            login = st.form_submit_button("Send email code", type="primary", width="stretch")
        if login:
            try:
                st.session_state["pending_challenge"] = accounts.begin_login(code, phone, password)
            except ValueError as error:
                st.error(str(error))
            except Exception:
                logging.exception("Sign-in could not be started")
                st.error("We couldn't start sign-in. Please try again.")
            else:
                st.session_state.pop("login_password", None)
                st.rerun()
    with register:
        with st.form("customer_registration"):
            if mail.is_demo:
                st.caption("Create your own test account. Choose an unused ID such as EM-2026; no invitation is needed.")
            code = st.text_input("Employee ID", key="register_employee", max_chars=40,
                placeholder="EM-2026" if mail.is_demo else "Your assigned Employee ID")
            name = st.text_input("Your name", key="register_name", max_chars=100)
            phone = st.text_input("Phone number", key="register_phone", placeholder="+91 9876543210", max_chars=25)
            email = st.text_input("Email address", key="register_email", max_chars=254)
            st.caption("Email receives sign-in codes and updates. Support uses your phone number for requested callbacks.")
            if mail.is_demo:
                st.caption('Your demo inbox is created with this same email and password. Open it to read your verification code; Gmail is not used in the local demo.')
            password = st.text_input("Password", key="register_password", type="password", max_chars=password_limit,
                help="Any non-empty password works in this demo." if mail.is_demo else "Use at least 12 characters.")
            confirm = st.text_input("Confirm password", key="register_confirm", type="password", max_chars=password_limit)
            create = st.form_submit_button("Create account and send code", type="primary", width="stretch")
        if create:
            if password != confirm:
                st.error("The passwords don't match.")
                return
            try:
                st.session_state["pending_challenge"] = accounts.register_customer(employee_id=code, name=name, phone=phone, email=email,
                    password=password)
            except ValueError as error:
                st.error(str(error))
            except Exception:
                logging.exception("Registration could not be completed")
                st.error("We couldn't create the account. Please try again.")
            else:
                st.session_state.pop("register_password", None)
                st.session_state.pop("register_confirm", None)
                st.rerun()
