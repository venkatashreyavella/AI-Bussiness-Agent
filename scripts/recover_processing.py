"""Recover interrupted runs only after all API workers have been stopped."""
import argparse
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import ProcessingRun, EmailMessage, utcnow


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers-stopped', action='store_true', required=True)
    parser.add_argument('--older-than-minutes', type=int, default=30)
    args = parser.parse_args()
    if args.older_than_minutes < 10:
        parser.error('Minimum age is 10 minutes')
    with SessionLocal() as db:
        runs = db.scalars(select(ProcessingRun).where(ProcessingRun.status == 'processing',
            ProcessingRun.created_at < datetime.now(timezone.utc) - timedelta(minutes=args.older_than_minutes))).all()
        for run in runs:
            run.status, run.error_code, run.finished_at = 'failed', 'interrupted', utcnow()
            db.get(EmailMessage, run.email_id).status = 'failed'
        db.commit()
        print(f'Recovered {len(runs)} interrupted runs; they can now be retried.')
