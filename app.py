from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
import logging
import os
import sys

import pandas as pd
import streamlit as st
import extra_streamlit_components as stx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from triage.classifier import fit_classifier, save_classifier  # noqa: E402
from triage.constants import COST_SENSITIVE_CLASS_WEIGHTS  # noqa: E402
from triage.pipeline import TriagePipeline  # noqa: E402
from triage.safety import audit_label_conflicts  # noqa: E402
from triage.support_ui import (  # noqa: E402
    clear_ticket_submission, ensure_operation_id, rotate_operation_id,
    render_raise_ticket, render_receipt, render_support_inbox, render_my_tickets, raise_ticket,
)
from triage.tickets import TicketStore  # noqa: E402
from triage.accounts import AccountService  # noqa: E402
from triage.auth_ui import render_authentication  # noqa: E402
from triage.mail import MailService  # noqa: E402
from triage.review import (  # noqa: E402
    direct_human_decision, review_decision, review_decision_from_classification,
)

st.set_page_config(page_title="Ticket triage", page_icon="🎫", layout="centered")
st.set_option("client.toolbarMode", "minimal")
st.html("""
<style>
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
.block-container h1 { font-size: 2rem; }
</style>
""")


@st.cache_resource(show_spinner="Getting ready…")
def load_pipeline() -> TriagePipeline:
    model_path = ROOT / "artifacts" / "classifier.joblib"
    if not model_path.exists():
        # Free-host friendly: model weights are intentionally not committed. Rebuild the tiny
        # classifier from the bundled synthetic CSV on first boot.
        data = pd.read_csv(ROOT / "data" / "tickets.csv")
        conflicts = audit_label_conflicts(data["text"], data["label"])
        clean = data.drop(index=conflicts).reset_index(drop=True)
        model = fit_classifier(
            clean["text"],
            clean["label"],
            class_weight=COST_SENSITIVE_CLASS_WEIGHTS,
        )
        model_path.parent.mkdir(parents=True, exist_ok=True)
        save_classifier(model, model_path)
    return TriagePipeline(model_path=model_path, kb_dir=ROOT / "kb")


@st.cache_resource
def load_services():
    store = TicketStore(os.getenv("SUPPORT_DB_PATH", str(ROOT / "var" / "support.sqlite3")))
    mail = MailService(store, ROOT)
    return store, mail, AccountService(store, mail)


store, mail, accounts = load_services()
session_cookies = stx.CookieManager(key="support_session_cookie")
if st.session_state.pop("sign_out_requested", False):
    session_cookies.set(
        "dataeko_support_session",
        "",
        key="delete_support_session",
        expires_at=datetime.now() - timedelta(days=1),
        secure=st.context.url.startswith("https://"),
        same_site="strict",
    )
    st.session_state.clear()
cookie_token = st.context.cookies.get("dataeko_support_session", "")
session_token = st.session_state.get("auth_session") or cookie_token
principal = accounts.resolve_session(session_token)
if principal is not None:
    st.session_state["auth_session"] = session_token
    if cookie_token != session_token and not st.session_state.get("auth_cookie_saved"):
        session_cookies.set(
            "dataeko_support_session",
            session_token,
            key="save_support_session",
            expires_at=datetime.now() + timedelta(hours=8),
            secure=st.context.url.startswith("https://"),
            same_site="strict",
        )
        st.session_state["auth_cookie_saved"] = True
if principal is None:
    continuation = st.query_params.get("auth_challenge", "")
    if mail.is_demo and continuation and accounts.recoverable_challenge(continuation):
        st.session_state["pending_challenge"] = continuation
    render_authentication(accounts, mail)
    st.stop()


def sign_out():
    accounts.logout(session_token)
    st.session_state.clear()
    st.session_state["sign_out_requested"] = True


st.caption(f"{principal.tenant_name} · {principal.name} · {principal.employee_id}")
st.button("Sign out", on_click=sign_out)
if mail.is_demo:
    st.markdown('[Open your Dataeko demo inbox](http://127.0.0.1:8025/)')
    st.caption('Customers use their support email and password for this local inbox. Staff use their assigned inbox login.')
if principal.role == "staff":
    render_support_inbox(store, mail, principal, accounts)
    st.stop()
if st.query_params.get("view") == "support":
    st.error("This inbox is available only to your organisation's support team.")
    st.stop()
view = st.radio("Support view", ["New request", "My tickets"], horizontal=True, label_visibility="collapsed")
if view == "My tickets":
    render_my_tickets(store, mail, principal)
    st.stop()
if mail.setting("host") in {"127.0.0.1", "localhost"} or mail.mode == "demo":
    st.caption("Local demo: email is delivered to the Dataeko demo mailbox, and executives are simulated.")


samples = {
    "Account question": "Where can I see the details of my current plan and update my profile?",
    "Billing question": "I was charged twice for my monthly subscription. How do I get the duplicate charge refunded?",
    "Something isn't working": "The app crashes every time I open settings after logging in.",
    "Feature suggestion": "Could you add scheduled weekly exports to CSV?",
    "Account safety": "I see an unknown login and a charge I did not make. I think my account was hacked.",
}


def choose_example() -> None:
    selected = st.session_state["example"]
    if selected in samples:
        st.session_state["ticket_text"] = samples[selected]
        st.session_state.pop("result", None)
        clear_ticket_submission()
        st.session_state["request_id"] = rotate_operation_id(st.query_params)


def start_over() -> None:
    st.session_state["ticket_text"] = ""
    st.session_state["example"] = "Choose an example"
    st.session_state.pop("result", None)
    clear_ticket_submission()
    st.session_state["request_id"] = rotate_operation_id(st.query_params)


