from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Numeric, Date, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class Timestamped:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailMessage(Timestamped, Base):
    __tablename__ = 'emails'
    sender: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(String(120), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default='new', index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey('user_accounts.id', name='fk_emails_owner_user_id'), index=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(128))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(128))
    outlook_message_id: Mapped[str | None] = mapped_column(String(512))
    original_message_id: Mapped[str | None] = mapped_column(String(500))
    reply_to: Mapped[str | None] = mapped_column(String(320))
    extraction: Mapped['ExtractedEmailData | None'] = relationship(back_populates='email', uselist=False)
    draft: Mapped['ReplyDraft | None'] = relationship(back_populates='email', uselist=False)


class ExtractedEmailData(Timestamped, Base):
    __tablename__ = 'extractions'
    email_id: Mapped[int] = mapped_column(ForeignKey('emails.id'), unique=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    urgency: Mapped[str] = mapped_column(String(16), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    email: Mapped[EmailMessage] = relationship(back_populates='extraction')


class Customer(Timestamped, Base):
    __tablename__ = 'customers'
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    fictional: Mapped[bool] = mapped_column(default=True)


class Invoice(Timestamped, Base):
    __tablename__ = 'invoices'
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), index=True)
    number: Mapped[str] = mapped_column(String(80), unique=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    due_date: Mapped[datetime] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24))


class Order(Timestamped, Base):
    __tablename__ = 'orders'
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), index=True)
    number: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(String(300))


class ReplyDraft(Timestamped, Base):
    __tablename__ = 'drafts'
    email_id: Mapped[int] = mapped_column(ForeignKey('emails.id'), unique=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default='pending')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    delivery_status: Mapped[str] = mapped_column(String(24), default='not_sent', server_default='not_sent')
    gmail_sent_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email: Mapped[EmailMessage] = relationship(back_populates='draft')


class ProcessingRun(Timestamped, Base):
    __tablename__ = 'processing_runs'
    email_id: Mapped[int] = mapped_column(ForeignKey('emails.id'), index=True)
    status: Mapped[str] = mapped_column(String(24))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)


class ToolExecutionLog(Timestamped, Base):
    __tablename__ = 'tool_logs'
    run_id: Mapped[int] = mapped_column(ForeignKey('processing_runs.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    arguments: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    outcome: Mapped[dict] = mapped_column(JSON)


class UserAccount(Timestamped, Base):
    __tablename__ = 'user_accounts'
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(24), default='viewer')
    active: Mapped[bool] = mapped_column(default=True)


class AuthSession(Timestamped, Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[int] = mapped_column(ForeignKey('user_accounts.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(default=False)


class LoginAttempt(Timestamped, Base):
    __tablename__ = 'login_attempts'
    identity_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SecurityAudit(Timestamped, Base):
    __tablename__ = 'security_audit'
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120))


class GmailConnection(Timestamped, Base):
    __tablename__ = 'gmail_connections'
    user_id: Mapped[int] = mapped_column(ForeignKey('user_accounts.id'), unique=True)
    email_address: Mapped[str] = mapped_column(String(320))
    encrypted_credentials: Mapped[str] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GmailOAuthState(Timestamped, Base):
    __tablename__ = 'gmail_oauth_states'
    user_id: Mapped[int] = mapped_column(ForeignKey('user_accounts.id'), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(default=False)


class OutlookConnection(Timestamped, Base):
    __tablename__ = 'outlook_connections'
    user_id: Mapped[int] = mapped_column(ForeignKey('user_accounts.id'), unique=True)
    email_address: Mapped[str] = mapped_column(String(320))
    encrypted_credentials: Mapped[str] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutlookOAuthState(Timestamped, Base):
    __tablename__ = 'outlook_oauth_states'
    user_id: Mapped[int] = mapped_column(ForeignKey('user_accounts.id'), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_flow: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(default=False)
