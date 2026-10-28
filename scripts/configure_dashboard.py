"""Generate a private dashboard password without printing it or changing API credentials."""
import secrets
from pathlib import Path
from dotenv import dotenv_values


def configure():
    path = Path('.env')
    if not path.exists():
        raise SystemExit('Configure .env first; see README.')
    values = dotenv_values(path)
    password = values.get('DASHBOARD_PASSWORD')
    username = values.get('BOOTSTRAP_ADMIN_USERNAME') or 'owner'
    if not password:
        password = secrets.token_urlsafe(24)
        with path.open('a', encoding='utf-8') as file:
            file.write('\nDASHBOARD_PASSWORD=' + password + '\n')
    if len(password) < 16:
        raise SystemExit('DASHBOARD_PASSWORD must have at least 16 characters.')
    output = Path('artifacts/dashboard-access.txt')
    output.parent.mkdir(exist_ok=True)
    output.write_text('Business Inbox dashboard access\n\nLocal URL: http://127.0.0.1:8501\n'
                      'Username: ' + username + '\nInitial owner password: ' + password +
                      '\n\nThis is the bootstrap credential. If you changed your account password, use the newer password.\n'
                      'Keep this file private. Internet URL is shown in the chat or docker compose logs tunnel.\n', encoding='utf-8')
    print('Dashboard password configured. Private credentials saved to artifacts/dashboard-access.txt (not printed).')


if __name__ == '__main__':
    configure()
