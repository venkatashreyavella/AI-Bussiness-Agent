import os
import httpx
import streamlit as st


def handle_callback():
    if 'code' not in st.query_params and 'error' not in st.query_params:
        return
    code, state = st.query_params.get('code'), st.query_params.get('state')
    error = st.query_params.get('error')
    st.query_params.clear()
    if error or not code or not state:
        st.warning('Google connection was cancelled or incomplete. Sign in and start again.')
        return
    st.session_state['pending_gmail_callback'] = {'code': code, 'state': state}
    st.info('Sign in to the same application account that started Gmail connection to complete it.')


def complete_callback():
    pending = st.session_state.pop('pending_gmail_callback', None)
    if not pending:
        return
    try:
        response = httpx.request('POST', os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/') + '/gmail/callback',
                                json=pending, headers={'Authorization': 'Bearer ' + st.session_state['auth_token']}, timeout=60)
        if response.status_code == 200:
            st.success('Gmail connected. Sign in if requested, then open Gmail to sync messages.')
        else:
            st.error('Gmail connection could not be completed. Use the account that started connection, check OAuth settings, and reconnect.')
    except httpx.HTTPError:
        st.error('The Gmail connection service is unavailable. Start the connection again after signing in.')


def gmail_page(api, can_write):
    status = api('GET', '/gmail/status')
    if not status:
        return
    st.write('Connect Gmail, import recent inbox messages, review drafts, and explicitly confirm delivery.')
    st.info('Gmail imports are private to your account. Other users, other administrators and demo integrations cannot read them. Manual demo emails remain shared.')
    if not status['live_ai_enabled']:
        st.warning('Live AI is not configured yet. Add an OpenAI API key and model, then set LLM_PROVIDER=openai. Gmail sending is blocked in demo mode.')
    if not status['configured']:
        st.warning('Gmail setup is incomplete: ' + ', '.join(status['missing_settings']))
        st.markdown('Open the project’s **GMAIL_SETUP.md** for Google Cloud setup and private environment configuration.')
        st.write('Required: enable Gmail API, create a Web application OAuth client, and register the exact dashboard redirect URL.')
        return
    if status['connected']:
        st.success('Connected Gmail: ' + status['email_address'])
        st.caption('Last sync: ' + (status['last_synced_at'] or 'Not yet synced'))
        if st.button('Sync latest 20 Gmail messages', type='primary', disabled=not can_write):
            with st.spinner('Importing private inbox messages…'):
                result = api('POST', '/gmail/sync')
            if result:
                st.success(f"Imported {result['imported']} messages. Skipped {result['skipped']} invalid or oversized messages. Open Inbox to process them.")
        st.caption('Sync does not mark messages as read or change Gmail labels. Attachments are not opened or executed. Sync again to fetch new messages; existing imports are reused.')
        if st.button('Disconnect Gmail'):
            if api('POST', '/gmail/disconnect'):
                st.rerun()
        st.caption('Disconnect revokes Gmail access. Previously imported emails remain private in the application.')
    elif can_write and st.button('Connect my Gmail', type='primary'):
        result = api('POST', '/gmail/connect')
        if result:
            st.link_button('Continue to Google consent', result['authorization_url'])
            st.caption('Choose your Google account and review read/send permissions. A Gmail password is never entered into this app.')
