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
def clean_t3(migrated_db: None) -> Iterator[None]:
    """Delete Phase-3+ test rows (slug prefix t3-) after the test.

    Deleting aois first cascades jobs/detections and (Phase 4) briefs -> brief_claims
    -> evidence_links, since briefs.aoi_id is ondelete=CASCADE. scenes must be deleted
    last: briefs.before/after_scene_id are ondelete=NO ACTION, so a scene delete would
    fail while a brief still referenced it — by the time we get here, the aois delete
    has already cascaded those briefs away.
    """
    yield
    with session_scope() as session:
        session.execute(text("DELETE FROM aois WHERE slug LIKE 't3-%'"))
        session.execute(text("DELETE FROM scenes WHERE aoi_slug LIKE 't3-%'"))


@pytest.fixture()
def db_session(clean_t3: None) -> Iterator[Session]:
    """Function-scoped session over a migrated DB.

    Depends on clean_t3 so the cleanup DELETE always tears down AFTER this session
    commits — the reverse order deadlocks: the still-open transaction holds row locks
    the cleanup blocks on, while the commit waits for the cleanup to finish.
    """
    with session_scope() as session:
        yield session
