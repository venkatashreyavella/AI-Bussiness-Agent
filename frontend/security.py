"""Use individual API sessions. No service credential is used for dashboard requests."""
import os
import httpx
import streamlit as st


def base_url():
    return os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def clear_session():
    for key in list(st.session_state):
        del st.session_state[key]


def sign_out():
    token = st.session_state.get('auth_token')
    if token:
        try:
            httpx.request('POST', base_url() + '/auth/logout', headers={'Authorization': 'Bearer ' + token}, timeout=10)
        except httpx.HTTPError:
            pass
    clear_session()


def require_login():
    token = st.session_state.get('auth_token')
    if token:
        try:
            response = httpx.request('GET', base_url() + '/auth/me', headers={'Authorization': 'Bearer ' + token}, timeout=10)
            if response.status_code == 200:
                user = response.json()
                st.session_state['current_user'] = user
                return user
            if response.status_code != 401:
                st.error('Account verification is temporarily unavailable. Please try again.')
                st.stop()
        except (httpx.HTTPError, ValueError):
            st.error('Cannot reach the sign-in service. Please try again.')
            st.stop()
        clear_session()
    st.title('Sign in to Business Inbox')
    st.caption('Accounts use the shared business workspace. Sessions expire after one hour.')
    registration_enabled = False
    try:
        options = httpx.request('GET', base_url() + '/auth/registration', timeout=10)
        if options.status_code == 200:
            registration_enabled = options.json().get('enabled') is True
    except (httpx.HTTPError, ValueError):
        pass
    st.write('New here? Choose Create account to pick your own username and password.' if registration_enabled
             else 'Use your own username and password to sign in.')
    panels = st.tabs(['Sign in', 'Create account'] if registration_enabled else ['Sign in'])
    with panels[0]:
        with st.form('dashboard_sign_in', clear_on_submit=True):
            username = st.text_input('Username', max_chars=80)
            password = st.text_input('Password', type='password', max_chars=256)
            submitted = st.form_submit_button('Sign in', type='primary')
        if submitted:
            try:
                response = httpx.request('POST', base_url() + '/auth/login',
                                        json={'username': username, 'password': password}, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    st.session_state['auth_token'] = data['access_token']
                    st.session_state['current_user'] = data['user']
                    st.rerun()
                detail = response.json().get('detail')
                st.error(detail if isinstance(detail, str) else 'Enter a valid username and password.')
            except (httpx.HTTPError, ValueError, KeyError):
                st.error('Cannot reach the sign-in service. Please try again.')
    if registration_enabled:
        with panels[1]:
            st.write('Create your own account. No administrator-created login is needed.')
            st.info('New accounts can read, add and process emails, edit drafts, and approve or reject replies in the shared workspace. Account administration stays with Admins.')
            with st.form('public_registration', clear_on_submit=False):
                new_username = st.text_input('Choose a username', max_chars=80,
                    help='3–80 letters, numbers, dots, underscores, @, + or hyphens. Usernames are case-insensitive.')
                display_name = st.text_input('Your name (optional)', max_chars=120)
                new_password = st.text_input('Choose a password (at least 16 characters)', type='password', max_chars=256, key='signup_password')
                confirmation = st.text_input('Confirm password', type='password', max_chars=256, key='signup_confirmation')
                create = st.form_submit_button('Create account', type='primary')
            if create:
                if new_password != confirmation:
                    st.error('The passwords do not match.')
                elif len(new_password) < 16:
                    st.error('Use a password of at least 16 characters.')
                else:
                    try:
                        response = httpx.request('POST', base_url() + '/auth/register', json={
                            'username': new_username, 'display_name': display_name or None, 'password': new_password}, timeout=15)
                        if response.status_code == 201:
                            data = response.json()
                            clear_session()
                            st.session_state['auth_token'] = data['access_token']
                            st.session_state['current_user'] = data['user']
                            st.session_state['just_registered'] = True
                            st.rerun()
                        detail = response.json().get('detail')
                        st.error(detail if isinstance(detail, str) else 'Choose a valid username and a password of at least 16 characters.')
                    except (httpx.HTTPError, ValueError, KeyError):
                        st.error('Cannot reach account creation. Please try again.')
    st.stop()
