"""SQLAlchemy engine/session plumbing. psycopg3 driver forced onto plain postgres URLs."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from overwatch.config import settings


def sqlalchemy_url(url: str) -> str:
    """Force the psycopg (v3) driver on plain postgresql:// URLs; leave others untouched."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(sqlalchemy_url(settings.database_url), pool_pre_ping=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session with commit-on-success, rollback-on-error semantics."""
    session = sessionmaker(bind=get_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
