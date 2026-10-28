from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core.security import hash_password, verify_password, token_hash
from app.models import AuthSession, LoginAttempt, SecurityAudit, UserAccount, utcnow

PASSWORD = 'correct-test-password-123'


def headers(client, username='owner', password=PASSWORD):
    response = client.post('/auth/login', json=dict(username=username, password=password))
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_password_hashing():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password('wrong', first)
    assert not verify_password(PASSWORD, 'corrupt')


def test_login_sessions_and_logout(client, db, account_factory):
    account_factory()
    auth = headers(client, username='OWNER')
    me = client.get('/auth/me', headers=auth)
    assert me.status_code == 200 and me.json()['username'] == 'owner'
    assert 'password_hash' not in me.json()
    token = auth['Authorization'].split(' ', 1)[1]
    session = db.scalar(select(AuthSession))
    assert session.token_hash == token_hash(token) and session.token_hash != token
    assert client.post('/auth/logout', headers=auth).status_code == 204
    assert client.get('/emails', headers=auth).status_code == 401


def test_expired_sessions(client, db, account_factory):
    account_factory()
    auth = headers(client)
    db.scalar(select(AuthSession)).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get('/auth/me', headers=auth).status_code == 401


@pytest.mark.parametrize('role', ['viewer', 'reviewer'])
def test_admin_routes_deny_other_roles(client, account_factory, role):
    account_factory(username='person', role=role)
    auth = headers(client, 'person')
    assert client.get('/users', headers=auth).status_code == 403
    assert client.post('/users', headers=auth, json=dict(username='hacker', display_name='Hacker', password=PASSWORD, role='admin')).status_code == 403
    assert client.patch('/users/1', headers=auth, json={'role': 'admin'}).status_code == 403
    assert client.get('/users/audit/events', headers=auth).status_code == 403
    assert client.post('/users/1/reset-password', headers=auth, json={'new_password': PASSWORD}).status_code == 403


def test_viewer_cannot_mutate_even_by_direct_api(client, account_factory, payload):
    ident = client.post('/emails', json=payload).json()['id']
    draft = client.post(f'/emails/{ident}/process').json()['draft']
    account_factory(username='reader', role='viewer')
    auth = headers(client, 'reader')
    assert client.get('/emails', headers=auth).status_code == 200
    assert client.get(f'/emails/{ident}/results', headers=auth).status_code == 200
    assert client.get('/analytics', headers=auth).status_code == 200
    assert client.post('/emails', headers=auth, json=payload).status_code == 403
    assert client.post('/emails/import', headers=auth, files={'file': ('example.eml', b'x')}).status_code == 403
    assert client.post(f'/emails/{ident}/process', headers=auth).status_code == 403
    assert client.patch(f"/drafts/{draft['id']}", headers=auth, json={'body': 'forged', 'revision': 1}).status_code == 403
    for action in ['approve', 'reject']:
        assert client.post(f"/drafts/{draft['id']}/{action}", headers=auth, json={'revision': 1, 'reviewer': 'owner'}).status_code == 403


def test_review_identity_cannot_be_forged(client, db, account_factory, payload):
    account_factory(username='reviewer', role='reviewer')
    auth = headers(client, 'reviewer')
    ident = client.post('/emails', headers=auth, json=payload).json()['id']
    draft = client.post(f'/emails/{ident}/process', headers=auth).json()['draft']
    response = client.post(f"/drafts/{draft['id']}/approve", headers=auth, json={'revision': 1, 'reviewer': 'someone-else'})
    assert response.status_code == 200 and response.json()['reviewed_by'] == 'reviewer'
    event = db.scalar(select(SecurityAudit).where(SecurityAudit.action == 'draft_approved'))
    assert event.actor == 'reviewer'


