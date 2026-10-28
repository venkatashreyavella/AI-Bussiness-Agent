import os
import sys
from pathlib import Path

# Streamlit adds the script directory, rather than the repository root, to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from frontend.security import require_login, sign_out

load_dotenv()
st.set_page_config(page_title='Business Inbox · AI Agent', page_icon='✉', layout='wide')
st.markdown('''<style>
    h1,h2,h3 {color:#17243b; overflow-wrap:anywhere}
    [data-testid="stMetric"] {background:white;padding:18px;border-radius:12px;border:1px solid #e0e6ef}
    .block-container {padding-top:2rem; max-width:1400px}
    button, input, select {min-height:44px}
    input, textarea {font-size:1rem !important}
    button:focus-visible, input:focus-visible, textarea:focus-visible, a:focus-visible,
    [role="radio"]:focus-visible {outline:3px solid #1d4ed8 !important;outline-offset:3px}
    [role="radiogroup"] {flex-wrap:wrap;gap:.5rem}
    [data-testid="stText"] pre {white-space:pre-wrap;overflow-wrap:anywhere}
    @media (max-width:800px) {
        .block-container {padding:1rem 1rem 3rem}
        h1 {font-size:1.9rem !important}
        [data-testid="stHorizontalBlock"] {flex-wrap:wrap !important;gap:1rem}
        [data-testid="stColumn"] {width:100% !important;flex:1 1 100% !important;min-width:0 !important}
        [data-testid="stButton"] button {width:100%}
    }
    @media (prefers-reduced-motion:reduce) {*, *::before, *::after {scroll-behavior:auto !important;animation:none !important;transition:none !important}}
    </style>''', unsafe_allow_html=True)
user = require_login()
BASE = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
token = st.session_state['auth_token']
can_write = user['role'] in {'admin', 'reviewer'}
with st.sidebar:
    st.title('✉ Business Inbox')
    st.caption('AI-assisted operations')
    st.write(f"Signed in as {user['display_name']} ({user['username']})")
    st.caption(f"Role: {user['role'].capitalize()}")
    st.write('Use the Workspace navigation at the top of every page.')
    st.button('Sign out', on_click=sign_out)
    st.divider()
    st.caption('Fictional demonstration records. All replies require human review. Sending is disabled.')

pages = ['Inbox', 'Email Details', 'Reply Review', 'Analytics', 'My Account']
if user['role'] == 'admin':
    pages.append('Users')
if st.session_state.get('workspace') not in pages:
    st.session_state.pop('workspace', None)
page = st.radio('Workspace', pages, horizontal=True, key='workspace')


def open_email(ident):
    st.session_state['selected_email'] = ident
    st.session_state['workspace'] = 'Email Details'


def readable(value):
    return 'Unknown' if value is None else str(value).replace('_', ' ').title()


def api(method, path, **kwargs):
    try:
        response = httpx.request(method, BASE + path, headers={'Authorization': f'Bearer {token}'}, timeout=240, **kwargs)
        if response.is_error:
            detail = response.json().get('detail', 'Request failed')
            if isinstance(detail, list):
                # Validation input can contain a password; show field messages without echoing inputs.
                detail = '; '.join(f"{'.'.join(map(str, error.get('loc', [])))}: {error.get('msg', 'Invalid value')}" for error in detail)
            st.error(detail if isinstance(detail, str) else 'Request failed')
            return None
        if response.status_code == 204:
            return {'ok': True}
        return response.json()
    except (httpx.HTTPError, ValueError):
        st.error('The API is unavailable. Start the backend and check your connection settings.')
        return None


st.title(page)
if st.session_state.pop('just_registered', False):
    st.success('Your account is ready. You are signed in and can start using the inbox.')
st.caption('BUSINESS INBOX AI AGENT / REVIEW WORKSPACE')
health = api('GET', '/health')
if health:
    st.info('Offline demonstration · deterministic rules' if health['provider'] == 'demo' else 'OpenAI · human review required')

