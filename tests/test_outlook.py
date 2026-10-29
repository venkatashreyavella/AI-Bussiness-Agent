import base64
import json
from datetime import timedelta
from email.message import EmailMessage as MimeMessage
from unittest.mock import Mock, patch
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from app.core.config import Settings, get_settings
from app.core.security import Principal, token_hash
from app.models import EmailMessage, ReplyDraft, OutlookConnection, OutlookOAuthState, GmailConnection, utcnow
from app.schemas.gmail import SendRequest
from app.services import outlook_service as outlook


@pytest.fixture
def settings():
    return Settings(microsoft_client_id='test-client', microsoft_client_secret='test-secret',
        token_encryption_key=Fernet.generate_key().decode(), llm_provider='demo')


def actor(user):
    return Principal(user.username, user.role, user.id)


def begin(db, user, settings):
    client = Mock()
    client.initiate_auth_code_flow.side_effect = lambda scopes, **kw: {
        'auth_uri': 'https://login.microsoftonline.com/common/authorize',
        'state': kw['state'], 'code_verifier': 'private-pkce-verifier'}
    with patch.object(outlook, 'oauth_client', return_value=client):
        outlook.begin_oauth(db, actor(user), settings)
    record = db.scalar(select(OutlookOAuthState))
    flow = json.loads(outlook.cipher(settings).decrypt(record.encrypted_flow.encode()))
    return record, flow


def test_oauth_encrypted_flow_identity_expiry_and_replay(db, account_factory, settings):
    owner = account_factory()
    record, flow = begin(db, owner, settings)
    assert flow['state'].startswith('outlook:') and token_hash(flow['state']) == record.state_hash
    assert 'private-pkce' not in record.encrypted_flow
    with patch.object(outlook, 'oauth_client') as client:
        with pytest.raises(HTTPException) as err:
            outlook.finish_oauth(db, 'code', flow['state'], settings, owner.id + 1)
        assert err.value.status_code == 400 and not client.called
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            outlook.finish_oauth(db, 'code', flow['state'], settings, owner.id)
        assert not client.called
    record.expires_at = utcnow() + timedelta(minutes=5)
    db.commit()
    client = Mock()
    client.acquire_token_by_auth_code_flow.return_value = {'access_token': 'private-token', 'scope': 'User.Read Mail.Read Mail.Send'}
    with patch.object(outlook, 'oauth_client', return_value=client), patch.object(outlook, 'OutlookProvider') as provider:
        provider.return_value.profile.return_value = {'mail': 'me@example.com'}
        provider.return_value.cache.serialize.return_value = '{"refresh":"private-refresh"}'
        outlook.finish_oauth(db, 'code', flow['state'], settings, owner.id)
        connection = db.scalar(select(OutlookConnection))
        assert connection.email_address == 'me@example.com' and 'private-refresh' not in connection.encrypted_credentials
        assert 'private-refresh' in outlook.cipher(settings).decrypt(connection.encrypted_credentials.encode()).decode()
        with pytest.raises(HTTPException):
            outlook.finish_oauth(db, 'code', flow['state'], settings, owner.id)
        assert client.acquire_token_by_auth_code_flow.call_count == 1


def test_oauth_errors_redacted(db, account_factory, settings):
    user = account_factory()
    record, flow = begin(db, user, settings)
    with patch.object(outlook, 'oauth_client') as client:
        client.return_value.acquire_token_by_auth_code_flow.side_effect = RuntimeError('private-secret')
        with pytest.raises(HTTPException) as err:
            outlook.finish_oauth(db, 'code', flow['state'], settings, user.id)
        assert err.value.status_code == 502 and 'private-secret' not in err.value.detail


def raw_message():
    message = MimeMessage()
    message['From'], message['Subject'] = 'sender@example.com', 'Real enquiry'
    message['Reply-To'], message['Message-ID'] = 'reply@example.com', '<original@example.com>'
    message.set_content('Please check my invoice.')
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode(), 'threadId': 'conversation'}


