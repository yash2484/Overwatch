"""Replace-set idempotency + ST_Intersects / since / change_type filters."""

from datetime import UTC, date, datetime

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import query_detections, replace_detections
from overwatch.db.jobs import create_job
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)


def _fixture_ids(session: Session) -> tuple[int, str, int, int]:
    aoi_id = upsert_aoi(session, slug="t3-det", name="D", vertical="port", geometry=AOI_GEOM)
    scene_ids = []
    for stac_id, day in (("t3-det-before", 10), ("t3-det-after", 20)):
        meta = SceneMeta(
            stac_id=stac_id,
            collection="sentinel-2-l2a",
            captured_at=datetime(2024, 6, day, tzinfo=UTC),
            cloud_pct=1.0,
            epsg=32643,
            assets={},
        )
        scene_ids.append(upsert_scene(session, meta, "t3-det", AOI_GEOM, 1.0))
    job = create_job(session, aoi_id, {})
    return aoi_id, str(job.id), scene_ids[0], scene_ids[1]


def _detection(lonlat_box: tuple[float, float, float, float]) -> Detection:
    # epsg=4326 keeps the test geometry in lon/lat directly (to_wgs84 no-ops)
    return Detection(
        geometry=box(*lonlat_box),
        epsg=4326,
        area_m2=20_000.0,
        change_type=ChangeType.CONSTRUCTION,
        magnitude=0.5,
        confidence=0.9,
        contributing_indices={"ssim_dissim": 0.5},
    )


def test_replace_set_is_idempotent(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _fixture_ids(db_session)
    dets = [_detection((76.97, 8.36, 76.99, 8.38)), _detection((77.00, 8.40, 77.02, 8.42))]
    kwargs = {
        "aoi_id": aoi_id,
        "job_id": job_id,
        "before_scene_id": before_id,
        "after_scene_id": after_id,
    }
    assert replace_detections(db_session, detections=dets, **kwargs) == 2
    assert replace_detections(db_session, detections=dets, **kwargs) == 2
    assert len(query_detections(db_session, aoi_id)) == 2  # not 4


def test_spatial_and_attribute_filters(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _fixture_ids(db_session)
    replace_detections(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=[_detection((76.97, 8.36, 76.99, 8.38))],
    )
    hit = query_detections(db_session, aoi_id, intersects=box(76.98, 8.37, 77.00, 8.39))
    miss = query_detections(db_session, aoi_id, intersects=box(75.0, 7.0, 75.1, 7.1))
    assert len(hit) == 1 and len(miss) == 0

    # since: after scene captured 2024-06-20
    assert len(query_detections(db_session, aoi_id, since=date(2024, 6, 1))) == 1
    assert len(query_detections(db_session, aoi_id, since=date(2024, 7, 1))) == 0

    assert len(query_detections(db_session, aoi_id, change_type="construction")) == 1
    assert len(query_detections(db_session, aoi_id, change_type="flooding")) == 0