if page == 'Inbox':
    if not can_write:
        st.info('Viewer access: you can inspect emails, drafts and analytics. A reviewer or admin can make changes.')
    with st.expander('＋ Add an email', expanded=False):
        manual, upload = st.tabs(['Write or paste', 'Import .eml'])
        with manual:
            with st.form('new_email'):
                sender = st.text_input('Sender', 'accounts@aisha.example')
                subject = st.text_input('Subject', 'Invoice enquiry: INV-1042')
                body = st.text_area('Email body', 'Hello, please confirm the status of invoice INV-1042 for Aisha Trading LLC. Thank you.', height=150)
                document = st.file_uploader('Optional text document (UTF-8, up to 10,000 characters)', type=['txt'])
                thread = st.text_input('Thread reference (optional)')
                if st.form_submit_button('Add to inbox', type='primary', disabled=not can_write):
                    valid = True
                    if document:
                        try:
                            if document.size > 40000:
                                raise ValueError()
                            text = document.getvalue().decode('utf-8')
                            if len(text) > 10000:
                                raise ValueError()
                            body += '\n\n[Untrusted attached document]\n' + text
                        except (UnicodeDecodeError, ValueError):
                            valid = False
                            st.error('Use a UTF-8 text document up to 10,000 characters.')
                    created = api('POST', '/emails', json=dict(sender=sender, subject=subject, body=body, thread_id=thread or None)) if valid else None
                    if created:
                        st.session_state['selected_email'] = created['id']
                        st.success(f"Email #{created['id']} saved. Open Email Details using Workspace above to process it.")
        with upload:
            file = st.file_uploader('Plain-text email file, up to 100 KB', type=['eml'])
            if file and st.button('Import file', disabled=not can_write):
                created = api('POST', '/emails/import', files={'file': (file.name, file.getvalue(), 'message/rfc822')})
                if created:
                    st.session_state['selected_email'] = created['id']
                    st.success('Imported. Open Email Details using Workspace above to process it.')
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    search = c1.text_input('Search subject or sender')
    category = c2.selectbox('Category', ['All', 'sales_enquiry', 'invoice_enquiry', 'order', 'customer_complaint', 'payment_follow_up', 'general_request'])
    status = c3.selectbox('Status', ['All', 'new', 'processing', 'processed', 'failed'])
    urgency = c4.selectbox('Urgency', ['All', 'low', 'normal', 'high'])
    page_number = st.number_input('Page', min_value=1, value=1)
    params = {'q': search, 'limit': 10, 'offset': (page_number - 1) * 10}
    params.update({k: v for k, v in dict(category=category, status=status, urgency=urgency).items() if v != 'All'})
    emails = api('GET', '/emails', params=params)
    if emails:
        st.caption(f'Page {page_number} · {len(emails)} messages shown · 10 messages per page')
        for email in emails:
            with st.container(border=True):
                st.subheader(email['subject'])
                st.text(f"From: {email['sender']}")
                st.write(f"Status: {readable(email['status'])} · Category: {readable(email['category'])} · Urgency: {readable(email['urgency'])}")
                st.caption(f"Received: {email['created_at']}")
                st.button(f"Open email #{email['id']}", key=f"open_{email['id']}", on_click=open_email, args=(email['id'],))
        with st.expander('Optional data table'):
            st.dataframe(pd.DataFrame(emails).drop(columns=['body', 'thread_id']), hide_index=True, width='stretch')
    elif emails is not None:
        st.info('Your inbox is empty for these filters. Add a fictional email above to get started.')

