from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from overwatch.db.engine import session_scope

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Bring the test database to head. Requires a reachable PostGIS (compose or CI service)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture()
def db_session(migrated_db: None) -> Iterator[Session]:
    with session_scope() as session:
        yield session


@pytest.fixture()
def clean_t3(migrated_db: None) -> Iterator[None]:
    """Delete Phase-3 test rows (slug prefix t3-) after the test; cascades jobs/detections."""
    yield
    with session_scope() as session:
        session.execute(text("DELETE FROM aois WHERE slug LIKE 't3-%'"))
        session.execute(text("DELETE FROM scenes WHERE aoi_slug LIKE 't3-%'"))
