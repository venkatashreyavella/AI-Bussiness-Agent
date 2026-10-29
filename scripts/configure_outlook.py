"""Prepare private Microsoft placeholders while preserving Gmail credentials and encryption."""
from pathlib import Path
from dotenv import dotenv_values, set_key
from scripts.configure_gmail import configure as configure_gmail


def configure():
    configure_gmail()
    path = Path('.env')
    values = dotenv_values(path)
    public = Path('artifacts/public-dashboard-url.txt')
    redirect = public.read_text(encoding='utf-8').strip().rstrip('/') + '/' if public.exists() else 'http://127.0.0.1:8501/'
    defaults = {'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'MICROSOFT_TENANT': 'common',
                'MICROSOFT_REDIRECT_URI': redirect, 'OUTLOOK_SEND_ENABLED': 'false'}
    for name, value in defaults.items():
        if name not in values:
            set_key(str(path), name, value, quote_mode='auto')
    Path('artifacts/outlook-setup-checklist.txt').write_text(
        'Outlook activation checklist\n\nRegister this exact Microsoft Web redirect URI:\n' +
        (values.get('MICROSOFT_REDIRECT_URI') or redirect) +
        '\n\n1. Register a Microsoft Entra app for personal and work/school accounts.\n'
        '2. Add delegated User.Read, Mail.Read and Mail.Send permissions.\n'
        '3. Put the client ID and client secret VALUE in private .env.\n'
        '4. Configure live OpenAI, then restart the app.\n'
        '5. Sign in, open Outlook, connect and review Microsoft consent yourself.\n'
        '6. Sync messages; enable OUTLOOK_SEND_ENABLED only when ready for reviewed sending.\n'
        '\nKeep .env and TOKEN_ENCRYPTION_KEY private. See OUTLOOK_SETUP.md.\n', encoding='utf-8')
    print('Private Outlook placeholders configured. See artifacts/outlook-setup-checklist.txt and OUTLOOK_SETUP.md.')


if __name__ == '__main__':
    configure()
