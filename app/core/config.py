from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./inbox.db'
    llm_provider: str = 'demo'
    openai_api_key: str = ''
    openai_model: str = ''
    app_api_token: str = ''
    public_signup_enabled: bool = True
    llm_timeout_seconds: float = 45
    sample_due_date: str = '2026-11-30'
    google_client_id: str = ''
    google_client_secret: str = ''
    google_redirect_uri: str = 'http://127.0.0.1:8501/'
    token_encryption_key: str = ''
    gmail_send_enabled: bool = False
    microsoft_client_id: str = ''
    microsoft_client_secret: str = ''
    microsoft_tenant: str = 'common'
    microsoft_redirect_uri: str = 'http://127.0.0.1:8501/'
    outlook_send_enabled: bool = False

    @model_validator(mode='after')
    def validate_config(self):
        if self.llm_provider not in {'demo', 'openai'}:
            raise ValueError('LLM_PROVIDER must be demo or openai')
        if self.llm_provider == 'openai' and not (self.openai_api_key and self.openai_model):
            raise ValueError('OpenAI mode requires OPENAI_API_KEY and OPENAI_MODEL')
        return self


@lru_cache
def get_settings():
    return Settings()