def test_account_lifecycle_and_session_revocation(client, db, account_factory):
    account_factory()
    admin = headers(client)
    created = client.post('/users', headers=admin, json=dict(username='colleague', display_name='Colleague', password=PASSWORD, role='reviewer'))
    assert created.status_code == 201
    ident = created.json()['id']
    assert 'password' not in created.text and 'hash' not in created.text
    colleague = headers(client, 'colleague')
    assert client.patch(f'/users/{ident}', headers=admin, json={'role': 'viewer'}).status_code == 200
    assert client.get('/auth/me', headers=colleague).status_code == 401
    colleague = headers(client, 'colleague')
    assert client.get('/auth/me', headers=colleague).json()['role'] == 'viewer'
    assert client.patch(f'/users/{ident}', headers=admin, json={'active': False}).status_code == 200
    assert client.get('/auth/me', headers=colleague).status_code == 401
    assert client.post('/auth/login', json=dict(username='colleague', password=PASSWORD)).status_code == 401
    assert client.patch(f'/users/{ident}', headers=admin, json={'active': True}).status_code == 200
    replacement = 'replacement-test-password-123'
    assert client.post(f'/users/{ident}/reset-password', headers=admin, json={'new_password': replacement}).status_code == 204
    assert client.post('/auth/login', json=dict(username='colleague', password=PASSWORD)).status_code == 401
    assert client.get('/auth/me', headers=headers(client, 'colleague', replacement)).status_code == 200
    assert any(e['action'] == 'password_reset' for e in client.get('/users/audit/events', headers=admin).json())


def test_self_password_change_revokes_all_sessions(client, account_factory):
    account_factory()
    first, second = headers(client), headers(client)
    new = 'changed-password-123456789'
    assert client.post('/auth/password', headers=first, json={'current_password': 'wrong', 'new_password': new}).status_code == 400
    assert client.post('/auth/password', headers=first, json={'current_password': PASSWORD, 'new_password': new}).status_code == 204
    assert client.get('/auth/me', headers=first).status_code == 401
    assert client.get('/auth/me', headers=second).status_code == 401
    assert client.post('/auth/login', json=dict(username='owner', password=PASSWORD)).status_code == 401
    assert client.get('/auth/me', headers=headers(client, password=new)).status_code == 200


def test_last_admin_protection(client, account_factory):
    owner = account_factory()
    auth = headers(client)
    for change in [{'role': 'viewer'}, {'active': False}, {'role': 'reviewer', 'active': False}]:
        assert client.patch(f'/users/{owner.id}', headers=auth, json=change).status_code == 409
    assert client.get('/auth/me', headers=auth).json()['role'] == 'admin'


def test_login_throttle_is_database_backed(client, db, account_factory):
    account_factory()
    for _ in range(10):
        assert client.post('/auth/login', json={'username': 'owner', 'password': 'wrong'}).status_code == 401
    response = client.post('/auth/login', json={'username': 'owner', 'password': PASSWORD})
    assert response.status_code == 429 and response.headers['Retry-After'] == '60'
    for attempt in db.scalars(select(LoginAttempt)).all():
        attempt.created_at = utcnow() - timedelta(minutes=2)
    db.commit()
    assert client.post('/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 200


def test_validation_and_no_shared_password_backdoor(client, account_factory):
    account_factory()
    assert client.get('/emails', headers={'Authorization': 'Bearer ' + PASSWORD}).status_code == 401
    assert client.get('/users').status_code == 403  # private service key is not a human administrator
    admin = headers(client)
    for data in [dict(username='a', role='viewer', password=PASSWORD), dict(username='other', role='root', password=PASSWORD),
                 dict(username='other', role='viewer', password='short')]:
        assert client.post('/users', headers=admin, json={**data, 'display_name': 'Other'}).status_code == 422
    assert client.post('/users', headers=admin, json=dict(username='owner', display_name='Duplicate', role='viewer', password=PASSWORD)).status_code == 409


def test_bootstrap_does_not_reset_accounts(db, monkeypatch):
    from scripts.bootstrap_admin import bootstrap
    monkeypatch.setenv('DASHBOARD_PASSWORD', PASSWORD)
    bootstrap(db)
    user = db.scalar(select(UserAccount))
    first_hash = user.password_hash
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'different-bootstrap-password')
    bootstrap(db)
    assert user.username == 'owner' and user.password_hash == first_hash
    assert verify_password(PASSWORD, user.password_hash)
