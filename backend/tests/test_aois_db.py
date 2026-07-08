"""AOI repository: idempotent upsert, get/list/delete, cascade."""

from datetime import UTC, datetime

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import delete_aoi, get_aoi, list_aois, stamp_checked, upsert_aoi

GEOM = box(76.96, 8.35, 77.01, 8.40)


def test_upsert_is_idempotent_on_slug(db_session: Session, clean_t3: None) -> None:
    first = upsert_aoi(db_session, slug="t3-up", name="A", vertical="port", geometry=GEOM)
    second = upsert_aoi(db_session, slug="t3-up", name="A2", vertical="port", geometry=GEOM)
    assert first == second
    assert get_aoi(db_session, "t3-up").name == "A2"


def test_upsert_does_not_clobber_cadence(db_session: Session, clean_t3: None) -> None:
    aoi_id = upsert_aoi(
        db_session, slug="t3-cad", name="C", vertical="forest", geometry=GEOM, cadence_days=7
    )
    stamp_checked(db_session, aoi_id, datetime(2026, 7, 1, tzinfo=UTC))
    upsert_aoi(db_session, slug="t3-cad", name="C", vertical="forest", geometry=GEOM)
    row = get_aoi(db_session, "t3-cad")
    assert row.cadence_days == 7
    assert row.last_checked_at is not None


def test_get_list_delete(db_session: Session, clean_t3: None) -> None:
    upsert_aoi(db_session, slug="t3-del", name="D", vertical="flood", geometry=GEOM)
    assert any(a.slug == "t3-del" for a in list_aois(db_session))
    assert delete_aoi(db_session, "t3-del") is True
    assert get_aoi(db_session, "t3-del") is None
    assert delete_aoi(db_session, "t3-del") is False
