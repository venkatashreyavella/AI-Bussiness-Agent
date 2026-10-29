from sqlalchemy import select, update
from app.models import EmailMessage, ExtractedEmailData, ReplyDraft, ProcessingRun, utcnow
from app.schemas import Extraction, DraftOutput
from app.services.business_tools import BusinessTools
from app.services.llm_service import get_provider


def classify_email(provider, email, thread=None):
    return extract_email_data(provider, email, thread).category


def extract_email_data(provider, email, thread=None):
    return Extraction.model_validate(provider.extract_email_data(email, thread or []))


def summarize_email(provider, email, thread=None):
    return extract_email_data(provider, email, thread).summary


def retrieve_business_context(extraction, tools):
    if extraction.invoice_number:
        tools.execute('get_invoice_status', {'invoice_number': extraction.invoice_number})
    if extraction.order_number:
        tools.execute('get_order_status', {'order_number': extraction.order_number})
    tools.execute('search_customer', {'customer_name_or_email': extraction.customer_name or extraction.sender})
    return tools.evidence


def generate_reply_draft(provider, email, extraction, tools, thread=None):
    return DraftOutput.model_validate(provider.generate_reply_draft(email, extraction, tools, thread or []))


class ProcessingConflict(Exception):
    pass


def process_email(db, email_id, settings, provider=None):
    email = db.get(EmailMessage, email_id)
    if email.status == 'processed':
        return email
    # Atomic claim is committed before the network call so concurrent requests cannot duplicate work.
    claimed = db.execute(update(EmailMessage).where(EmailMessage.id == email_id,
        EmailMessage.status.in_(['new', 'failed'])).values(status='processing'))
    if claimed.rowcount != 1:
        db.rollback()
        raise ProcessingConflict('Email is already processing')
    run = ProcessingRun(email_id=email_id, status='processing', provider=settings.llm_provider,
                        model=settings.openai_model or None)
    db.add(run)
    db.commit()
    try:
        provider = provider or get_provider(settings)
        payload = {'sender': email.sender, 'subject': email.subject, 'body': email.body}
        thread = []
        if email.thread_id:
            earlier = db.scalars(select(EmailMessage).where(EmailMessage.thread_id == email.thread_id,
                EmailMessage.owner_user_id == email.owner_user_id,
                EmailMessage.id < email.id).order_by(EmailMessage.id.desc()).limit(5)).all()
            thread = [{'sender': e.sender, 'subject': e.subject, 'body': e.body[:5000]} for e in reversed(earlier)]
        extraction = extract_email_data(provider, payload, thread)
        tools = BusinessTools(db, run.id, include_demo_records=email.owner_user_id is None)
        retrieve_business_context(extraction, tools)
        draft = generate_reply_draft(provider, payload, extraction, tools, thread)
        db.add(ExtractedEmailData(email_id=email_id, category=extraction.category.value, urgency=extraction.urgency,
                                  data=extraction.model_dump(mode='json')))
        db.add(ReplyDraft(email_id=email_id, body=draft.body, status='pending'))
        email.status, run.status, run.finished_at = 'processed', 'success', utcnow()
        db.commit()
    except Exception as exc:
        # Keep safe audit information without serializing model outputs, email contents or credentials.
        from pydantic import ValidationError
        from openai import APIError
        error_code = 'validation_error' if isinstance(exc, (ValidationError, ValueError)) else 'llm_api_error' if isinstance(exc, APIError) else 'processing_error'
        errors = [{'field': '.'.join(map(str, e['loc'])), 'type': e['type']} for e in exc.errors()] if isinstance(exc, ValidationError) else []
        # Preserve completed tool activity even when subsequent generation fails.
        logs = list(tools.evidence) if 'tools' in locals() else []
        db.rollback()
        email = db.get(EmailMessage, email_id)
        run = db.get(ProcessingRun, run.id)
        email.status, run.status = 'failed', 'failed'
        run.error_code, run.validation_errors, run.finished_at = error_code, errors, utcnow()
        from app.models import ToolExecutionLog
        for log in logs:
            db.add(ToolExecutionLog(run_id=run.id, name=log['tool'], arguments={}, status=log['status'],
                                    outcome={k: v for k, v in log.items() if k not in {'tool', 'status'}}))
        db.commit()
    db.refresh(email)
    return email
