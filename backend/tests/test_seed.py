"""Showcase seeder is idempotent."""

from sqlalchemy.orm import Session

from overwatch.aois import SHOWCASE_AOIS
from overwatch.db.aois import get_aoi
from overwatch.db.seed import seed


def test_seed_twice_yields_three_stable_rows(db_session: Session) -> None:
    first = seed()
    second = seed()
    assert first == second
    assert len(first) == len(SHOWCASE_AOIS) == 3
    db_session.expire_all()
    for slug, aoi in SHOWCASE_AOIS.items():
        row = get_aoi(db_session, slug)
        assert row is not None and row.vertical == aoi.vertical
