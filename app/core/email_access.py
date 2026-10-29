from fastapi import HTTPException
from sqlalchemy import or_
from app.models import EmailMessage


def visible_emails(actor):
    if actor.user_id is None:
        return EmailMessage.owner_user_id.is_(None)
    return or_(EmailMessage.owner_user_id.is_(None), EmailMessage.owner_user_id == actor.user_id)


def check_email_access(email, actor):
    # Real provider mail is private to its owner, including from other administrators and service integrations.
    if email is None or (email.owner_user_id is not None and email.owner_user_id != actor.user_id):
        raise HTTPException(404, 'Record not found')
    return email
