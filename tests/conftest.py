import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.welcomepage_user import Base
from app import app, get_db
from fastapi.testclient import TestClient

# Use a test database URL (set this in your environment or hardcode for local dev)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test_test.db")
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    # Create tables before any tests
    Base.metadata.create_all(bind=engine)
    yield
    # Drop tables after all tests
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db, monkeypatch):
    # Override get_db dependency to use the test DB
    def override_get_db():
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides = {}
