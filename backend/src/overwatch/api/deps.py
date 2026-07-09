"""FastAPI dependencies. Endpoints are sync `def` over the shared sync engine (design doc §1.4)."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from overwatch.db.engine import session_scope


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session
