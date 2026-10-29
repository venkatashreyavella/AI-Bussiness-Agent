from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.api.routes import router
from app.core.config import get_settings
from app.db.session import get_db
from app.core.security import current_principal as authorize
from app.api.accounts import router as account_router
from app.api.gmail import router as gmail_router

app = FastAPI(title='Business Inbox AI Agent', version='1.2.0',
              description='Shared demonstration inbox and private Gmail integration with human-approved delivery.')
app.include_router(router, dependencies=[Depends(authorize)])
app.include_router(account_router)
app.include_router(gmail_router)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={'detail': 'Database unavailable; retry later'})


@app.get('/health')
def health(db=Depends(get_db)):
    db.execute(text('SELECT 1'))
    settings = get_settings()
    return {'status': 'ok', 'provider': settings.llm_provider,
            'sending_enabled': settings.gmail_send_enabled and settings.llm_provider == 'openai'}
