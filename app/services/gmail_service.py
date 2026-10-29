"""Gmail OAuth, private import and explicit reviewed delivery; no autonomous sends."""
import base64
import hashlib
import json
import secrets
from datetime import timedelta
from email import policy
from email.message import EmailMessage as MimeMessage
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid
from html.parser import HTMLParser
from urllib.parse import urlparse
import httplib2
import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models import (EmailMessage, ReplyDraft, GmailConnection, GmailOAuthState, UserAccount, utcnow)
from app.schemas import EmailCreate
from app.core.security import token_hash, aware, audit

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']


def missing_config(settings):
    return [name for name in ['google_client_id', 'google_client_secret', 'token_encryption_key'] if not getattr(settings, name)]


def cipher(settings):
    try:
        return Fernet(settings.token_encryption_key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, 'Mailbox token encryption key is missing or invalid')


def oauth_flow(settings, verifier, state=None):
    if missing_config(settings):
        raise HTTPException(503, 'Configure the Google OAuth client and token encryption key first')
    uri = urlparse(settings.google_redirect_uri)
    if uri.scheme != 'https' and not (uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1'}):
        raise HTTPException(503, 'Google redirect URI must use HTTPS, or localhost for development')
    return Flow.from_client_config({'web': {'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret, 'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token', 'redirect_uris': [settings.google_redirect_uri]}},
        scopes=SCOPES, redirect_uri=settings.google_redirect_uri, code_verifier=verifier, state=state)


def begin_oauth(db, actor, settings):
    state, verifier = secrets.token_urlsafe(40), secrets.token_urlsafe(64)
    flow = oauth_flow(settings, verifier, state)
    url, _ = flow.authorization_url(state=state, access_type='offline', prompt='consent select_account')
    db.add(GmailOAuthState(user_id=actor.user_id, state_hash=token_hash(state),
        encrypted_verifier=cipher(settings).encrypt(verifier.encode()).decode(), expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return url


def finish_oauth(db, code, state, settings, user_id):
    record = db.scalar(select(GmailOAuthState).where(GmailOAuthState.state_hash == token_hash(state)))
    if record is None or record.used or aware(record.expires_at) <= utcnow():
        raise HTTPException(400, 'Gmail connection link expired or was already used. Start again.')
    if record.user_id != user_id:
        raise HTTPException(400, 'Sign in with the same application account that started this Gmail connection')
    user = db.get(UserAccount, record.user_id)
    if not user or not user.active or user.role not in {'admin', 'reviewer'}:
        raise HTTPException(403, 'This account cannot connect Gmail')
    claimed = db.execute(update(GmailOAuthState).where(GmailOAuthState.id == record.id,
        GmailOAuthState.used.is_(False)).values(used=True))
    if claimed.rowcount != 1:
        raise HTTPException(400, 'Gmail connection link was already used')
    verifier = cipher(settings).decrypt(record.encrypted_verifier.encode()).decode()
    db.commit()
    try:
        flow = oauth_flow(settings, verifier, state)
        flow.fetch_token(code=code, timeout=20)
        credentials = flow.credentials
        if not credentials.refresh_token or not set(SCOPES).issubset(set(credentials.granted_scopes or credentials.scopes or [])):
            raise ValueError('Required Gmail permissions were not granted')
        provider = GmailProvider(credentials=credentials)
        address = provider.profile()['emailAddress']
        connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
        if not connection:
            connection = GmailConnection(user_id=user.id, email_address=address, encrypted_credentials='')
            db.add(connection)
        connection.email_address = address
        connection.encrypted_credentials = cipher(settings).encrypt(credentials.to_json().encode()).decode()
        audit(db, user.username, 'gmail_connected', user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Google connection failed. Check consent permissions and OAuth settings, then start again.')


class GmailProvider:
    def __init__(self, credentials=None, service=None):
        self.credentials = credentials
        self.service = service or build('gmail', 'v1', http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=20)), cache_discovery=False)

    def profile(self):
        return self.service.users().getProfile(userId='me').execute(num_retries=0)

    def list_messages(self, limit=20):
        return self.service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=limit).execute(num_retries=0).get('messages', [])

    def get_raw(self, ident):
        return self.service.users().messages().get(userId='me', id=ident, format='raw').execute(num_retries=0)

    def send(self, body):
        # A delivery request is never automatically retried; an ambiguous result is reconciled manually.
        return self.service.users().messages().send(userId='me', body=body).execute(num_retries=0)


def connected_provider(db, user_id, settings):
    connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id))
    if connection is None:
        raise HTTPException(409, 'Connect your Gmail account first')
    try:
        data = json.loads(cipher(settings).decrypt(connection.encrypted_credentials.encode()))
        credentials = Credentials.from_authorized_user_info(data, scopes=SCOPES)
    except (ValueError, KeyError, InvalidToken):
        raise HTTPException(409, 'Gmail credentials cannot be read. Reconnect Gmail or restore the encryption key.')
    return connection, GmailProvider(credentials=credentials)


def save_credentials(connection, provider, settings):
    if provider.credentials:
        connection.encrypted_credentials = cipher(settings).encrypt(provider.credentials.to_json().encode()).decode()


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1
        elif tag in {'p', 'br', 'div', 'li'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def parse_gmail(raw):
    encoded = raw.get('raw', '')
    if len(encoded) > 2_700_000:
        raise ValueError('Email exceeds import limit')
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    addresses = getaddresses([str(message.get('From', ''))])
    if len(addresses) != 1:
        raise ValueError('One sender is required')
    part = message.get_body(preferencelist=('plain', 'html'))
    if part is None:
        raise ValueError('No text body')
    body = part.get_content()
    if part.get_content_type() == 'text/html':
        parser = PlainHTML()
        parser.feed(body)
        body = ''.join(parser.parts)
    email = EmailCreate(sender=addresses[0][1], subject=str(message.get('Subject') or '(No subject)')[:500], body=body)
    reply = getaddresses([str(message.get('Reply-To', message.get('From', '')))])
    if len(reply) != 1:
        raise ValueError('One reply recipient is required')
    recipient = EmailCreate(sender=reply[0][1], subject='validation', body='validation').sender
    original_id = str(message.get('Message-ID', ''))
    if '\r' in original_id or '\n' in original_id:
        original_id = ''
    return email, str(recipient), original_id[:500] or None


def sync_mailbox(db, actor, settings, provider=None):
    connection, live = connected_provider(db, actor.user_id, settings) if provider is None else (None, provider)
    mailbox = connection.email_address.lower() if connection else 'test-sender@example.com'
    added = skipped = 0
    try:
        messages = live.list_messages(20)
        for item in messages:
            ident = str(item['id'])[:128]
            fingerprint = hashlib.sha256(f'gmail:{actor.user_id}:{mailbox}:{ident}'.encode()).hexdigest()
            if db.scalar(select(EmailMessage.id).where(EmailMessage.fingerprint == fingerprint)):
                continue
            try:
                raw = live.get_raw(ident)
                data, recipient, message_id = parse_gmail(raw)
                thread = str(raw.get('threadId', ident))[:128]
                with db.begin_nested():
                    db.add(EmailMessage(sender=str(data.sender), subject=data.subject, body=data.body,
                        thread_id=f'gmail:{actor.user_id}:{token_hash(mailbox)[:16]}:{thread}'[:120], fingerprint=fingerprint, owner_user_id=actor.user_id,
                        gmail_message_id=ident, gmail_thread_id=thread, original_message_id=message_id, reply_to=recipient))
                    db.flush()
                added += 1
            except (ValueError, TypeError, IntegrityError):
                skipped += 1
        if connection:
            connection.last_synced_at = utcnow()
            save_credentials(connection, live, settings)
        audit(db, actor, 'gmail_synced', actor.user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Gmail sync failed. Reconnect Gmail if permissions were revoked, then retry.')
    return {'imported': added, 'skipped': skipped, 'checked': len(messages)}


def send_approved_draft(db, draft, actor, payload, settings, provider=None):
    email = draft.email
    if actor.user_id is None or email.owner_user_id != actor.user_id or not email.gmail_message_id:
        raise HTTPException(404, 'Record not found')
    if not settings.gmail_send_enabled or settings.llm_provider != 'openai':
        raise HTTPException(409, 'Sending requires live OpenAI processing and GMAIL_SEND_ENABLED=true')
    if draft.delivery_status == 'sent':
        return draft
    if draft.status != 'approved' or draft.revision != payload.revision:
        raise HTTPException(409, 'Approve the current draft revision before sending')
    recipient = email.reply_to or email.sender
    if str(payload.recipient).lower() != recipient.lower() or payload.confirmation != 'SEND':
        raise HTTPException(409, 'Confirm the exact displayed recipient before sending')
    connection, live = connected_provider(db, actor.user_id, settings) if provider is None else (None, provider)
    if connection:
        expected = hashlib.sha256(f'gmail:{actor.user_id}:{connection.email_address.lower()}:{email.gmail_message_id}'.encode()).hexdigest()
        if email.fingerprint != expected:
            raise HTTPException(409, 'Reconnect the Gmail mailbox that originally imported this message before sending')
    sender = connection.email_address if connection else 'test-sender@example.com'
    message = MimeMessage()
    message['From'], message['To'] = sender, recipient
    message['Subject'] = email.subject if email.subject.lower().startswith('re:') else 'Re: ' + email.subject
    message['Message-ID'] = make_msgid()
    if email.original_message_id:
        message['In-Reply-To'] = email.original_message_id
        message['References'] = email.original_message_id
    message.set_content(draft.body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    claimed = db.execute(update(ReplyDraft).where(ReplyDraft.id == draft.id, ReplyDraft.revision == payload.revision,
        ReplyDraft.status == 'approved', ReplyDraft.delivery_status == 'not_sent').values(delivery_status='sending'))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Delivery is already attempted; check Gmail Sent before taking further action')
    db.commit()
    try:
        result = live.send({'raw': raw, 'threadId': email.gmail_thread_id})
        if not result.get('id'):
            raise ValueError('Delivery not confirmed')
        draft.delivery_status, draft.gmail_sent_id, draft.sent_at = 'sent', result['id'], utcnow()
        if connection:
            save_credentials(connection, live, settings)
        audit(db, actor, 'gmail_sent', draft.id)
        db.commit()
    except Exception:
        db.rollback()
        db.refresh(draft)
        draft.delivery_status = 'unknown'
        audit(db, actor, 'gmail_delivery_unknown', draft.id)
        db.commit()
        raise HTTPException(502, 'Delivery outcome is unknown. Check Gmail Sent; do not retry automatically.')
    db.refresh(draft)
    return draft
