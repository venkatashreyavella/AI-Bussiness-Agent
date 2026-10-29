from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Category(str, Enum):
    sales = 'sales_enquiry'
    invoice = 'invoice_enquiry'
    order = 'order'
    complaint = 'customer_complaint'
    payment = 'payment_follow_up'
    general = 'general_request'


class EmailCreate(StrictModel):
    sender: EmailStr
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50000)
    thread_id: str | None = Field(default=None, max_length=120)

    @field_validator('subject', 'body')
    @classmethod
    def strip_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Text must not be blank')
        return value


class Extraction(StrictModel):
    category: Category
    summary: str = Field(min_length=1, max_length=2000)
    sender: str
    customer_name: str | None
    invoice_number: str | None
    amount: float | None = Field(ge=0)
    currency: str | None = Field(pattern=r'^[A-Z]{3}$')
    due_date: date | None
    order_number: str | None
    urgency: str = Field(pattern=r'^(low|normal|high)$')
    requested_action: str = Field(min_length=1, max_length=2000)
    missing_information: list[str]
    uncertainty: list[str]
    confidence: float = Field(ge=0, le=1)
    suggested_next_step: str


class DraftOutput(StrictModel):
    body: str = Field(min_length=1, max_length=20000)


class DraftEdit(DraftOutput):
    revision: int = Field(ge=1)


class Review(StrictModel):
    revision: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=120)

    @field_validator('reviewer')
    @classmethod
    def nonblank_reviewer(cls, value):
        if not value.strip():
            raise ValueError('Reviewer must not be blank')
        return value.strip()


class EmailResponse(StrictModel):
    id: int
    sender: str
    subject: str
    body: str
    thread_id: str | None
    created_at: datetime
    status: str
    category: Category | None
    urgency: str | None
    private: bool = False
    source: str = 'manual'
    reply_to: str | None = None


class DraftResponse(StrictModel):
    id: int
    email_id: int
    body: str
    status: str
    revision: int
    reviewed_at: datetime | None
    reviewed_by: str | None
    sending_enabled: bool
    delivery_status: str = 'not_sent'
    gmail_sent_id: str | None = None
    sent_at: datetime | None = None


class RunResponse(StrictModel):
    id: int
    status: str
    provider: str
    model: str | None
    error_code: str | None
    validation_errors: list[dict]
    created_at: datetime
    finished_at: datetime | None


class ToolLogResponse(StrictModel):
    name: str
    arguments: dict
    status: str
    outcome: dict


class ResultResponse(StrictModel):
    email: EmailResponse
    extraction: Extraction | None
    draft: DraftResponse | None
    runs: list[RunResponse]
    tools: list[ToolLogResponse]
