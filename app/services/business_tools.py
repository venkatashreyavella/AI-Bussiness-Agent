import hashlib
from pydantic import Field
from sqlalchemy import select, or_
from app.models import Customer, Invoice, Order, ToolExecutionLog
from app.schemas import StrictModel


class SearchCustomerArgs(StrictModel):
    customer_name_or_email: str = Field(min_length=1, max_length=200)


class InvoiceArgs(StrictModel):
    invoice_number: str = Field(pattern=r'^[A-Za-z0-9-]{1,80}$')


class OrderArgs(StrictModel):
    order_number: str = Field(pattern=r'^[A-Za-z0-9-]{1,80}$')


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=200)


ARGUMENTS = {'search_customer': SearchCustomerArgs, 'get_invoice_status': InvoiceArgs,
             'get_order_status': OrderArgs, 'search_business_records': SearchArgs}
TOOLS = [dict(type='function', name=name, description=description, strict=True,
              parameters=ARGUMENTS[name].model_json_schema()) for name, description in [
    ('search_customer', 'Find fictional business customers by name or email.'),
    ('get_invoice_status', 'Retrieve verified invoice amount, currency, due date and status.'),
    ('get_order_status', 'Retrieve verified order status and description.'),
    ('search_business_records', 'Search customers, invoice numbers and order numbers.')]]


class BusinessTools:
    def __init__(self, db, run_id=None):
        self.db, self.run_id = db, run_id
        self.evidence = []

    def search_customer(self, customer_name_or_email):
        rows = self.db.scalars(select(Customer).where(or_(Customer.name.icontains(customer_name_or_email, autoescape=True),
                                                        Customer.email.icontains(customer_name_or_email, autoescape=True))).limit(10)).all()
        return [{'name': r.name, 'email': r.email, 'fictional': r.fictional} for r in rows]

    def get_invoice_status(self, invoice_number):
        row = self.db.scalar(select(Invoice).where(Invoice.number == invoice_number.upper()))
        if not row:
            return []
        return [{'invoice_number': row.number, 'amount': str(row.amount), 'currency': row.currency,
                 'due_date': row.due_date.isoformat(), 'status': row.status, 'source': 'database', 'fictional': True}]

    def get_order_status(self, order_number):
        row = self.db.scalar(select(Order).where(Order.number == order_number.upper()))
        return [{'order_number': row.number, 'status': row.status, 'description': row.description,
                 'source': 'database', 'fictional': True}] if row else []

    def search_business_records(self, query):
        invoices = self.db.scalars(select(Invoice).where(Invoice.number.icontains(query, autoescape=True)).limit(10)).all()
        orders = self.db.scalars(select(Order).where(Order.number.icontains(query, autoescape=True)).limit(10)).all()
        return self.search_customer(query) + [{'invoice_number': i.number} for i in invoices] + [{'order_number': o.number} for o in orders]

    def execute(self, name, arguments):
        args = {}
        try:
            schema = ARGUMENTS.get(name)
            if schema is None:
                raise ValueError('Tool not allowed')
            args = schema.model_validate(arguments).model_dump()
            # Nested transaction keeps an individual SQL failure from poisoning the audit transaction.
            with self.db.begin_nested():
                records = getattr(self, name)(**args)
            outcome = {'records': records, 'found': bool(records)}
            status = 'success'
        except Exception:
            outcome, status = {'error': 'Tool unavailable or arguments invalid', 'records': [], 'found': False}, 'error'
        self.evidence.append({'tool': name, 'status': status, **outcome})
        if self.run_id:
            # Hash customer/search arguments to avoid recording arbitrary email text or personal data.
            safe = {k: (v if k in {'invoice_number', 'order_number'} else hashlib.sha256(str(v).encode()).hexdigest())
                    for k, v in args.items()}
            self.db.add(ToolExecutionLog(run_id=self.run_id, name=name[:80], arguments=safe, status=status, outcome=outcome))
        return outcome
