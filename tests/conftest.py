"""Pytest configuration and test database fixtures."""

from collections.abc import Generator
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
import app.models  # noqa: F401 - ensure all models are registered


@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine for fast unit and model testing."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return test_engine


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """Function-scoped database session with clean table states."""
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_test_key_provider():
    """Ensures test key provider state is isolated and reset across all test functions."""
    from app.merchant_keys import clear_test_merchant_keys
    clear_test_merchant_keys()
    yield
    clear_test_merchant_keys()
