from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest

SCRIPT = str(Path(__file__).resolve().parents[1] / 'frontend/streamlit_app.py')
PASSWORD = 'correct-test-password-123'


def bridge(client):
    def request(method, url, **kwargs):
        kwargs.pop('timeout', None)
        return client.request(method, url.split(':8000')[-1], **kwargs)
    return request


def sign_in(app, username):
    app.text_input[0].set_value(username)
    app.text_input[1].set_value(PASSWORD)
    app.button[0].click().run()
    assert not app.exception


def test_dashboard_pages(client, payload, account_factory):
    account_factory()
    ident = client.post('/emails', json=payload).json()['id']
    assert client.post(f'/emails/{ident}/process').status_code == 200
    with patch('httpx.request', side_effect=bridge(client)) as requests:
        app = AppTest.from_file(SCRIPT, default_timeout=20).run()
        assert all('/auth/registration' in call.args[1] for call in requests.call_args_list)
        sign_in(app, 'owner')
        assert not any(field.label == 'Access token' for field in app.text_input)
        next(button for button in app.button if button.label == f'Open email #{ident}').click().run()
        assert app.radio[0].value == 'Email Details'
        for page in ['Email Details', 'Reply Review', 'Analytics', 'Gmail', 'Outlook', 'My Account', 'Users']:
            app.radio[0].set_value(page).run()
            assert not app.exception
        assert 'Create account' in [b.label for b in app.button]
        next(button for button in app.button if button.label == 'Sign out').click().run()
        assert app.title[0].value == 'Sign in to Business Inbox' and not app.radio


def test_wrong_password_cannot_read_inbox(client, account_factory):
    account_factory()
    with patch('httpx.request', side_effect=bridge(client)) as requests:
        app = AppTest.from_file(SCRIPT).run()
        app.text_input[0].set_value('owner')
        app.text_input[1].set_value('incorrect-password')
        app.button[0].click().run()
        assert app.error[0].value == 'Username or password is incorrect'
        assert not app.radio and not app.text_area
        assert all(any(path in call.args[1] for path in ['/auth/login', '/auth/registration']) for call in requests.call_args_list)


def test_viewer_dashboard_is_read_only(client, payload, account_factory):
    account_factory(username='reader', role='viewer')
    ident = client.post('/emails', json=payload).json()['id']
    client.post(f'/emails/{ident}/process')
    with patch('httpx.request', side_effect=bridge(client)):
        app = AppTest.from_file(SCRIPT, default_timeout=20).run()
        sign_in(app, 'reader')
        assert 'Users' not in app.radio[0].options
        app.radio[0].set_value('Reply Review').run()
        assert not app.exception and app.text_area[0].disabled
        assert all(b.disabled for b in app.button if b.label in ['Approve', 'Reject', 'Save edits'])


def test_service_outage_does_not_grant_access():
    import httpx
    with patch('httpx.request', side_effect=httpx.ConnectError('offline')):
        app = AppTest.from_file(SCRIPT).run()
        app.text_input[0].set_value('owner')
        app.text_input[1].set_value(PASSWORD)
        app.button[0].click().run()
        assert 'Cannot reach' in app.error[0].value and not app.radio


def test_admin_creates_separate_viewer_account(client, account_factory):
    account_factory()
    with patch('httpx.request', side_effect=bridge(client)):
        app = AppTest.from_file(SCRIPT, default_timeout=20).run()
        sign_in(app, 'owner')
        app.radio[0].set_value('Users').run()
        for field in app.text_input:
            if field.label == 'New username':
                field.set_value('new.viewer')
            elif field.label == 'Display name':
                field.set_value('New Viewer')
            elif field.label == 'Initial password (at least 16 characters)':
                field.set_value(PASSWORD)
        next(button for button in app.button if button.label == 'Create account').click().run()
        assert not app.exception and any('Account created' in item.value for item in app.success)
        response = client.post('/auth/login', json={'username': 'new.viewer', 'password': PASSWORD})
        assert response.status_code == 200 and response.json()['user']['role'] == 'viewer'


