"""Database-backed identities, opaque revocable sessions and API-side authorization."""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import get_db
from app.models import UserAccount, AuthSession, SecurityAudit, utcnow

bearer = HTTPBearer(auto_error=False)
ITERATIONS = 600_000


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    user_id: int | None = None
    session_id: int | None = None


def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    if not credentials:
        raise HTTPException(401, 'Sign in required')
    token = credentials.credentials
    service_token = get_settings().app_api_token
    # Compatibility for private CLI integrations; never used by the browser dashboard.
    if service_token and secrets.compare_digest(token.encode(), service_token.encode()):
        return Principal(username='service', role='admin')
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token), AuthSession.revoked.is_(False)))
    if session is None or aware(session.expires_at) <= utcnow():
        raise HTTPException(401, 'Session expired or invalid; sign in again')
    user = db.get(UserAccount, session.user_id)
    if user is None or not user.active:
        raise HTTPException(401, 'Session expired or invalid; sign in again')
    return Principal(username=user.username, role=user.role, user_id=user.id, session_id=session.id)


def require_writer(actor: Principal = Depends(current_principal)):
    if actor.role not in {'admin', 'reviewer'}:
        raise HTTPException(403, 'Reviewer or admin permission required')
    return actor


def require_admin(actor: Principal = Depends(current_principal)):
    if actor.role != 'admin' or actor.user_id is None:
        raise HTTPException(403, 'An administrator account is required')
    return actor


def audit(db, actor, action, target):
    db.add(SecurityAudit(actor=actor.username if isinstance(actor, Principal) else actor,
                         action=action, target=str(target)))
