from datetime import datetime
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.schemas import StrictModel

Role = Literal['admin', 'reviewer', 'viewer']


class Login(StrictModel):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[A-Za-z0-9_.@+\-]+$')
    password: str = Field(min_length=1, max_length=256)

    @field_validator('username')
    @classmethod
    def normalize(cls, value):
        return value.lower()


class AccountCreate(Login):
    password: str = Field(min_length=16, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    role: Role = 'viewer'

    @field_validator('display_name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Display name must not be blank')
        return value.strip()


class AccountUpdate(StrictModel):
    role: Role | None = None
    active: bool | None = None

    @model_validator(mode='after')
    def has_change(self):
        if self.role is None and self.active is None:
            raise ValueError('A role or active status is required')
        return self


class AccountRegistration(Login):
    password: str = Field(min_length=16, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator('display_name')
    @classmethod
    def optional_name(cls, value):
        return value.strip() or None if value is not None else None


class PasswordReset(StrictModel):
    new_password: str = Field(min_length=16, max_length=256)


class PasswordChange(PasswordReset):
    current_password: str = Field(min_length=1, max_length=256)


class AccountResponse(StrictModel):
    id: int
    username: str
    display_name: str
    role: Role
    active: bool
    created_at: datetime


class SessionResponse(StrictModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: datetime
    user: AccountResponse
