"""Deterministic, idempotent FICTIONAL records only; migrations must already be applied."""
from datetime import date
from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Customer, Invoice, Order


def seed(db):
    customer = db.scalar(select(Customer).where(Customer.email == 'accounts@aisha.example'))
    if not customer:
        customer = Customer(name='Aisha Trading LLC', email='accounts@aisha.example', fictional=True)
        db.add(customer)
        db.flush()
    if not db.scalar(select(Invoice).where(Invoice.number == 'INV-1042')):
        db.add(Invoice(customer_id=customer.id, number='INV-1042', amount=3500, currency='AED',
                       due_date=date.fromisoformat(get_settings().sample_due_date), status='Pending'))
    if not db.scalar(select(Order).where(Order.number == 'ORD-2041')):
        db.add(Order(customer_id=customer.id, number='ORD-2041', status='Processing', description='Fictional office supplies'))
    db.commit()


if __name__ == '__main__':
    with SessionLocal() as db:
        seed(db)
    print('Fictional demonstration data seeded.')