def test_password_validation_does_not_echo_secret(client, account_factory):
    account_factory()
    with patch('httpx.request', side_effect=bridge(client)):
        app = AppTest.from_file(SCRIPT, default_timeout=20).run()
        sign_in(app, 'owner')
        app.radio[0].set_value('Users').run()
        for field in app.text_input:
            if field.label == 'New username':
                field.set_value('new.viewer')
            elif field.label == 'Display name':
                field.set_value('New Viewer')
            elif field.label == 'Initial password (at least 16 characters)':
                field.set_value('secret123')
        next(button for button in app.button if button.label == 'Create account').click().run()
        assert not app.exception and app.error
        assert 'secret123' not in app.error[0].value


def test_self_registration_signs_in_as_reviewer(client, account_factory):
    account_factory()
    with patch('httpx.request', side_effect=bridge(client)):
        app = AppTest.from_file(SCRIPT, default_timeout=20).run()
        values = {'Choose a username': 'self.registered', 'Your name (optional)': 'Self Registered',
                  'Choose a password (at least 16 characters)': PASSWORD, 'Confirm password': PASSWORD}
        for field in app.text_input:
            if field.label in values:
                field.set_value(values[field.label])
        next(button for button in app.button if button.label == 'Create account').click().run()
        assert not app.exception
        assert app.radio[0].value == 'Inbox' and 'Users' not in app.radio[0].options
        assert any('Your account is ready' in item.value for item in app.success)
        app.radio[0].set_value('My Account').run()
        assert any('self.registered' in item.value for item in app.markdown)


def test_registration_password_mismatch_never_submits(client, account_factory):
    account_factory()
    with patch('httpx.request', side_effect=bridge(client)) as requests:
        app = AppTest.from_file(SCRIPT).run()
        for field in app.text_input:
            if field.label == 'Choose a password (at least 16 characters)':
                field.set_value(PASSWORD)
            elif field.label == 'Confirm password':
                field.set_value('different-test-password')
        next(button for button in app.button if button.label == 'Create account').click().run()
        assert any('do not match' in error.value for error in app.error)
        assert not any('/auth/register' in call.args[1] for call in requests.call_args_list)


def test_disabled_registration_hides_signup(client, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv('PUBLIC_SIGNUP_ENABLED', 'false')
    get_settings.cache_clear()
    with patch('httpx.request', side_effect=bridge(client)):
        app = AppTest.from_file(SCRIPT).run()
        assert not app.exception
        assert not any(button.label == 'Create account' for button in app.button)
        assert not any('New here?' in item.value for item in app.markdown)


def test_gmail_callback_waits_for_login_and_clears_url(client, account_factory):
    user = account_factory()
    with patch('httpx.request', side_effect=bridge(client)) as requests, patch('app.api.gmail.finish_oauth') as finish:
        app = AppTest.from_file(SCRIPT, default_timeout=20)
        app.query_params['code'] = 'private-authorization-code'
        app.query_params['state'] = 's' * 54
        app.run()
        assert not any('/gmail/callback' in call.args[1] for call in requests.call_args_list)
        assert not app.query_params
        sign_in(app, 'owner')
        assert finish.call_count == 1
        assert finish.call_args.args[-1] == user.id
        assert any('Gmail connected' in item.value for item in app.success)


def test_outlook_callback_routes_to_microsoft_after_login(client, account_factory):
    user = account_factory()
    with patch('httpx.request', side_effect=bridge(client)) as requests, patch('app.api.outlook.finish_oauth') as finish:
        app = AppTest.from_file(SCRIPT, default_timeout=20)
        app.query_params['code'] = 'private-microsoft-code'
        app.query_params['state'] = 'outlook:' + 's' * 54
        app.run()
        assert not app.query_params
        assert not any('/outlook/callback' in call.args[1] for call in requests.call_args_list)
        sign_in(app, 'owner')
        assert finish.call_count == 1 and finish.call_args.args[-1] == user.id
        assert any('Outlook connected' in item.value for item in app.success)
