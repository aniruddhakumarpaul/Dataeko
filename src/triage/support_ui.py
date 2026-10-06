from __future__ import annotations

import logging
import re
from uuid import uuid4
import streamlit as st
from .review import ReviewDecision
from .schemas import TriageResult
from .tickets import STATUSES, TicketStore


_OPERATION_ID = re.compile(r"[0-9a-f]{32}")


def ensure_operation_id(query_params) -> str:
    """Use a URL-persisted opaque operation key, or create one before submission."""
    value = query_params.get("operation_id", "")
    if not isinstance(value, str) or not _OPERATION_ID.fullmatch(value):
        value = uuid4().hex
        query_params["operation_id"] = value
    return value


def rotate_operation_id(query_params) -> str:
    value = uuid4().hex
    query_params["operation_id"] = value
    return value


def clear_ticket_submission() -> None:
    for key in ('raised_ticket', 'support_phone', 'support_details'):
        st.session_state.pop(key, None)


def raise_ticket(store, principal, result, message, *, details='', phone=None,
                 classification=None, decision=None, direct_human=False):
    request_id = ensure_operation_id(st.query_params)
    st.session_state['request_id'] = request_id
    ticket_id = store.create_ticket(
        actor=principal, message=message, details=details,
        phone=principal.phone if phone is None else phone,
        result=result, classification=classification, decision=decision,
        request_id=request_id, direct_human=direct_human,
    )
    st.session_state['raised_ticket'] = ticket_id
    # The transactional outbox is delivered independently by the retry worker.
    return ticket_id


def render_receipt(store, mail, principal, ticket_id):
    ticket = store.get_ticket(principal, ticket_id)
    if ticket is None:
        st.error('This ticket is not available to your account.')
        return
    st.success(f"Ticket {ticket_id} raised · {ticket['status']}")
    executive = ticket['assigned_to']
    profiles = store.staff_members(principal)
    demo = any(row['name'] == executive and row['demo'] for row in profiles)
    if executive:
        with st.container(border=True):
            st.write(f"**{executive} · {'demo support executive' if demo else 'support executive'}**")
            st.write(f"Hi, I'm {executive}. Your request is in the support inbox and your callback number is available to the technical team.")
            if ticket['callback_requested']:
                st.write('Callback requested: within 2 minutes.')
            if demo:
                st.caption('Simulated executive for this demo. No real call has been scheduled or placed.')
            else:
                st.caption('The requested callback time is a preference; support must confirm availability.')
    delivery = mail.event_status(f"ticket:{ticket_id}:{ticket['version']}")
    if delivery == 'Sent':
        st.caption('A ticket update was delivered by the configured email service.')
    elif delivery == 'Failed':
        st.warning('Your ticket is saved. Email delivery is temporarily delayed and will be retried.')
    else:
        st.warning('Your ticket is saved. Its email update is waiting for delivery.')
    if ticket['resolution']:
        st.write('Support response')
        st.text(ticket['resolution'])


def render_raise_ticket(store: TicketStore, mail, principal, result: TriageResult, review: ReviewDecision, message: str) -> None:
    receipt = st.session_state.get('raised_ticket')
    if receipt:
        render_receipt(store, mail, principal, receipt)
        return
    with st.expander('Raise a support ticket' if review.required else 'Still need help? Raise a ticket', expanded=review.required):
        st.write('Ask a support executive to review this message and contact you.')
        with st.form('raise_support_ticket'):
            phone = st.text_input('Phone number for your callback', value=principal.phone, key='support_phone', max_chars=25)
            st.caption("Shared only with your organisation's customer service team for this request.")
            details = st.text_area('What still needs attention? (optional)', key='support_details', max_chars=10000)
            send = st.form_submit_button('Raise ticket and request a person', type='primary', width='stretch')
        if send:
            try:
                raise_ticket(store, principal, result, message, details=details, phone=phone, direct_human=True)
            except ValueError as error:
                st.error(str(error))
            except Exception:
                logging.exception('Support ticket could not be saved')
                st.error("The ticket wasn't saved. Your details are still here; please try again.")
            else:
                st.rerun()


def render_my_tickets(store, mail, principal):
    st.subheader('My tickets')
    tickets = store.list_tickets(principal)
    if not tickets:
        st.info("You haven't raised any tickets yet.")
        return
    labels = {row['id']: f"{row['id']} · {row['category']} · {row['status']}" for row in tickets}
    ticket_id = st.selectbox('Choose a ticket', list(labels), format_func=labels.get)
    render_receipt(store, mail, principal, ticket_id)
    with st.expander('Your original request'):
        ticket = store.get_ticket(principal, ticket_id)
        st.text(ticket['message'])
        if ticket['details']:
            st.text(ticket['details'])


