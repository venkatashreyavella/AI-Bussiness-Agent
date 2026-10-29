from typing import Literal
from pydantic import EmailStr, Field
from app.schemas import StrictModel


class OAuthCallback(StrictModel):
    state: str = Field(min_length=32, max_length=200)
    code: str = Field(min_length=1, max_length=4096)


class SendRequest(StrictModel):
    revision: int = Field(ge=1)
    recipient: EmailStr
    confirmation: Literal['SEND']
