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
    llm_timeout_seconds: float = 45
    sample_due_date: str = '2026-11-30'

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
