import json
import requests
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from app.core.config import get_settings
from app.core.security import require_writer, current_principal, audit
from app.db.session import get_db
from app.models import GmailConnection
from app.schemas.gmail import OAuthCallback
from app.services.gmail_service import begin_oauth, finish_oauth, sync_mailbox, missing_config, cipher

router = APIRouter(prefix='/gmail', tags=['Gmail'])


def human_user(actor=Depends(current_principal)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with your own account to manage Gmail')
    return actor


def mailbox_user(actor=Depends(require_writer)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with your own account to connect Gmail')
    return actor


@router.get('/status')
def status(actor=Depends(current_principal), db=Depends(get_db)):
    settings = get_settings()
    connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == actor.user_id)) if actor.user_id else None
    return {'configured': not missing_config(settings), 'missing_settings': [v.upper() for v in missing_config(settings)],
            'connected': bool(connection), 'email_address': connection.email_address if connection else None,
            'last_synced_at': connection.last_synced_at if connection else None,
            'live_ai_enabled': settings.llm_provider == 'openai',
            'sending_enabled': settings.gmail_send_enabled and settings.llm_provider == 'openai'}


@router.post('/connect')
def connect(actor=Depends(mailbox_user), db=Depends(get_db)):
    return {'authorization_url': begin_oauth(db, actor, get_settings())}


@router.post('/callback')
def callback(payload: OAuthCallback, actor=Depends(mailbox_user), db=Depends(get_db)):
    # Require the initiating application identity again after Google's redirect; state alone cannot link accounts.
    finish_oauth(db, payload.code, payload.state, get_settings(), actor.user_id)
    return {'connected': True}


@router.post('/sync')
def sync(actor=Depends(mailbox_user), db=Depends(get_db)):
    return sync_mailbox(db, actor, get_settings())


@router.post('/disconnect', status_code=204)
def disconnect(actor=Depends(human_user), db=Depends(get_db)):
    connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == actor.user_id))
    if connection is None:
        return Response(status_code=204)
    try:
        data = json.loads(cipher(get_settings()).decrypt(connection.encrypted_credentials.encode()))
        response = requests.post('https://oauth2.googleapis.com/revoke',
            data={'token': data.get('refresh_token') or data.get('token')}, timeout=20)
        if response.status_code not in {200, 400}:
            raise ValueError('Revocation failed')
    except Exception:
        raise HTTPException(502, 'Could not revoke Gmail access. Retry, or revoke the app in your Google account settings.')
    db.delete(connection)
    audit(db, actor, 'gmail_disconnected', actor.user_id)
    db.commit()
    return Response(status_code=204)
