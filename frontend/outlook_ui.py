import streamlit as st


def outlook_page(api, can_write):
    status = api('GET', '/outlook/status')
    if not status:
        return
    st.write('Connect Outlook, import recent inbox messages, review drafts, and explicitly confirm delivery.')
    st.info('Outlook imports are private to your account. Other users, other administrators and demo integrations cannot read them. Manual demo emails remain shared.')
    if not status['live_ai_enabled']:
        st.warning('Live AI is not configured yet. Add an OpenAI API key and model, then set LLM_PROVIDER=openai. Outlook sending is blocked in demo mode.')
    if not status['configured']:
        st.warning('Outlook setup is incomplete: ' + ', '.join(status['missing_settings']))
        st.markdown('Open the project **OUTLOOK_SETUP.md** for Microsoft Entra setup and private environment configuration.')
        st.write('Required: register a Microsoft Entra Web application, allow delegated User.Read, Mail.Read and Mail.Send permissions, and register the exact dashboard redirect URL.')
        return
    if status['connected']:
        st.success('Connected Outlook: ' + status['email_address'])
        st.caption('Last sync: ' + (status['last_synced_at'] or 'Not yet synced'))
        if st.button('Sync latest 20 Outlook messages', type='primary', disabled=not can_write):
            with st.spinner('Importing private inbox messages...'):
                result = api('POST', '/outlook/sync')
            if result:
                st.success(f"Imported {result['imported']} messages. Skipped {result['skipped']} invalid or oversized messages. Open Inbox to process them.")
        st.caption('Sync does not mark messages as read or change Outlook folders. Attachments are not opened or executed. Sync again to fetch new messages; existing imports are reused.')
        if st.button('Disconnect Outlook'):
            if api('POST', '/outlook/disconnect'):
                st.rerun()
        st.caption('Disconnect removes saved Outlook credentials. Revoke the app separately in Microsoft account permissions to withdraw consent. Imported emails stay private.')
    elif can_write and st.button('Connect my Outlook', type='primary'):
        result = api('POST', '/outlook/connect')
        if result:
            st.link_button('Continue to Microsoft consent', result['authorization_url'])
            st.caption('Choose your Microsoft account and review read/send permissions. An Outlook password is never entered into this app.')
