"""Create private local demo settings only when .env does not already exist."""
import secrets
from pathlib import Path
from scripts.configure_dashboard import configure

path = Path('.env')
if path.exists():
    print('.env already exists; preserved existing settings.')
else:
    path.write_text('DATABASE_URL=sqlite:///./inbox.db\nLLM_PROVIDER=demo\nOPENAI_API_KEY=\nOPENAI_MODEL=\n'
                    'APP_API_TOKEN=' + secrets.token_urlsafe(32) + '\nAPI_BASE_URL=http://127.0.0.1:8000\nSAMPLE_DUE_DATE=2026-11-30\n', encoding='utf-8')
    print('Created private .env for offline local demonstration. Token is loaded automatically by the dashboard.')

configure()
