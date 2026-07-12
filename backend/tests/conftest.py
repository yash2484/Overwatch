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


# Every prefix the test suite seeds under. A prefix missing from this list is a slow leak:
# its rows are never cleaned, they pile up in the shared dev database, and `list_aois` (the
# beat task's due-recheck sweep) will eventually iterate over them as if they were real.
_TEST_SLUG_PREFIXES = ("t3-", "t5-")


@pytest.fixture()
def clean_t3(migrated_db: None) -> Iterator[None]:
    """Delete Phase-3+ test rows (slug prefixes in `_TEST_SLUG_PREFIXES`) after the test.

    Deleting aois first cascades jobs/detections and (Phase 4) briefs -> brief_claims
    -> evidence_links, since briefs.aoi_id is ondelete=CASCADE. (Phase 5) news_articles
    cascade the same way. scenes must be deleted last: briefs.before/after_scene_id are
    ondelete=NO ACTION, so a scene delete would fail while a brief still referenced it —
    by the time we get here, the aois delete has already cascaded those briefs away.
    """
    yield
    with session_scope() as session:
        for prefix in _TEST_SLUG_PREFIXES:
            session.execute(text("DELETE FROM aois WHERE slug LIKE :p"), {"p": f"{prefix}%"})
            session.execute(text("DELETE FROM scenes WHERE aoi_slug LIKE :p"), {"p": f"{prefix}%"})


@pytest.fixture()
def db_session(clean_t3: None) -> Iterator[Session]:
    """Function-scoped session over a migrated DB.

    Depends on clean_t3 so the cleanup DELETE always tears down AFTER this session
    commits — the reverse order deadlocks: the still-open transaction holds row locks
    the cleanup blocks on, while the commit waits for the cleanup to finish.
    """
    with session_scope() as session:
        yield session
