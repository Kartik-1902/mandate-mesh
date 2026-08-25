"""Database engine, session management, and declarative Base."""

from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


# Sync engine for migrations, standard transactions & CLI
connect_args = {"check_same_thread": False} if settings.DATABASE_URL_SYNC.startswith("sqlite") else {}
engine = create_engine(
    settings.DATABASE_URL_SYNC,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    """Returns a new SQLAlchemy Session."""
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI / task dependency providing a scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
