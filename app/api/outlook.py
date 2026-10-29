from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from app.core.config import get_settings
from app.core.security import require_writer, current_principal, audit
from app.db.session import get_db
from app.models import OutlookConnection
from app.schemas.gmail import OAuthCallback
from app.services.outlook_service import begin_oauth, finish_oauth, sync_mailbox, missing_config

router = APIRouter(prefix='/outlook', tags=['Outlook'])


def human_user(actor=Depends(current_principal)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with your own account to manage Outlook')
    return actor


def mailbox_user(actor=Depends(require_writer)):
    if actor.user_id is None:
        raise HTTPException(403, 'Sign in with your own account to connect Outlook')
    return actor


@router.get('/status')
def status(actor=Depends(current_principal), db=Depends(get_db)):
    settings = get_settings()
    connection = db.scalar(select(OutlookConnection).where(OutlookConnection.user_id == actor.user_id)) if actor.user_id else None
    return {'configured': not missing_config(settings), 'missing_settings': [v.upper() for v in missing_config(settings)],
            'connected': bool(connection), 'email_address': connection.email_address if connection else None,
            'last_synced_at': connection.last_synced_at if connection else None,
            'live_ai_enabled': settings.llm_provider == 'openai',
            'sending_enabled': settings.outlook_send_enabled and settings.llm_provider == 'openai'}


@router.post('/connect')
def connect(actor=Depends(mailbox_user), db=Depends(get_db)):
    return {'authorization_url': begin_oauth(db, actor, get_settings())}


@router.post('/callback')
def callback(payload: OAuthCallback, actor=Depends(mailbox_user), db=Depends(get_db)):
    # Require the initiating application identity again; state alone cannot link accounts.
    finish_oauth(db, payload.code, payload.state, get_settings(), actor.user_id)
    return {'connected': True}


@router.post('/sync')
def sync(actor=Depends(mailbox_user), db=Depends(get_db)):
    return sync_mailbox(db, actor, get_settings())


@router.post('/disconnect', status_code=204)
def disconnect(actor=Depends(human_user), db=Depends(get_db)):
    connection = db.scalar(select(OutlookConnection).where(OutlookConnection.user_id == actor.user_id))
    if connection is None:
        return Response(status_code=204)
    db.delete(connection)
    audit(db, actor, 'outlook_disconnected', actor.user_id)
    db.commit()
    return Response(status_code=204)
