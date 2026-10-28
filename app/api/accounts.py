import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, func, update, delete, text
from sqlalchemy.exc import IntegrityError
from app.db.session import get_db
from app.models import UserAccount, AuthSession, LoginAttempt, SecurityAudit, utcnow
from app.core.security import (hash_password, verify_password, token_hash, current_principal,
                               require_admin, audit)
from app.schemas.accounts import (Login, AccountCreate, AccountUpdate, PasswordReset,
    PasswordChange, AccountResponse, SessionResponse)

router = APIRouter(tags=['Accounts'])
DUMMY_HASH = hash_password('invalid-account-password-never-accepted')


def public_user(user):
    return {k: getattr(user, k) for k in ('id', 'username', 'display_name', 'role', 'active', 'created_at')}


def revoke_sessions(db, user_id):
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id).values(revoked=True))


@router.post('/auth/login', response_model=SessionResponse)
def login(payload: Login, db=Depends(get_db)):
    if db.bind.dialect.name == 'postgresql':
        # Serialize counter checks across API workers; never trust caller-supplied IP headers.
        db.execute(text('SELECT pg_advisory_xact_lock(48105002)'))
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < utcnow() - timedelta(days=1)))
    cutoff = utcnow() - timedelta(seconds=60)
    identity = token_hash(payload.username)
    failures = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.created_at >= cutoff,
        LoginAttempt.identity_hash == identity))
    total = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.created_at >= cutoff))
    if failures >= 10 or total >= 100:
        raise HTTPException(429, 'Too many sign-in attempts. Wait one minute and try again.', headers={'Retry-After': '60'})
    user = db.scalar(select(UserAccount).where(UserAccount.username == payload.username))
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not user or not user.active or not valid:
        db.add(LoginAttempt(identity_hash=identity))
        db.commit()
        raise HTTPException(401, 'Username or password is incorrect')
    token, expires = secrets.token_urlsafe(32), utcnow() + timedelta(hours=1)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash(token), expires_at=expires))
    audit(db, user.username, 'sign_in', user.id)
    db.commit()
    return dict(access_token=token, token_type='bearer', expires_at=expires, user=public_user(user))


@router.get('/auth/me', response_model=AccountResponse)
def me(actor=Depends(current_principal), db=Depends(get_db)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with a user account')
    return public_user(db.get(UserAccount, actor.user_id))


@router.post('/auth/logout', status_code=204)
def logout(actor=Depends(current_principal), db=Depends(get_db)):
    if actor.session_id:
        db.get(AuthSession, actor.session_id).revoked = True
        audit(db, actor, 'sign_out', actor.user_id)
        db.commit()
    return Response(status_code=204)


@router.post('/auth/password', status_code=204)
def change_password(payload: PasswordChange, actor=Depends(current_principal), db=Depends(get_db)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with a user account')
    user = db.get(UserAccount, actor.user_id)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, 'Current password is incorrect')
    user.password_hash = hash_password(payload.new_password)
    revoke_sessions(db, user.id)
    audit(db, actor, 'password_changed', user.id)
    db.commit()
    return Response(status_code=204)


@router.get('/users', response_model=list[AccountResponse])
def users(actor=Depends(require_admin), db=Depends(get_db)):
    return [public_user(user) for user in db.scalars(select(UserAccount).order_by(UserAccount.id)).all()]


@router.post('/users', response_model=AccountResponse, status_code=201)
def create_user(payload: AccountCreate, actor=Depends(require_admin), db=Depends(get_db)):
    user = UserAccount(username=payload.username, display_name=payload.display_name,
                       password_hash=hash_password(payload.password), role=payload.role, active=True)
    db.add(user)
    try:
        db.flush()
        audit(db, actor, 'user_created', user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username already exists')
    return public_user(user)


@router.patch('/users/{user_id}', response_model=AccountResponse)
def update_user(user_id: int, payload: AccountUpdate, actor=Depends(require_admin), db=Depends(get_db)):
    # Lock active administrators in deterministic order so two admins cannot remove each other concurrently.
    admins = db.scalars(select(UserAccount).where(UserAccount.role == 'admin', UserAccount.active.is_(True))
                        .order_by(UserAccount.id).with_for_update()).all()
    user = db.get(UserAccount, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    role = payload.role if payload.role is not None else user.role
    active = payload.active if payload.active is not None else user.active
    if user.role == 'admin' and user.active and (role != 'admin' or not active) and len(admins) <= 1:
        raise HTTPException(409, 'At least one active administrator must remain')
    user.role, user.active = role, active
    revoke_sessions(db, user.id)
    audit(db, actor, 'user_updated', user.id)
    db.commit()
    return public_user(user)


@router.post('/users/{user_id}/reset-password', status_code=204)
def reset_password(user_id: int, payload: PasswordReset, actor=Depends(require_admin), db=Depends(get_db)):
    user = db.get(UserAccount, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    user.password_hash = hash_password(payload.new_password)
    revoke_sessions(db, user.id)
    audit(db, actor, 'password_reset', user.id)
    db.commit()
    return Response(status_code=204)


@router.get('/users/audit/events')
def events(actor=Depends(require_admin), db=Depends(get_db)):
    rows = db.scalars(select(SecurityAudit).order_by(SecurityAudit.id.desc()).limit(100)).all()
    return [dict(id=row.id, actor=row.actor, action=row.action, target=row.target, created_at=row.created_at) for row in rows]