st.session_state.setdefault("ticket_text", "")
request_id = ensure_operation_id(st.query_params)
st.session_state["request_id"] = request_id
try:
    existing_ticket_id = store.ticket_id_for_request(principal, request_id)
except PermissionError:
    # A copied URL operation ID must not reveal whether another account used it.
    existing_ticket_id = None
    st.session_state["request_id"] = rotate_operation_id(st.query_params)
if existing_ticket_id:
    st.session_state.setdefault("raised_ticket", existing_ticket_id)
    existing_ticket = store.get_ticket(principal, existing_ticket_id)
    if existing_ticket and not st.session_state.get("analyzed_message"):
        st.session_state["analyzed_message"] = existing_ticket["message"]
        st.session_state["ticket_text"] = existing_ticket["message"]

st.title("How can we help?")
st.write("Check help articles or ask a support executive to contact you.")

with st.expander("Try an example"):
    st.selectbox(
        "Example message",
        ["Choose an example"] + list(samples),
        key="example",
        on_change=choose_example,
    )

with st.form("ticket_form"):
    ticket = st.text_area(
        "Customer message",
        key="ticket_text",
        height=140,
        placeholder="Paste the customer's message here…",
    )
    submitted = st.form_submit_button("Analyze ticket", type="primary", width="stretch")
    human_requested = st.form_submit_button("Talk to a person", width="stretch")
    st.caption("Requesting a person raises a ticket immediately and shares your account phone number with support.")

if submitted or human_requested:
    st.session_state.pop("result", None)
    if st.session_state.get("raised_ticket") and ticket.strip() != st.session_state.get("analyzed_message"):
        clear_ticket_submission()
        st.session_state["request_id"] = rotate_operation_id(st.query_params)
    if not ticket.strip():
        st.warning("Paste a customer message before analyzing.")
    else:
        st.session_state["analyzed_message"] = ticket.strip()
        try:
            with st.spinner("Reviewing your request…"):
                if human_requested:
                    decision = direct_human_decision(ticket.strip())
                    raise_ticket(
                        store, principal, None, ticket.strip(),
                        classification=None, decision=decision, direct_human=True,
                    )
                    st.session_state["retrieval_backend"] = "not needed for a direct human request"
                else:
                    pipeline = load_pipeline()
                    classification = pipeline.classify(ticket.strip())
                    early_decision = review_decision_from_classification(classification)
                    if early_decision.required:
                        raise_ticket(
                            store, principal, None, ticket.strip(),
                            classification=classification, decision=early_decision,
                        )
                    result = pipeline.complete(ticket.strip(), classification)
                    st.session_state["result"] = result
                    st.session_state["retrieval_backend"] = pipeline.retriever.backend
                    if st.session_state.get("raised_ticket"):
                        store.update_ai_assistance(
                            principal, st.session_state["raised_ticket"], result=result
                        )
                    else:
                        later_decision = review_decision(result)
                        if later_decision.required:
                            raise_ticket(
                                store, principal, result, ticket.strip(),
                                decision=later_decision,
                            )
                st.session_state["analyzed_message"] = ticket.strip()
        except Exception:
            logging.exception("Ticket analysis failed")
            ticket_id = st.session_state.get("raised_ticket")
            if ticket_id:
                try:
                    existing = store.get_ticket(principal, ticket_id)
                    if existing and existing["ai_state"] == "pending":
                        store.update_ai_assistance(principal, ticket_id, failed=True)
                except Exception:
                    logging.exception("Optional assistance state could not be updated")
                st.error("Your support ticket is saved. We couldn't finish the automated checks, so a support engineer will review it.")
            else:
                st.error("We couldn't save or analyze this request. Your message is still here; please try again.")

result = st.session_state.get("result")
if result is not None:
    c = result.classification
    review = review_decision(result)

    with st.container(border=True):
        category_column, confidence_column = st.columns([2, 1])
        category_column.caption("Category")
        category_column.markdown(f"**{c.category}**")
        confidence_column.caption("Confidence")
        confidence_column.markdown(f"**{c.confidence:.2%}**" if result.draft.generation_mode != "human-request" else "**Human request**")

    if review.security:
        st.warning(
            "**Security review needed**\n\n"
            + ("Your ticket has been raised for our support team to review this account or payment security concern."
               if st.session_state.get("raised_ticket") else
               "This may involve account or payment security. Request a support engineer to review your concern.")
        )
    elif review.required and result.draft.grounded:
        st.warning(
            "**Human review required**\n\n"
            + ("A ticket has been raised for a support engineer to review this request."
               if st.session_state.get("raised_ticket") else
               "A support engineer needs to check this message. Raise a ticket below so they can help.")
        )

    if not result.draft.grounded and result.draft.generation_mode != "human-request":
        if st.session_state.get("raised_ticket"):
            st.info("A support engineer will review it and resolve it at the earliest.")
        else:
            st.info("We couldn't find a relevant help article. Raise a support ticket to have an engineer review it.")

    render_raise_ticket(store, mail, principal, result, review, st.session_state["analyzed_message"])

    if result.draft.grounded:
        with st.expander("Help articles"):
            for hit in result.retrieval:
                if hit.source_id not in result.draft.cited_sources:
                    continue
                st.markdown(f"**{hit.title}**")
                st.markdown(hit.text)

    st.button("Start over", on_click=start_over)
elif st.session_state.get("raised_ticket"):
    render_receipt(store, mail, principal, st.session_state["raised_ticket"])
    st.button("Start a new request", on_click=start_over)

st.caption("Demo using sample tickets and help articles.")
