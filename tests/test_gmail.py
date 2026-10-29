import base64
import hashlib
import json
from datetime import timedelta
from email.message import EmailMessage as MimeMessage
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlparse, parse_qs
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from app.core.config import Settings, get_settings
from app.core.security import Principal, token_hash
from app.models import EmailMessage, ReplyDraft, GmailOAuthState, GmailConnection, utcnow
from app.schemas.gmail import SendRequest
from app.services.business_tools import BusinessTools
from app.services.gmail_service import (begin_oauth, finish_oauth, cipher, parse_gmail, sync_mailbox,
                                       send_approved_draft, SCOPES)


@pytest.fixture
def settings():
    return Settings(llm_provider='demo', google_client_id='test-client.apps.googleusercontent.com',
        google_client_secret='test-client-secret', google_redirect_uri='http://127.0.0.1:8501/',
        token_encryption_key=Fernet.generate_key().decode())


def auth(client, username):
    response = client.post('/auth/login', json={'username': username, 'password': 'correct-test-password-123'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def private_message(db, owner, **changes):
    message = EmailMessage(sender='sender@example.com', subject='Invoice query', body='Please check INV-1042.',
        fingerprint=token_hash('private:' + owner.username + str(changes)), owner_user_id=owner.id,
        gmail_message_id='gmail-1', gmail_thread_id='thread-1', reply_to='reply@example.com',
        original_message_id='<original@example.com>', **changes)
    db.add(message)
    db.commit()
    return message


def raw_message(body='Please check INV-1042.', html=False):
    message = MimeMessage()
    message['From'], message['To'], message['Subject'] = 'Sender <sender@example.com>', 'me@example.com', 'Invoice query'
    message['Reply-To'], message['Message-ID'] = 'reply@example.com', '<original@example.com>'
    message.set_content(body, subtype='html' if html else 'plain')
    return {'id': 'gmail-1', 'threadId': 'thread-1', 'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}


def test_oauth_state_uses_pkce_and_encryption(db, account_factory, settings):
    owner = account_factory()
    actor = Principal(owner.username, owner.role, owner.id)
    url = begin_oauth(db, actor, settings)
    params = parse_qs(urlparse(url).query)
    state = db.scalar(select(GmailOAuthState))
    assert token_hash(params['state'][0]) == state.state_hash
    verifier = cipher(settings).decrypt(state.encrypted_verifier.encode()).decode()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    assert params['code_challenge'][0] == expected and params['code_challenge_method'] == ['S256']
    assert settings.google_client_secret not in url and verifier not in url


def test_callback_encrypts_credentials_and_rejects_replay(db, account_factory, settings):
    owner = account_factory()
    state = parse_qs(urlparse(begin_oauth(db, Principal(owner.username, owner.role, owner.id), settings)).query)['state'][0]
    credentials = SimpleNamespace(refresh_token='refresh-secret', granted_scopes=SCOPES, scopes=SCOPES,
        to_json=lambda: json.dumps({'refresh_token': 'refresh-secret'}))
    flow = Mock(credentials=credentials)
    with patch('app.services.gmail_service.oauth_flow', return_value=flow), patch('app.services.gmail_service.GmailProvider') as provider:
        provider.return_value.profile.return_value = {'emailAddress': 'me@example.com'}
        finish_oauth(db, 'oauth-code', state, settings, owner.id)
        connection = db.scalar(select(GmailConnection))
        assert connection.user_id == owner.id and 'refresh-secret' not in connection.encrypted_credentials
        assert 'refresh-secret' in cipher(settings).decrypt(connection.encrypted_credentials.encode()).decode()
        with pytest.raises(HTTPException) as error:
            finish_oauth(db, 'oauth-code', state, settings, owner.id)
        assert error.value.status_code == 400 and flow.fetch_token.call_count == 1


def test_oauth_expiry_and_error_redaction(db, account_factory, settings):
    owner = account_factory()
    state = parse_qs(urlparse(begin_oauth(db, Principal(owner.username, owner.role, owner.id), settings)).query)['state'][0]
    record = db.scalar(select(GmailOAuthState))
    record.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as error:
        finish_oauth(db, 'code', state, settings, owner.id)
    assert error.value.status_code == 400
    record.expires_at = utcnow() + timedelta(minutes=5)
    db.commit()
    with patch('app.services.gmail_service.oauth_flow') as flow:
        flow.return_value.fetch_token.side_effect = RuntimeError('secret-token')
        with pytest.raises(HTTPException) as error:
            finish_oauth(db, 'code', state, settings, owner.id)
        assert error.value.status_code == 502 and 'secret-token' not in error.value.detail


def test_sync_private_deduplicated_import(db, account_factory, settings):
    owner = account_factory()
    actor = Principal(owner.username, owner.role, owner.id)
    provider = Mock(credentials=None)
    provider.list_messages.return_value = [{'id': 'gmail-1'}]
    provider.get_raw.return_value = raw_message()
    assert sync_mailbox(db, actor, settings, provider)['imported'] == 1
    assert sync_mailbox(db, actor, settings, provider)['imported'] == 0
    assert provider.get_raw.call_count == 1
    email = db.scalar(select(EmailMessage))
    assert email.owner_user_id == owner.id and email.reply_to == 'reply@example.com'
    assert email.thread_id.startswith(f'gmail:{owner.id}:')


def test_html_import_does_not_include_script_or_fetch_images():
    data, recipient, ident = parse_gmail(raw_message('<p>Hello</p><script>steal_secret()</script><img src="https://invalid.example/tracker">', html=True))
    assert 'Hello' in data.body and 'steal_secret' not in data.body
    assert recipient == 'reply@example.com' and ident == '<original@example.com>'
    with pytest.raises(ValueError):
        parse_gmail({'raw': 'a' * 2_700_001})


def test_gmail_sync_failure_is_safe(db, account_factory, settings):
    owner = account_factory()
    provider = Mock()
    provider.list_messages.side_effect = TimeoutError('private-token')
    with pytest.raises(HTTPException) as error:
        sync_mailbox(db, Principal(owner.username, owner.role, owner.id), settings, provider)
    assert error.value.status_code == 502 and 'private-token' not in error.value.detail


def test_private_mail_hidden_from_other_users_admin_and_service(client, db, account_factory):
    owner, other = account_factory('alice', 'reviewer'), account_factory('bob', 'admin')
    email = private_message(db, owner)
    draft = ReplyDraft(email_id=email.id, body='Private reply', status='approved')
    db.add(draft)
    db.commit()
    owner_auth, other_auth = auth(client, 'alice'), auth(client, 'bob')
    for headers in [other_auth, {'Authorization': 'Bearer test-token'}]:
        assert client.get('/emails', headers=headers).json() == []
        assert client.get('/analytics', headers=headers).json()['total_emails'] == 0
        for suffix in ['', '/results']:
            assert client.get(f'/emails/{email.id}{suffix}', headers=headers).status_code == 404
        assert client.post(f'/emails/{email.id}/process', headers=headers).status_code == 404
        assert client.patch(f'/drafts/{draft.id}', headers=headers, json={'body': 'stolen', 'revision': 1}).status_code == 404
        assert client.post(f'/drafts/{draft.id}/approve', headers=headers, json={'revision': 1, 'reviewer': 'bob'}).status_code == 404
        assert client.post(f'/drafts/{draft.id}/send', headers=headers).status_code == 404
    assert client.get(f'/emails/{email.id}', headers=owner_auth).json()['private'] is True
    assert client.post(f'/emails/{email.id}/process', headers=owner_auth).status_code == 409  # live AI required


def test_demo_business_records_excluded_from_live_mail(db):
    tools = BusinessTools(db, include_demo_records=False)
    assert tools.execute('get_invoice_status', {'invoice_number': 'INV-1042'})['found'] is False
    assert tools.execute('get_order_status', {'order_number': 'ORD-2041'})['found'] is False
    assert tools.execute('search_customer', {'customer_name_or_email': 'Aisha'})['found'] is False
    assert tools.execute('search_business_records', {'query': '1042'})['found'] is False


def test_private_thread_context_never_crosses_owner(db, account_factory, settings):
    from app.services.email_service import process_email
    from app.services.llm_service import DemoProvider
    alice, bob = account_factory('alice', 'reviewer'), account_factory('bob', 'reviewer')
    prior = private_message(db, alice, thread_id='same-thread')
    private_message(db, bob, thread_id='same-thread')
    db.add(EmailMessage(sender='shared@example.com', subject='Shared secret', body='Shared context', thread_id='same-thread', fingerprint='shared'))
    current = private_message(db, alice, thread_id='same-thread', status='new')
    provider = DemoProvider()
    original = provider.extract_email_data
    provider.extract_email_data = Mock(side_effect=original)
    assert process_email(db, current.id, settings, provider).status == 'processed'
    context = provider.extract_email_data.call_args.args[1]
    assert len(context) == 1 and context[0]['subject'] == prior.subject


@pytest.fixture
def approved(db, account_factory):
    owner = account_factory()
    email = private_message(db, owner)
    draft = ReplyDraft(email_id=email.id, body='A reviewed real reply.', status='approved', reviewed_by=owner.username, revision=3)
    db.add(draft)
    db.commit()
    return draft, Principal(owner.username, owner.role, owner.id)


def live_settings(settings):
    return settings.model_copy(update={'llm_provider': 'openai', 'gmail_send_enabled': True})


def test_approved_send_confirmation_and_duplicate_prevention(db, approved, settings):
    draft, actor = approved
    provider = Mock(credentials=None)
    provider.send.return_value = {'id': 'confirmed-sent-id'}
    request = SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND')
    send_approved_draft(db, draft, actor, request, live_settings(settings), provider)
    assert draft.delivery_status == 'sent' and draft.gmail_sent_id == 'confirmed-sent-id' and draft.sent_at
    send_approved_draft(db, draft, actor, request, live_settings(settings), provider)
    assert provider.send.call_count == 1
    raw = provider.send.call_args.args[0]['raw']
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert 'To: reply@example.com' in decoded and 'In-Reply-To: <original@example.com>' in decoded


@pytest.mark.parametrize('case', ['unapproved', 'stale', 'wrong-recipient', 'wrong-owner', 'offline'])
def test_send_guards_do_not_contact_google(db, approved, settings, case):
    draft, actor = approved
    cfg = live_settings(settings)
    recipient, revision = 'reply@example.com', 3
    if case == 'unapproved':
        draft.status = 'pending'
    elif case == 'stale':
        revision = 2
    elif case == 'wrong-recipient':
        recipient = 'other@example.com'
    elif case == 'wrong-owner':
        actor = Principal('other', 'admin', actor.user_id + 1)
    elif case == 'offline':
        cfg = settings
    provider = Mock()
    with pytest.raises(HTTPException):
        send_approved_draft(db, draft, actor, SendRequest(revision=revision, recipient=recipient, confirmation='SEND'), cfg, provider)
    provider.send.assert_not_called()


def test_delivery_timeout_locks_ambiguous_result(db, approved, settings):
    draft, actor = approved
    provider = Mock()
    provider.send.side_effect = TimeoutError('private-token')
    request = SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND')
    with pytest.raises(HTTPException) as error:
        send_approved_draft(db, draft, actor, request, live_settings(settings), provider)
    assert draft.delivery_status == 'unknown' and 'private-token' not in error.value.detail
    with pytest.raises(HTTPException) as retry:
        send_approved_draft(db, draft, actor, request, live_settings(settings), provider)
    assert retry.value.status_code == 409 and provider.send.call_count == 1


def test_gmail_setup_status_no_credentials_or_service_access(client):
    assert client.get('/gmail/status').json()['configured'] is False
    assert client.post('/gmail/connect').status_code == 403
    assert client.post('/gmail/sync').status_code == 403


def test_provider_send_never_uses_automatic_retries():
    from app.services.gmail_service import GmailProvider
    service = Mock()
    GmailProvider(service=service).send({'raw': 'test'})
    service.users().messages().send.assert_called_once_with(userId='me', body={'raw': 'test'})
    service.users().messages().send().execute.assert_called_once_with(num_retries=0)


def test_disconnect_revokes_only_own_connection(client, db, account_factory, settings, monkeypatch):
    alice, bob = account_factory('alice', 'viewer'), account_factory('bob', 'admin')
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', settings.token_encryption_key)
    get_settings.cache_clear()
    for user in [alice, bob]:
        db.add(GmailConnection(user_id=user.id, email_address=user.username + '@example.com',
            encrypted_credentials=cipher(settings).encrypt(json.dumps({'refresh_token': user.username + '-token'}).encode()).decode()))
    db.commit()
    with patch('app.api.gmail.requests.post') as revoke:
        revoke.return_value.status_code = 200
        assert client.post('/gmail/disconnect', headers=auth(client, 'alice')).status_code == 204
        assert revoke.call_args.kwargs['data'] == {'token': 'alice-token'}
        assert 'params' not in revoke.call_args.kwargs
    assert db.scalar(select(GmailConnection).where(GmailConnection.user_id == alice.id)) is None
    assert db.scalar(select(GmailConnection).where(GmailConnection.user_id == bob.id)) is not None


def test_delivery_attempt_cannot_be_edited_or_reviewed(client, db, account_factory):
    owner = account_factory()
    email = private_message(db, owner)
    draft = ReplyDraft(email_id=email.id, body='Already attempted', status='approved', delivery_status='unknown')
    db.add(draft)
    db.commit()
    headers = auth(client, owner.username)
    assert client.patch(f'/drafts/{draft.id}', headers=headers, json={'body': 'changed', 'revision': 1}).status_code == 409
    assert client.post(f'/drafts/{draft.id}/approve', headers=headers, json={'reviewer': owner.username, 'revision': 1}).status_code == 409


def test_atomic_delivery_claim_prevents_stale_cached_edits(client, db, account_factory):
    from sqlalchemy import update
    owner = account_factory()
    email = private_message(db, owner)
    draft = ReplyDraft(email_id=email.id, body='Approved original', status='approved')
    db.add(draft)
    db.commit()
    db.execute(update(ReplyDraft).where(ReplyDraft.id == draft.id).values(delivery_status='sending'), execution_options={'synchronize_session': False})
    db.commit()
    assert draft.delivery_status == 'not_sent'  # simulate a competing request with a cached snapshot
    assert client.patch(f'/drafts/{draft.id}', headers=auth(client, owner.username), json={'body': 'racing edit', 'revision': 1}).status_code == 409


def test_oauth_callback_requires_same_signed_in_identity(client, db, account_factory, settings):
    owner, other = account_factory('alice', 'reviewer'), account_factory('bob', 'reviewer')
    state = parse_qs(urlparse(begin_oauth(db, Principal(owner.username, owner.role, owner.id), settings)).query)['state'][0]
    with patch('app.services.gmail_service.oauth_flow') as flow:
        response = client.post('/gmail/callback', headers=auth(client, 'bob'), json={'code': 'fake-code', 'state': state})
        assert response.status_code == 400
        flow.assert_not_called()
    record = db.scalar(select(GmailOAuthState).where(GmailOAuthState.state_hash == token_hash(state)))
    assert not record.used
    assert client.post('/gmail/callback', json={'code': 'fake-code', 'state': state}, headers={'Authorization': ''}).status_code == 401


def test_reconnecting_another_mailbox_cannot_send_old_mail(db, approved, settings):
    draft, actor = approved
    provider = Mock(credentials=None)
    connection = SimpleNamespace(email_address='different-mailbox@example.com')
    with patch('app.services.gmail_service.connected_provider', return_value=(connection, provider)):
        with pytest.raises(HTTPException) as error:
            send_approved_draft(db, draft, actor, SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND'), live_settings(settings))
        assert error.value.status_code == 409
        provider.send.assert_not_called()