elif page in ['Email Details', 'Reply Review']:
    ident = st.number_input('Email ID', min_value=1, value=st.session_state.get('selected_email', 1))
    result = api('GET', f'/emails/{ident}/results')
    if result:
        email = result['email']
        st.subheader(email['subject'])
        st.caption(f"From {email['sender']} · {email['status']} · {email['created_at']}")
        if page == 'Email Details':
            left, right = st.columns([1, 1])
            with left:
                st.markdown('**Original message**')
                st.text(email['body'])
                if email['status'] in ['new', 'failed'] and st.button('Process email', type='primary', disabled=not can_write):
                    with st.spinner('Extracting information and looking up business records…'):
                        processed = api('POST', f'/emails/{ident}/process')
                    if processed:
                        st.rerun()
            with right:
                ext = result['extraction']
                if ext:
                    st.markdown('**Summary**')
                    st.write(ext['summary'])
                    st.caption('Extracted from email claims; database evidence is shown separately below.')
                    for field in ['category', 'sender', 'customer_name', 'invoice_number', 'amount', 'currency', 'due_date', 'order_number', 'urgency', 'requested_action', 'suggested_next_step']:
                        st.write(f"{field.replace('_', ' ').capitalize()}: {ext[field] if ext[field] is not None else 'Unknown'}")
                    st.caption(f"Model-reported confidence: {ext['confidence']:.0%}. Verify missing information and business evidence separately.")
                    with st.expander('Structured extraction JSON'):
                        st.json(ext)
                    if ext['missing_information']:
                        st.warning('Missing: ' + ', '.join(ext['missing_information']))
                    for item in ext['uncertainty']:
                        st.warning(item)
                else:
                    st.info('Process this email to see its extraction and draft.')
            with st.expander('Verified business evidence and tool activity'):
                for tool in result['tools']:
                    st.write(f"Tool: {readable(tool['name'])} · Status: {readable(tool['status'])}")
                    if not tool['outcome'].get('found'):
                        st.write('No verified matching record available.')
                    for record in tool['outcome'].get('records', []):
                        with st.container(border=True):
                            for field, value in record.items():
                                st.text(f"{field.replace('_', ' ').capitalize()}: {value}")
                with st.expander('Tool audit JSON'):
                    st.json(result['tools'])
            with st.expander('Processing history'):
                st.json(result['runs'])
        elif result['draft']:
            draft = result['draft']
            st.caption(f"Status: {draft['status']} · Revision {draft['revision']} · Reviewed: {draft['reviewed_at'] or 'Not yet'} · {draft['reviewed_by'] or ''}")
            text = st.text_area('Reply draft', draft['body'], height=300, key=f"draft_{draft['id']}_{draft['revision']}", disabled=not can_write)
            reviewer = user['username']
            st.caption(f"Review actions are recorded as {reviewer}." if can_write else 'Viewer access: editing and review decisions are disabled.')
            a, b, c = st.columns(3)
            if a.button('Save edits', disabled=not can_write):
                if api('PATCH', f"/drafts/{draft['id']}", json={'body': text, 'revision': draft['revision']}):
                    st.rerun()
            if b.button('Approve', type='primary', disabled=not can_write or text != draft['body']):
                if api('POST', f"/drafts/{draft['id']}/approve", json={'reviewer': reviewer, 'revision': draft['revision']}):
                    st.rerun()
            if c.button('Reject', disabled=not can_write):
                if api('POST', f"/drafts/{draft['id']}/reject", json={'reviewer': reviewer, 'revision': draft['revision']}):
                    st.rerun()
            if text != draft['body']:
                st.warning('Save your edits before approving. Saving clears any previous approval.')
            st.info('Approval is recorded only. Sending is disabled until a delivery integration is implemented and configured.')
        else:
            st.info('Process this email on Email Details to create a reply draft.')

elif page == 'Analytics':
    data = api('GET', '/analytics')
    if data:
        a, b, c, d = st.columns(4)
        a.metric('Emails', data['total_emails'])
        b.metric('Processed', data['statuses'].get('processed', 0))
        c.metric('Failures', data['processing_failures'])
        d.metric('Approved', data['drafts'].get('approved', 0))
        left, right = st.columns(2)
        with left:
            st.subheader('Category distribution')
            if data['categories']:
                st.bar_chart(pd.Series(data['categories'], name='Emails'))
                for category, count in data['categories'].items():
                    st.write(f'{readable(category)}: {count}')
            else:
                st.info('Process an email to populate this chart.')
        with right:
            st.subheader('Draft decisions')
            if data['drafts']:
                st.bar_chart(pd.Series(data['drafts'], name='Drafts'))
                for decision, count in data['drafts'].items():
                    st.write(f'{readable(decision)}: {count}')
            else:
                st.info('No drafts yet.')
        st.write(f"Validated extractions: {data['extraction_count']} · Missing fields: {data['missing_field_count']} · Validation failures: {data['validation_failures']}")
        st.subheader('Measured evaluation results')
        if data['evaluation']:
            st.json(data['evaluation'])
        else:
            st.info('No evaluation has been run. Run python -m evaluation.run_evaluation to produce a report.')