def render_support_inbox(store, mail, principal, accounts):
    if principal.role != 'staff':
        st.error("Only your organisation's support team can open this inbox.")
        return
    st.title('Support inbox')
    st.caption(principal.tenant_name)
    with st.expander('Invite employee'):
        with st.form('invite_employee'):
            employee_id = st.text_input('Employee ID', max_chars=40)
            employee_name = st.text_input('Employee name', max_chars=100)
            employee_phone = st.text_input('Employee phone number', max_chars=25, placeholder='+91 9876543210')
            employee_email = st.text_input('Employee email address', max_chars=254)
            invite = st.form_submit_button('Assign Employee ID')
        if invite:
            try:
                accounts.invite_employee(tenant_id=principal.tenant_id, employee_id=employee_id,
                    name=employee_name,phone=employee_phone,email=employee_email,actor=principal)
            except (ValueError,PermissionError) as error:
                st.error(str(error))
            else:
                try:
                    mail.deliver_pending(event_key='invite:'+employee_id.strip().upper())
                except Exception:
                    logging.exception('Employee invitation saved; email must be retried')
                st.success('Employee ID assigned. The employee must verify their assigned email to activate the account.')
                if mail.mode == 'demo' or mail.setting('host') in {'127.0.0.1','localhost'}:
                    from .mailboxes import MailboxService
                    temporary = MailboxService(store).provision(principal.tenant_id,employee_email)
                    if temporary:
                        st.session_state['new_mailbox_credentials'] = {'email':employee_email,'password':temporary}
    new_mailbox = st.session_state.get('new_mailbox_credentials')
    if new_mailbox:
        with st.expander('New employee demo mailbox access',expanded=True):
            st.caption('Give these details to the invited employee privately. This password is separate from their support password.')
            st.text_input('Demo mailbox email',value=new_mailbox['email'],disabled=True)
            st.text_input('Temporary demo mailbox password',value=new_mailbox['password'],type='password',disabled=True)
            st.download_button('Save mailbox access details',data=f"Email: {new_mailbox['email']}\nMailbox password: {new_mailbox['password']}\n",
                file_name='mailbox-access.txt',mime='text/plain',on_click='ignore')
            if st.button('Dismiss mailbox access details'):
                st.session_state.pop('new_mailbox_credentials',None)
                st.rerun()
    if st.button('Refresh inbox'):
        st.session_state.pop('inbox_snapshot', None)
    if st.button('Retry pending email updates'):
        mail.deliver_pending(tenant_id=principal.tenant_id)
        st.info('Pending email delivery was retried. Ticket records remain saved even if delivery fails.')
    status_filter = st.selectbox('Show tickets', ['All'] + list(STATUSES))
    tickets = store.list_tickets(principal, status_filter)
    if not tickets:
        st.info('There are no tickets in this view.')
        return
    st.caption(f'{len(tickets)} ticket(s). Security tickets appear first. Refresh to see new requests.')
    labels = {row['id']: f"{row['id']} · {row['priority']} · {row['category']} · {row['status']}" for row in tickets}
    ticket_id = st.selectbox('Open a ticket', list(labels), format_func=labels.get, key='inbox_ticket')
    snapshot = st.session_state.get('inbox_snapshot')
    if not snapshot or snapshot['id'] != ticket_id or snapshot['tenant_id'] != principal.tenant_id:
        snapshot = store.get_ticket(principal, ticket_id)
        st.session_state['inbox_snapshot'] = snapshot
    if snapshot is None:
        st.error('This ticket is no longer available. Refresh the inbox.')
        return
    ticket = snapshot
    st.subheader(ticket['id'])
    st.write(f"**{ticket['category'] or 'Human support'} · {ticket['priority']} priority · {ticket['status']}**")
    st.write(ticket['review_reason'])
    st.caption(f"Raised: {ticket['created_at']} · Last updated: {ticket['updated_at']}")
    st.write('Customer message')
    st.text(ticket['message'])
    if ticket['details']:
        st.write('Additional details')
        st.text(ticket['details'])
    st.write('Customer contact for the technical team')
    st.text(f"Name: {ticket['customer_name']}\nPhone: {ticket['phone']}")
    if ticket['callback_requested']:
        st.info('Direct human callback requested, preferably within 2 minutes. Confirm availability before promising a time.')
    if ticket['suggested_reply']:
        with st.expander('Suggested help article reply'):
            st.text(ticket['suggested_reply'])
    executives = [row['name'] for row in store.staff_members(principal)]
    version_key = f"{ticket_id}_{ticket['version']}"
    with st.form(f'update_{ticket_id}'):
        assigned_to = st.selectbox('Assigned support executive', executives,
            index=executives.index(ticket['assigned_to']) if ticket['assigned_to'] in executives else 0, key=f'agent_{version_key}')
        status = st.selectbox('Status', STATUSES, index=STATUSES.index(ticket['status']), key=f'status_{version_key}')
        resolution = st.text_area('Response / resolution for the customer', value=ticket['resolution'], key=f'resolution_{version_key}', max_chars=10000)
        st.caption('The customer sees this response in My tickets and receives an email update.')
        save = st.form_submit_button('Save update and notify customer', type='primary')
    if save:
        try:
            store.update_ticket(principal, ticket_id, status=status, assigned_to=assigned_to, resolution=resolution, expected_version=ticket['version'])
            try:
                mail.deliver_pending(event_key=f"ticket:{ticket_id}:{ticket['version'] + 1}")
            except Exception:
                logging.exception('Ticket update saved; email delivery must be retried')
        except (ValueError, PermissionError) as error:
            st.error(str(error))
        except Exception:
            logging.exception('Support ticket update failed')
            st.error("The update wasn't saved. Please try again.")
        else:
            st.session_state.pop('inbox_snapshot', None)
            st.session_state['inbox_saved'] = ticket_id
            st.rerun()
    if st.session_state.get('inbox_saved') == ticket_id:
        delivered = mail.event_status(f"ticket:{ticket_id}:{ticket['version']}")
        st.success('Ticket update saved.')
        st.caption('Email delivered.' if delivered == 'Sent' else 'Email is queued; retry delivery if needed.')
    with st.expander('Ticket history'):
        for event in store.events(principal, ticket_id):
            st.text(f"{event['occurred_at']} · {event['actor']} · {event['status']}")