def test_sync_keeps_gmail_and_outlook_connections_and_ids_separate(db, account_factory, settings):
    user = account_factory()
    db.add(GmailConnection(user_id=user.id, email_address='gmail@example.com', encrypted_credentials='existing'))
    db.add(OutlookConnection(user_id=user.id, email_address='outlook@example.com', encrypted_credentials='existing'))
    db.commit()
    provider = Mock()
    provider.list_messages.return_value = [{'id': 'same-id'}]
    provider.get_raw.return_value = raw_message()
    assert outlook.sync_mailbox(db, actor(user), settings, provider)['imported'] == 1
    assert outlook.sync_mailbox(db, actor(user), settings, provider)['imported'] == 0
    from app.services.gmail_service import sync_mailbox as gmail_sync
    assert gmail_sync(db, actor(user), settings, provider)['imported'] == 1
    emails = db.scalars(select(EmailMessage)).all()
    assert len(emails) == 2 and len({e.fingerprint for e in emails}) == 2
    assert all(e.owner_user_id == user.id for e in emails)
    assert any(e.outlook_message_id and not e.gmail_message_id for e in emails)
    assert db.scalar(select(GmailConnection)).encrypted_credentials == 'existing'


@pytest.fixture
def approved(db, account_factory):
    user = account_factory()
    email = EmailMessage(sender='sender@example.com', reply_to='reply@example.com', subject='Query', body='Private',
        fingerprint='private', owner_user_id=user.id, outlook_message_id='outlook-id', original_message_id='<original@example.com>')
    db.add(email)
    db.flush()
    draft = ReplyDraft(email_id=email.id, body='Reviewed reply', status='approved', revision=3)
    db.add(draft)
    db.commit()
    return draft, actor(user)


def live(settings):
    return settings.model_copy(update={'llm_provider': 'openai', 'outlook_send_enabled': True})


def test_send_accepted_is_not_delivered_and_cannot_repeat(db, approved, settings):
    draft, user = approved
    provider = Mock()
    provider.send.return_value = 202
    request = SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND')
    outlook.send_approved_draft(db, draft, user, request, live(settings), provider)
    assert draft.delivery_status == 'accepted' and not draft.gmail_sent_id
    mime = base64.b64decode(provider.send.call_args.args[0]).decode()
    assert 'To: reply@example.com' in mime and 'In-Reply-To: <original@example.com>' in mime and 'Reviewed reply' in mime
    outlook.send_approved_draft(db, draft, user, request, live(settings), provider)
    assert provider.send.call_count == 1


@pytest.mark.parametrize('case', ['stale', 'recipient', 'owner', 'unapproved', 'disabled', 'demo'])
def test_send_guards(db, approved, settings, case):
    draft, user = approved
    provider = Mock()
    cfg, revision, recipient = live(settings), 3, 'reply@example.com'
    if case == 'stale': revision = 2
    if case == 'recipient': recipient = 'wrong@example.com'
    if case == 'owner': user = Principal('other', 'admin', user.user_id + 1)
    if case == 'unapproved': draft.status = 'pending'
    if case == 'disabled': cfg.outlook_send_enabled = False
    if case == 'demo': cfg.llm_provider = 'demo'
    with pytest.raises(HTTPException):
        outlook.send_approved_draft(db, draft, user, SendRequest(revision=revision, recipient=recipient, confirmation='SEND'), cfg, provider)
    assert not provider.send.called


def test_unknown_send_locks_retry_and_edit(db, approved, settings, client):
    draft, user = approved
    provider = Mock()
    provider.send.side_effect = TimeoutError('private-token')
    request = SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND')
    for _ in range(2):
        with pytest.raises(HTTPException) as err:
            outlook.send_approved_draft(db, draft, user, request, live(settings), provider)
        assert 'private-token' not in err.value.detail
    assert draft.delivery_status == 'unknown' and provider.send.call_count == 1
    headers = login(client, 'owner')
    assert client.patch(f'/drafts/{draft.id}', headers=headers, json={'body': 'changed', 'revision': 3}).status_code == 409


