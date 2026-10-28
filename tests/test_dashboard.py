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
        assert requests.call_count == 0
        sign_in(app, 'owner')
        assert not any(field.label == 'Access token' for field in app.text_input)
        next(button for button in app.button if button.label == f'Open email #{ident}').click().run()
        assert app.radio[0].value == 'Email Details'
        for page in ['Email Details', 'Reply Review', 'Analytics', 'My Account', 'Users']:
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
        assert all('/auth/login' in call.args[1] for call in requests.call_args_list)


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
