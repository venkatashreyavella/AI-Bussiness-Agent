"""Add private Gmail configuration placeholders and an encryption key without exposing secrets."""
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


def configure():
    path = Path('.env')
    if not path.exists():
        raise SystemExit('Create the private .env first using scripts.configure_local')
    values = dotenv_values(path)
    key = values.get('TOKEN_ENCRYPTION_KEY') or Fernet.generate_key().decode()
    Fernet(key.encode())  # never silently replace an existing key that protects saved credentials
    public_url = Path('artifacts/public-dashboard-url.txt')
    redirect = public_url.read_text().strip().rstrip('/') + '/' if public_url.exists() else 'http://127.0.0.1:8501/'
    defaults = {'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'GOOGLE_REDIRECT_URI': redirect,
                'TOKEN_ENCRYPTION_KEY': key, 'GMAIL_SEND_ENABLED': 'false'}
    for name, value in defaults.items():
        if name not in values:
            set_key(str(path), name, value, quote_mode='auto')
    output = Path('artifacts/gmail-setup-checklist.txt')
    output.parent.mkdir(exist_ok=True)
    output.write_text('Gmail activation checklist\n\nRegister this exact Google OAuth redirect URI:\n' +
        (values.get('GOOGLE_REDIRECT_URI') or redirect) + '\n\n1. Enable Gmail API in Google Cloud.\n'
        '2. Configure an External OAuth consent screen in Testing; add your Gmail as a test user.\n'
        '3. Create a Web application OAuth client using the redirect above.\n'
        '4. Put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET into the private .env.\n'
        '5. Put OPENAI_API_KEY and OPENAI_MODEL into .env, and set LLM_PROVIDER=openai.\n'
        '6. Restart API/dashboard, sign in, open Gmail, and click Connect my Gmail.\n'
        '7. After reviewing Gmail permissions, sync messages and review a draft.\n'
        '8. Enable GMAIL_SEND_ENABLED=true only when ready to send explicitly approved replies.\n\n'
        'Keep .env and TOKEN_ENCRYPTION_KEY private. Do not paste secrets into chat or GitHub.\n', encoding='utf-8')
    print('Private Gmail placeholders and encryption key configured. See artifacts/gmail-setup-checklist.txt and GMAIL_SETUP.md.')


if __name__ == '__main__':
    configure()
