import pytest
import os
import uuid
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.db.session import Base, make_engine, get_db
from app.main import app
from scripts.seed_database import seed


@pytest.fixture
def db(tmp_path):
    url = os.getenv('TEST_DATABASE_URL')
    engine = make_engine(url or 'sqlite:///' + str(tmp_path / 'test.db'))
    schema = None
    if url:
        if engine.dialect.name != 'postgresql':
            raise ValueError('TEST_DATABASE_URL must be PostgreSQL; tests use an isolated schema')
        schema = 'inbox_test_' + uuid.uuid4().hex
        with engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA ' + schema))
        engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            seed(session)
            yield session
    finally:
        if schema:
            # schema consists only of a fixed test prefix and a generated UUID, never user input.
            with engine.begin() as connection:
                connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv('APP_API_TOKEN', 'test-token')
    monkeypatch.setenv('LLM_PROVIDER', 'demo')
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer test-token'
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def payload():
    return dict(sender='accounts@aisha.example', subject='Invoice INV-1042',
                body='Please check invoice INV-1042 for AED 3500 for Aisha Trading LLC.')


@pytest.fixture
def account_factory(db):
    from app.models import UserAccount
    from app.core.security import hash_password
    def create(username='owner', role='admin', password='correct-test-password-123'):
        user = UserAccount(username=username, display_name=username.title(), role=role,
                           password_hash=hash_password(password), active=True)
        db.add(user)
        db.commit()
        return user
    return create
