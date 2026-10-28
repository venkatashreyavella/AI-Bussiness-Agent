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
    st.write('Use your own account to access the shared business workspace.')
    st.caption('Your administrator supplies your username and password. Sessions expire after one hour.')
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
    st.stop()
