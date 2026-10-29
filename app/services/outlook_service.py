"""Microsoft Graph delegated Outlook mail, encrypted MSAL cache and reviewed delivery."""
import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from email.message import EmailMessage as MimeMessage
from email.utils import make_msgid
from urllib.parse import urlparse, quote
import msal
import requests
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models import EmailMessage, ReplyDraft, OutlookConnection, OutlookOAuthState, UserAccount, utcnow
from app.core.security import token_hash, aware, audit
from app.schemas import EmailCreate
from app.services.gmail_service import cipher, parse_gmail

SCOPES = ['User.Read', 'Mail.Read', 'Mail.Send']
GRAPH = 'https://graph.microsoft.com/v1.0'


def missing_config(settings):
    return [name for name in ['microsoft_client_id', 'microsoft_client_secret', 'token_encryption_key'] if not getattr(settings, name)]


def oauth_client(settings, cache=None):
    if missing_config(settings):
        raise HTTPException(503, 'Configure Microsoft OAuth and token encryption first')
    if not re.fullmatch(r'(common|organizations|consumers|[0-9a-fA-F-]{36})', settings.microsoft_tenant):
        raise HTTPException(503, 'Microsoft tenant must be common, organizations, consumers or a tenant UUID')
    uri = urlparse(settings.microsoft_redirect_uri)
    if uri.scheme != 'https' and not (uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1'}):
        raise HTTPException(503, 'Microsoft redirect URI must use HTTPS, or localhost for development')
    return msal.ConfidentialClientApplication(settings.microsoft_client_id,
        client_credential=settings.microsoft_client_secret,
        authority='https://login.microsoftonline.com/' + settings.microsoft_tenant,
        token_cache=cache, timeout=20)


def begin_oauth(db, actor, settings):
    # Provider prefix routes the shared dashboard callback; identity is verified server-side.
    state = 'outlook:' + secrets.token_urlsafe(40)
    try:
        flow = oauth_client(settings).initiate_auth_code_flow(SCOPES, state=state,
            redirect_uri=settings.microsoft_redirect_uri, prompt='select_account')
        url = flow['auth_uri']
        db.add(OutlookOAuthState(user_id=actor.user_id, state_hash=token_hash(state),
            encrypted_flow=cipher(settings).encrypt(json.dumps(flow).encode()).decode(),
            expires_at=utcnow() + timedelta(minutes=10)))
        db.commit()
        return url
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Could not start Microsoft sign-in. Check OAuth settings.')


def save_credentials(connection, provider, settings):
    connection.encrypted_credentials = cipher(settings).encrypt(provider.cache.serialize().encode()).decode()


def finish_oauth(db, code, state, settings, user_id):
    record = db.scalar(select(OutlookOAuthState).where(OutlookOAuthState.state_hash == token_hash(state)))
    if record is None or record.used or aware(record.expires_at) <= utcnow():
        raise HTTPException(400, 'Outlook connection link expired or was already used. Start again.')
    if record.user_id != user_id:
        raise HTTPException(400, 'Sign in with the same application account that started this Outlook connection')
    user = db.get(UserAccount, user_id)
    if not user or not user.active or user.role not in {'admin', 'reviewer'}:
        raise HTTPException(403, 'This account cannot connect Outlook')
    claimed = db.execute(update(OutlookOAuthState).where(OutlookOAuthState.id == record.id,
        OutlookOAuthState.used.is_(False)).values(used=True))
    if claimed.rowcount != 1:
        raise HTTPException(400, 'Outlook connection link was already used')
    db.commit()
    try:
        flow = json.loads(cipher(settings).decrypt(record.encrypted_flow.encode()))
        cache = msal.SerializableTokenCache()
        result = oauth_client(settings, cache).acquire_token_by_auth_code_flow(flow, {'code': code, 'state': state})
        scopes = {s.lower().split('/')[-1] for s in result.get('scope', '').split()}
        if not result.get('access_token') or not {s.lower() for s in SCOPES}.issubset(scopes):
            raise ValueError('Required Microsoft permissions were not granted')
        provider = OutlookProvider(result['access_token'], cache)
        profile = provider.profile()
        address = str(EmailCreate(sender=profile.get('mail') or profile.get('userPrincipalName'), subject='validation', body='validation').sender)
        connection = db.scalar(select(OutlookConnection).where(OutlookConnection.user_id == user.id))
        if not connection:
            connection = OutlookConnection(user_id=user.id, email_address=address, encrypted_credentials='')
            db.add(connection)
        connection.email_address = address
        save_credentials(connection, provider, settings)
        audit(db, user.username, 'outlook_connected', user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Microsoft connection failed. Check consent, account support and OAuth settings, then start again.')


class OutlookProvider:
    def __init__(self, token, cache):
        self.cache = cache
        self.headers = {'Authorization': 'Bearer ' + token, 'Prefer': 'IdType="ImmutableId"'}

    def profile(self):
        response = requests.get(GRAPH + '/me', headers=self.headers,
            params={'$select': 'mail,userPrincipalName'}, timeout=20, allow_redirects=False)
        response.raise_for_status()
        return response.json()

    def list_messages(self, limit=20):
        response = requests.get(GRAPH + '/me/mailFolders/inbox/messages', headers=self.headers,
            params={'$top': limit, '$select': 'id', '$orderby': 'receivedDateTime desc'}, timeout=20, allow_redirects=False)
        response.raise_for_status()
        return response.json().get('value', [])

    def get_raw(self, ident):
        with requests.get(GRAPH + '/me/messages/' + quote(ident, safe='') + '/$value',
                headers=self.headers, timeout=20, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError('Email exceeds import limit')
                chunks.append(chunk)
        raw = b''.join(chunks)
        # Reuse the bounded MIME parser; provider message ID isolates the thread when no header exists.
        from email import policy
        from email.parser import BytesParser
        message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        thread = (str(message.get('References') or message.get('In-Reply-To') or message.get('Message-ID') or '').strip() or ident).split()[0]
        return {'raw': base64.urlsafe_b64encode(raw).decode(), 'threadId': token_hash(thread)}

    def send(self, mime):
        # Graph's 202 is acceptance only, not proof of final delivery. No automatic retries.
        response = requests.post(GRAPH + '/me/sendMail', data=mime,
            headers={**self.headers, 'Content-Type': 'text/plain'}, timeout=20, allow_redirects=False)
        if response.status_code != 202:
            raise ValueError('Microsoft did not accept the message')
        return response.status_code


def connected_provider(db, user_id, settings):
    connection = db.scalar(select(OutlookConnection).where(OutlookConnection.user_id == user_id))
    if connection is None:
        raise HTTPException(409, 'Connect your Outlook account first')
    try:
        cache = msal.SerializableTokenCache()
        cache.deserialize(cipher(settings).decrypt(connection.encrypted_credentials.encode()).decode())
        client = oauth_client(settings, cache)
        accounts = client.get_accounts()
        if len(accounts) != 1:
            raise ValueError('Reconnect the intended Outlook account')
        result = client.acquire_token_silent(SCOPES, account=accounts[0])
        if not result or not result.get('access_token'):
            raise ValueError('Consent or token refresh is required')
        provider = OutlookProvider(result['access_token'], cache)
        save_credentials(connection, provider, settings)
        db.commit()
        return connection, provider
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Outlook access expired or credentials cannot be read. Reconnect Outlook.')


def sync_mailbox(db, actor, settings, provider=None):
    connection, live = connected_provider(db, actor.user_id, settings) if provider is None else (None, provider)
    mailbox = connection.email_address.lower() if connection else 'test-sender@example.com'
    added = skipped = 0
    try:
        messages = live.list_messages(20)
        for item in messages:
            ident = str(item['id'])
            if not ident or len(ident) > 512:
                skipped += 1
                continue
            fingerprint = hashlib.sha256(f'outlook:{actor.user_id}:{mailbox}:{ident}'.encode()).hexdigest()
            if db.scalar(select(EmailMessage.id).where(EmailMessage.fingerprint == fingerprint)):
                continue
            try:
                raw = live.get_raw(ident)
                data, recipient, message_id = parse_gmail(raw)
                thread = str(raw.get('threadId', ident))[:128]
                with db.begin_nested():
                    db.add(EmailMessage(sender=str(data.sender), subject=data.subject, body=data.body,
                        thread_id=f'outlook:{actor.user_id}:{token_hash(mailbox)[:16]}:{thread}'[:120], fingerprint=fingerprint, owner_user_id=actor.user_id,
                        outlook_message_id=ident, original_message_id=message_id, reply_to=recipient))
                    db.flush()
                added += 1
            except (ValueError, TypeError, IntegrityError):
                skipped += 1
        if connection:
            connection.last_synced_at = utcnow()
            save_credentials(connection, live, settings)
        audit(db, actor, 'outlook_synced', actor.user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Outlook sync failed. Reconnect Outlook if permissions were revoked, then retry.')
    return {'imported': added, 'skipped': skipped, 'checked': len(messages)}


def send_approved_draft(db, draft, actor, payload, settings, provider=None):
    email = draft.email
    if actor.user_id is None or email.owner_user_id != actor.user_id or not email.outlook_message_id:
        raise HTTPException(404, 'Record not found')
    if not settings.outlook_send_enabled or settings.llm_provider != 'openai':
        raise HTTPException(409, 'Sending requires live OpenAI processing and OUTLOOK_SEND_ENABLED=true')
    if draft.delivery_status == 'accepted':
        return draft
    if draft.status != 'approved' or draft.revision != payload.revision:
        raise HTTPException(409, 'Approve the current draft revision before sending')
    recipient = email.reply_to or email.sender
    if str(payload.recipient).lower() != recipient.lower() or payload.confirmation != 'SEND':
        raise HTTPException(409, 'Confirm the exact displayed recipient before sending')
    connection, live = connected_provider(db, actor.user_id, settings) if provider is None else (None, provider)
    if connection:
        expected = hashlib.sha256(f'outlook:{actor.user_id}:{connection.email_address.lower()}:{email.outlook_message_id}'.encode()).hexdigest()
        if email.fingerprint != expected:
            raise HTTPException(409, 'Reconnect the Outlook mailbox that originally imported this message before sending')
    sender = connection.email_address if connection else 'test-sender@example.com'
    message = MimeMessage()
    message['From'], message['To'] = sender, recipient
    message['Subject'] = email.subject if email.subject.lower().startswith('re:') else 'Re: ' + email.subject
    message['Message-ID'] = make_msgid()
    if email.original_message_id:
        message['In-Reply-To'] = email.original_message_id
        message['References'] = email.original_message_id
    message.set_content(draft.body)
    claimed = db.execute(update(ReplyDraft).where(ReplyDraft.id == draft.id, ReplyDraft.revision == payload.revision,
        ReplyDraft.status == 'approved', ReplyDraft.delivery_status == 'not_sent').values(delivery_status='sending'))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Delivery is already attempted; check Outlook Sent before taking further action')
    db.commit()
    try:
        result = live.send(base64.b64encode(message.as_bytes()).decode())
        if result != 202:
            raise ValueError('Submission not accepted')
        draft.delivery_status, draft.sent_at = 'accepted', utcnow()
        if connection:
            save_credentials(connection, live, settings)
        audit(db, actor, 'outlook_accepted', draft.id)
        db.commit()
    except Exception:
        db.rollback()
        db.refresh(draft)
        draft.delivery_status = 'unknown'
        audit(db, actor, 'outlook_delivery_unknown', draft.id)
        db.commit()
        raise HTTPException(502, 'Delivery outcome is unknown. Check Outlook Sent; do not retry automatically.')
    db.refresh(draft)
    return draft
