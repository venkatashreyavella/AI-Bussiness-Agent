import hashlib
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, or_, update
from sqlalchemy.exc import IntegrityError
from app.core.config import get_settings
from app.db.session import get_db
from app.models import EmailMessage, ReplyDraft, ProcessingRun, ToolExecutionLog, ExtractedEmailData, utcnow
from app.schemas import EmailCreate, DraftEdit, Review, Category, EmailResponse, DraftResponse, ResultResponse
from app.services.email_service import process_email, ProcessingConflict
from app.core.security import require_writer, current_principal, audit
from app.core.email_access import visible_emails, check_email_access
from app.schemas.gmail import SendRequest

router = APIRouter()


def required(db, model, ident, actor=None):
    row = db.get(model, ident)
    if row is None:
        raise HTTPException(404, 'Record not found')
    if actor is not None:
        if model is EmailMessage:
            check_email_access(row, actor)
        elif model is ReplyDraft:
            check_email_access(db.get(EmailMessage, row.email_id), actor)
    return row


def serialize_email(email):
    return {'id': email.id, 'sender': email.sender, 'subject': email.subject, 'body': email.body,
            'thread_id': email.thread_id, 'created_at': email.created_at, 'status': email.status,
            'category': email.extraction.category if email.extraction else None,
            'urgency': email.extraction.urgency if email.extraction else None,
            'private': email.owner_user_id is not None, 'source': 'gmail' if email.gmail_message_id else 'manual',
            'reply_to': email.reply_to}


def serialize_draft(d):
    return dict(id=d.id, email_id=d.email_id, body=d.body, status=d.status, revision=d.revision,
                reviewed_at=d.reviewed_at, reviewed_by=d.reviewed_by,
                sending_enabled=bool(d.email.gmail_message_id and get_settings().gmail_send_enabled and get_settings().llm_provider == 'openai'),
                delivery_status=d.delivery_status, gmail_sent_id=d.gmail_sent_id, sent_at=d.sent_at)


@router.post('/emails', status_code=201, response_model=EmailResponse, dependencies=[Depends(require_writer)])
def create_email(payload: EmailCreate, db=Depends(get_db)):
    data = payload.model_dump(mode='json')
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(EmailMessage).where(EmailMessage.fingerprint == fingerprint))
    if existing:
        return serialize_email(existing)
    email = EmailMessage(**data, fingerprint=fingerprint)
    db.add(email)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        email = db.scalar(select(EmailMessage).where(EmailMessage.fingerprint == fingerprint))
        if email is None:
            raise
    return serialize_email(email)


@router.post('/emails/import', status_code=201, response_model=EmailResponse, dependencies=[Depends(require_writer)])
async def import_email(file: UploadFile = File(...), db=Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith('.eml'):
        raise HTTPException(415, 'Upload a .eml file; only plain-text attachments are supported')
    raw = await file.read(100001)
    if len(raw) > 100000:
        raise HTTPException(413, 'Email file exceeds 100 KB')
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        sender = message['From'].addresses[0].addr_spec
        body = message.get_body(preferencelist=('plain',))
        if body is None:
            raise ValueError('Plain text required')
        content = body.get_content()
        for attachment in message.iter_attachments():
            if attachment.get_content_type() != 'text/plain':
                raise HTTPException(415, 'Only text/plain document attachments are supported; remove other attachments')
            text = attachment.get_content()
            if len(text) > 10000:
                raise HTTPException(413, 'Text attachment exceeds 10,000 characters')
            content += '\n\n[Untrusted attached document]\n' + text
        payload = EmailCreate(sender=sender, subject=str(message['Subject'] or ''), body=content)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, 'A valid sender, subject and plain-text body are required')
    return create_email(payload, db)


@router.get('/emails', response_model=list[EmailResponse])
def list_emails(q: str = Query('', max_length=200), category: Category | None = None,
                urgency: str | None = Query(None, pattern='^(low|normal|high)$'),
                status: str | None = Query(None, pattern='^(new|processing|processed|failed)$'),
                offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db=Depends(get_db), actor=Depends(current_principal)):
    statement = select(EmailMessage).outerjoin(ExtractedEmailData).where(visible_emails(actor))
    if q:
        statement = statement.where(or_(EmailMessage.subject.icontains(q, autoescape=True), EmailMessage.sender.icontains(q, autoescape=True)))
    if category:
        statement = statement.where(ExtractedEmailData.category == category.value)
    if urgency:
        statement = statement.where(ExtractedEmailData.urgency == urgency)
    if status:
        statement = statement.where(EmailMessage.status == status)
    return [serialize_email(e) for e in db.scalars(statement.order_by(EmailMessage.id.desc()).offset(offset).limit(limit)).all()]


@router.get('/emails/{email_id}', response_model=EmailResponse)
def get_email(email_id: int, db=Depends(get_db), actor=Depends(current_principal)):
    return serialize_email(required(db, EmailMessage, email_id, actor))


