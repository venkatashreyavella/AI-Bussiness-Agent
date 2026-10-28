from datetime import timedelta
from sqlalchemy import select, func
from app.core.config import get_settings
from app.core.security import token_hash, verify_password
from app.models import UserAccount, LoginAttempt, SecurityAudit, utcnow

PASSWORD = 'self-registration-password-123'


def payload(username='new.person', **extra):
    return {'username': username, 'password': PASSWORD, 'display_name': 'New Person', **extra}


def test_public_registration_grants_reviewer_and_session(client, db, account_factory):
    account_factory()
    response = client.post('/auth/register', json=payload(), headers={'Authorization': ''})
    assert response.status_code == 201
    data = response.json()
    assert data['user']['username'] == 'new.person' and data['user']['role'] == 'reviewer'
    auth = {'Authorization': 'Bearer ' + data['access_token']}
    assert client.get('/auth/me', headers=auth).status_code == 200
    assert client.get('/emails', headers=auth).status_code == 200
    assert client.get('/users', headers=auth).status_code == 403
    assert client.get('/users/audit/events', headers=auth).status_code == 403
    user = db.scalar(select(UserAccount).where(UserAccount.username == 'new.person'))
    assert verify_password(PASSWORD, user.password_hash) and user.password_hash != PASSWORD
    assert db.scalar(select(SecurityAudit).where(SecurityAudit.action == 'user_registered')).actor == 'new.person'


def test_registered_reviewer_can_process_and_approve(client, account_factory, payload):
    account_factory()
    response = client.post('/auth/register', json={'username': 'new.reviewer', 'password': PASSWORD})
    auth = {'Authorization': 'Bearer ' + response.json()['access_token']}
    ident = client.post('/emails', json=payload, headers=auth).json()['id']
    draft = client.post(f'/emails/{ident}/process', headers=auth).json()['draft']
    result = client.post(f"/drafts/{draft['id']}/approve", headers=auth, json={'revision': draft['revision'], 'reviewer': 'owner'})
    assert result.status_code == 200 and result.json()['reviewed_by'] == 'new.reviewer'


def test_cannot_choose_admin_or_modify_existing_user(client, db, account_factory):
    owner = account_factory()
    original_hash = owner.password_hash
    for extra in [{'role': 'admin'}, {'active': True}, {'id': owner.id}, {'password_hash': 'fake'}]:
        assert client.post('/auth/register', json=payload(**extra)).status_code == 422
    assert client.post('/auth/register', json=payload('OWNER')).status_code == 409
    db.refresh(owner)
    assert owner.password_hash == original_hash and owner.role == 'admin'


def test_duplicate_and_invalid_registration(client, db, account_factory):
    account_factory()
    assert client.post('/auth/register', json=payload()).status_code == 201
    assert client.post('/auth/register', json=payload('NEW.PERSON')).status_code == 409
    for invalid in [payload('a'), payload('bad username'), payload(password='short')]:
        assert client.post('/auth/register', json=invalid).status_code == 422
    assert db.scalar(select(func.count()).select_from(UserAccount)) == 2


def test_registration_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_SIGNUP_ENABLED', 'false')
    get_settings.cache_clear()
    assert client.get('/auth/registration', headers={'Authorization': ''}).json()['enabled'] is False
    assert client.post('/auth/register', json=payload()).status_code == 403


def test_no_registration_before_owner_bootstrap(client):
    assert client.post('/auth/register', json=payload()).status_code == 503


def test_registration_throttle_counts_duplicate_attempts(client, db, account_factory):
    account_factory()
    for _ in range(10):
        assert client.post('/auth/register', json=payload('owner')).status_code == 409
    response = client.post('/auth/register', json=payload())
    assert response.status_code == 429 and response.headers['Retry-After'] == '60'
    attempts = db.scalars(select(LoginAttempt).where(LoginAttempt.identity_hash == token_hash('public_registration_attempt'))).all()
    for attempt in attempts:
        attempt.created_at = utcnow() - timedelta(minutes=2)
    db.commit()
    assert client.post('/auth/register', json=payload()).status_code == 201