def login(client, username):
    response = client.post('/auth/login', json={'username': username, 'password': 'correct-test-password-123'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_private_api_and_roles(client, db, approved, account_factory):
    draft, user = approved
    account_factory('other', 'admin')
    account_factory('viewer', 'viewer')
    own = login(client, 'owner')
    for headers in [login(client, 'other'), {'Authorization': 'Bearer test-token'}]:
        assert client.get('/emails', headers=headers).json() == []
        assert client.get(f'/emails/{draft.email_id}', headers=headers).status_code == 404
        assert client.get(f'/emails/{draft.email_id}/results', headers=headers).status_code == 404
        assert client.post(f'/drafts/{draft.id}/send', headers=headers).status_code == 404
    assert client.get(f'/emails/{draft.email_id}', headers=own).json()['source'] == 'outlook'
    for headers in [login(client, 'viewer'), {'Authorization': 'Bearer test-token'}]:
        for endpoint in ['connect', 'callback', 'sync']:
            assert client.post('/outlook/' + endpoint, headers=headers, json={'code': 'c', 'state': 's'}).status_code == 403


def test_disconnect_only_own_outlook_and_preserves_gmail(client, db, account_factory):
    owner, other = account_factory(), account_factory('other')
    db.add_all([OutlookConnection(user_id=u.id, email_address=u.username+'@example.com', encrypted_credentials='secret') for u in [owner, other]])
    db.add(GmailConnection(user_id=owner.id, email_address='gmail@example.com', encrypted_credentials='secret'))
    db.commit()
    assert client.post('/outlook/disconnect', headers=login(client, 'owner')).status_code == 204
    assert db.scalar(select(OutlookConnection)).user_id == other.id
    assert db.scalar(select(GmailConnection)).user_id == owner.id


def test_graph_provider_immutable_ids_and_no_send_retry():
    provider = outlook.OutlookProvider('private-token', Mock())
    with patch.object(outlook.requests, 'get') as get:
        get.return_value.json.return_value = {'value': [{'id': 'id'}]}
        assert provider.list_messages() == [{'id': 'id'}]
        assert get.call_args.kwargs['headers']['Prefer'] == 'IdType="ImmutableId"'
        assert get.call_args.kwargs['params']['$top'] == 20
    with patch.object(outlook.requests, 'post') as post:
        post.return_value.status_code = 202
        assert provider.send('mime') == 202 and post.call_count == 1
        assert post.call_args.kwargs['headers']['Content-Type'] == 'text/plain'
        assert post.call_args.kwargs['allow_redirects'] is False


def test_reconnect_wrong_mailbox_blocked(db, approved, settings):
    draft, user = approved
    connection = OutlookConnection(user_id=user.user_id, email_address='different@example.com', encrypted_credentials='')
    provider = Mock()
    with patch.object(outlook, 'connected_provider', return_value=(connection, provider)):
        with pytest.raises(HTTPException) as err:
            outlook.send_approved_draft(db, draft, user, SendRequest(revision=3, recipient='reply@example.com', confirmation='SEND'), live(settings))
        assert err.value.status_code == 409 and not provider.send.called


def test_refresh_uses_only_saved_account_and_fails_closed(db, account_factory, settings):
    user = account_factory()
    connection = OutlookConnection(user_id=user.id, email_address='me@example.com',
        encrypted_credentials=outlook.cipher(settings).encrypt(b'{}').decode())
    db.add(connection)
    db.commit()
    client = Mock()
    client.get_accounts.return_value = [{'home_account_id': 'saved-account'}]
    client.acquire_token_silent.return_value = {'access_token': 'new-private-token'}
    with patch.object(outlook, 'oauth_client', return_value=client):
        actual, provider = outlook.connected_provider(db, user.id, settings)
        assert actual.id == connection.id
        assert provider.headers['Authorization'] == 'Bearer new-private-token'
        assert client.acquire_token_silent.call_args.kwargs['account']['home_account_id'] == 'saved-account'
        assert 'new-private-token' not in connection.encrypted_credentials
        client.acquire_token_silent.return_value = {'error': 'consent_required', 'error_description': 'private-data'}
        with pytest.raises(HTTPException) as err:
            outlook.connected_provider(db, user.id, settings)
        assert err.value.status_code == 409 and 'private-data' not in err.value.detail


def test_graph_mime_is_bounded_and_message_id_is_url_encoded():
    provider = outlook.OutlookProvider('private-token', Mock())
    with patch.object(outlook.requests, 'get') as get:
        response = get.return_value.__enter__.return_value
        response.iter_content.return_value = [b'x' * 2_000_001]
        with pytest.raises(ValueError):
            provider.get_raw('a/b?c')
        assert '/a%2Fb%3Fc/$value' in get.call_args.args[0]
        assert get.call_args.kwargs['stream'] is True


def test_outlook_api_send_dispatches_to_correct_provider(client, approved, monkeypatch):
    draft, user = approved
    monkeypatch.setenv('OUTLOOK_SEND_ENABLED', 'true')
    get_settings.cache_clear()
    with patch.object(outlook, 'send_approved_draft') as send, patch('app.services.gmail_service.send_approved_draft') as gmail_send:
        result = client.post(f'/drafts/{draft.id}/send', headers=login(client, 'owner'),
            json={'revision': 3, 'recipient': 'reply@example.com', 'confirmation': 'SEND'})
        assert result.status_code == 200 and send.call_count == 1 and not gmail_send.called