@router.post('/emails/{email_id}/process', response_model=ResultResponse, dependencies=[Depends(require_writer)])
def process(email_id: int, db=Depends(get_db), actor=Depends(require_writer)):
    email = required(db, EmailMessage, email_id, actor)
    if email.owner_user_id is not None and get_settings().llm_provider != 'openai':
        raise HTTPException(409, 'Configure live OpenAI before processing real Gmail messages')
    try:
        email = process_email(db, email_id, get_settings())
    except ProcessingConflict:
        raise HTTPException(409, 'Email is already processing')
    if email.status == 'failed':
        raise HTTPException(502, 'Processing failed; inspect results for a safe error code and retry')
    return get_results(email_id, db, actor)


@router.get('/emails/{email_id}/results', response_model=ResultResponse)
def get_results(email_id: int, db=Depends(get_db), actor=Depends(current_principal)):
    email = required(db, EmailMessage, email_id, actor)
    runs = db.scalars(select(ProcessingRun).where(ProcessingRun.email_id == email_id).order_by(ProcessingRun.id)).all()
    logs = db.scalars(select(ToolExecutionLog).where(ToolExecutionLog.run_id.in_([r.id for r in runs]))).all() if runs else []
    return {'email': serialize_email(email), 'extraction': email.extraction.data if email.extraction else None,
            'draft': serialize_draft(email.draft) if email.draft else None,
            'runs': [dict(id=r.id, status=r.status, provider=r.provider, model=r.model, error_code=r.error_code,
                          validation_errors=r.validation_errors, created_at=r.created_at, finished_at=r.finished_at) for r in runs],
            'tools': [dict(name=t.name, arguments=t.arguments, status=t.status, outcome=t.outcome) for t in logs]}


def mutate_draft(db, ident, revision, values, actor=None, action=None):
    draft = required(db, ReplyDraft, ident, actor)
    if draft.delivery_status != 'not_sent':
        raise HTTPException(409, 'This draft has a delivery attempt; it cannot be edited or re-reviewed')
    result = db.execute(update(ReplyDraft).where(ReplyDraft.id == ident, ReplyDraft.revision == revision,
                        ReplyDraft.delivery_status == 'not_sent')
                        .values(**values, revision=revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Draft changed; refresh and review the latest revision')
    if actor and action:
        audit(db, actor, action, ident)
    db.commit()
    db.expire_all()
    return serialize_draft(db.get(ReplyDraft, ident))


@router.patch('/drafts/{draft_id}', response_model=DraftResponse)
def edit_draft(draft_id: int, payload: DraftEdit, db=Depends(get_db), actor=Depends(require_writer)):
    if not payload.body.strip():
        raise HTTPException(422, 'Draft must not be blank')
    return mutate_draft(db, draft_id, payload.revision, dict(body=payload.body.strip(), status='pending', reviewed_at=None, reviewed_by=None), actor, 'draft_edited')


@router.post('/drafts/{draft_id}/approve', response_model=DraftResponse)
def approve(draft_id: int, payload: Review, db=Depends(get_db), actor=Depends(require_writer)):
    reviewer = actor.username if actor.user_id else payload.reviewer
    return mutate_draft(db, draft_id, payload.revision, dict(status='approved', reviewed_at=utcnow(), reviewed_by=reviewer), actor, 'draft_approved')


@router.post('/drafts/{draft_id}/reject', response_model=DraftResponse)
def reject(draft_id: int, payload: Review, db=Depends(get_db), actor=Depends(require_writer)):
    reviewer = actor.username if actor.user_id else payload.reviewer
    return mutate_draft(db, draft_id, payload.revision, dict(status='rejected', reviewed_at=utcnow(), reviewed_by=reviewer), actor, 'draft_rejected')


@router.post('/drafts/{draft_id}/send', response_model=DraftResponse)
def send(draft_id: int, payload: SendRequest | None = None, actor=Depends(require_writer), db=Depends(get_db)):
    from app.services.gmail_service import send_approved_draft
    draft = required(db, ReplyDraft, draft_id, actor)
    if not get_settings().gmail_send_enabled or not draft.email.gmail_message_id:
        raise HTTPException(409, 'Sending is disabled. Connect Gmail and configure approved sending first.')
    if payload is None:
        raise HTTPException(422, 'Confirm the recipient, reviewed revision and SEND action')
    send_approved_draft(db, draft, actor, payload, get_settings())
    return serialize_draft(draft)


@router.get('/analytics')
def analytics(db=Depends(get_db), actor=Depends(current_principal)):
    from collections import Counter
    emails = db.scalars(select(EmailMessage).where(visible_emails(actor))).all()
    drafts = db.scalars(select(ReplyDraft).join(EmailMessage).where(visible_emails(actor))).all()
    runs = db.scalars(select(ProcessingRun).join(EmailMessage).where(visible_emails(actor))).all()
    extracted = [e.extraction.data for e in emails if e.extraction]
    report = Path('evaluation/reports/latest.json')
    return dict(total_emails=len(emails), statuses=dict(Counter(e.status for e in emails)),
                categories=dict(Counter(e['category'] for e in extracted)),
                drafts=dict(Counter(d.status for d in drafts)), processing_failures=sum(r.status == 'failed' for r in runs),
                validation_failures=sum(r.error_code == 'validation_error' for r in runs),
                missing_field_count=sum(len(e['missing_information']) for e in extracted),
                extraction_count=len(extracted), evaluation=json.loads(report.read_text()) if report.exists() else None)
