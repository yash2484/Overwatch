import datetime as dt

import pytest
from shapely.geometry import box
from sqlalchemy import delete, select

from overwatch.db.engine import session_scope
from overwatch.db.models import Scene
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.models import SceneMeta

TEST_SLUG = "test-idempotency"


@pytest.fixture()
def clean_rows(migrated_db):
    yield
    with session_scope() as s:
        s.execute(delete(Scene).where(Scene.aoi_slug == TEST_SLUG))


def _meta() -> SceneMeta:
    return SceneMeta(
        stac_id="S2B_43PGK_20240101_0_L2A_TEST",
        collection="sentinel-2-l2a",
        captured_at=dt.datetime(2024, 1, 1, 5, 30, tzinfo=dt.UTC),
        cloud_pct=12.5,
        epsg=32643,
        assets={"red": "https://example.com/B04.tif"},
    )


def test_upsert_twice_yields_one_row_with_updated_fields(clean_rows) -> None:
    geom = box(76.96, 8.355, 77.01, 8.395)
    with session_scope() as s:
        first_id = upsert_scene(s, _meta(), TEST_SLUG, geom, usable_fraction=0.85)
    with session_scope() as s:
        second_id = upsert_scene(s, _meta(), TEST_SLUG, geom, usable_fraction=0.91)
    assert first_id == second_id
    with session_scope() as s:
        rows = s.execute(select(Scene).where(Scene.aoi_slug == TEST_SLUG)).scalars().all()
        assert len(rows) == 1
        assert rows[0].usable_fraction == pytest.approx(0.91)
        assert rows[0].stac_id == "S2B_43PGK_20240101_0_L2A_TEST"