elif page == 'My Account':
    st.write(f"Username: {user['username']}")
    st.write(f"Role: {user['role'].capitalize()}")
    st.caption('Changing your password signs out all of your sessions. You will need to sign in again.')
    with st.form('change_password', clear_on_submit=True):
        current = st.text_input('Current password', type='password', max_chars=256)
        new = st.text_input('New password (at least 16 characters)', type='password', max_chars=256)
        repeat = st.text_input('Confirm new password', type='password', max_chars=256)
        if st.form_submit_button('Change my password', type='primary'):
            if new != repeat:
                st.error('The new passwords do not match.')
            elif len(new) < 16:
                st.error('Use at least 16 characters.')
            elif api('POST', '/auth/password', json={'current_password': current, 'new_password': new}):
                sign_out()
                st.rerun()

elif page == 'Users':
    st.write('Create a separate account for each person. All accounts belong to this shared business workspace.')
    st.table(pd.DataFrame([
        {'Role': 'Admin', 'Permissions': 'Read, process, edit, approve and manage user accounts'},
        {'Role': 'Reviewer', 'Permissions': 'Read, process, edit, approve and reject drafts'},
        {'Role': 'Viewer', 'Permissions': 'Read emails, results, drafts and analytics'}]))
    with st.expander('Create an account', expanded=True):
        with st.form('create_user', clear_on_submit=True):
            username = st.text_input('New username', max_chars=80, help='3–80 letters, numbers, dots, underscores, @, + or hyphens. Usernames are case-insensitive.')
            display_name = st.text_input('Display name', max_chars=120)
            password = st.text_input('Initial password (at least 16 characters)', type='password', max_chars=256)
            role = st.selectbox('New account role', ['viewer', 'reviewer', 'admin'])
            if st.form_submit_button('Create account', type='primary'):
                if api('POST', '/users', json=dict(username=username, display_name=display_name, password=password, role=role)):
                    st.success('Account created. Share their username, password and dashboard link privately. They can change their password under My Account.')
    accounts = api('GET', '/users')
    if accounts:
        st.subheader('Existing accounts')
        st.table(pd.DataFrame(accounts).drop(columns=['created_at']))
        selected = st.selectbox('Account to manage', [a['id'] for a in accounts],
            format_func=lambda ident: next(f"{a['display_name']} ({a['username']})" for a in accounts if a['id'] == ident))
        selected_user = next(a for a in accounts if a['id'] == selected)
        with st.form(f'edit_user_{selected}'):
            roles = ['viewer', 'reviewer', 'admin']
            role = st.selectbox('Role', roles, index=roles.index(selected_user['role']))
            active = st.checkbox('Account enabled', value=selected_user['active'])
            if st.form_submit_button('Save permissions'):
                if api('PATCH', f'/users/{selected}', json={'role': role, 'active': active}):
                    st.rerun()
        with st.expander('Reset this account’s password'):
            st.caption('Resetting a password signs that person out on every device. The last active admin cannot be disabled or demoted.')
            with st.form(f'reset_password_{selected}', clear_on_submit=True):
                new_password = st.text_input('Replacement password (at least 16 characters)', type='password', max_chars=256)
                if st.form_submit_button('Reset password'):
                    if api('POST', f'/users/{selected}/reset-password', json={'new_password': new_password}):
                        st.success('Password reset. Share the replacement privately with that person.')
        with st.expander('Account and review activity'):
            events = api('GET', '/users/audit/events')
            if events:
                st.table(pd.DataFrame(events))
