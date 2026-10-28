"""Create the first owner only for an empty account database; never reset existing accounts."""
import os
from sqlalchemy import select, func, text
from app.db.session import SessionLocal
from app.models import UserAccount
from app.core.security import hash_password
from app.schemas.accounts import AccountCreate


def bootstrap(db):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(48105001)'))
    if db.scalar(select(func.count()).select_from(UserAccount)):
        print('Existing user accounts preserved.')
        return
    data = AccountCreate(username=os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'owner'), display_name='Workspace owner',
                         password=os.getenv('DASHBOARD_PASSWORD', ''), role='admin')
    db.add(UserAccount(username=data.username, display_name=data.display_name, role='admin', active=True,
                       password_hash=hash_password(data.password)))
    db.commit()
    print(f'Administrator account created: {data.username}. Use your existing dashboard password for the first sign-in.')


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    with SessionLocal() as db:
        bootstrap(db)
