"""Job rows: lifecycle transitions, attempts counter, latest-succeeded lookup."""

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.jobs import (
    create_job,
    get_job,
    latest_succeeded_job,
    mark_failed,
    mark_succeeded,
    record_attempt,
    set_scene,
    set_stage,
)

PARAMS = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def _aoi(session: Session, slug: str = "t3-job") -> int:
    return upsert_aoi(session, slug=slug, name="J", vertical="port", geometry=box(0, 0, 0.01, 0.01))


def test_lifecycle_to_succeeded(db_session: Session, clean_t3: None) -> None:
    aoi_id = _aoi(db_session)
    job = create_job(db_session, aoi_id, PARAMS)
    assert job.status == "queued" and job.attempts == 0 and job.params == PARAMS

    set_stage(db_session, job.id, "ingest_before")
    record_attempt(db_session, job.id)
    db_session.expire_all()
    row = get_job(db_session, str(job.id))
    assert row.status == "running" and row.stage == "ingest_before" and row.attempts == 1

    mark_succeeded(db_session, job.id, detection_count=9)
    db_session.expire_all()
    row = get_job(db_session, job.id)
    assert row.status == "succeeded" and row.detection_count == 9 and row.error is None


def test_mark_failed_records_structured_error(db_session: Session, clean_t3: None) -> None:
    job = create_job(db_session, _aoi(db_session), PARAMS)
    mark_failed(db_session, job.id, code="no_usable_scene", message="nope", detail={"w": 1})
    db_session.expire_all()
    row = get_job(db_session, job.id)
    assert row.status == "failed"
    assert row.error == {"code": "no_usable_scene", "message": "nope", "detail": {"w": 1}}


def test_latest_succeeded_requires_after_scene(db_session: Session, clean_t3: None) -> None:
    aoi_id = _aoi(db_session)
    first = create_job(db_session, aoi_id, PARAMS)
    mark_succeeded(db_session, first.id, detection_count=0)  # no after scene recorded
    assert latest_succeeded_job(db_session, aoi_id) is None

    second = create_job(db_session, aoi_id, PARAMS)
    set_scene(db_session, second.id, "after", _scene_id(db_session))
    mark_succeeded(db_session, second.id, detection_count=1)
    assert latest_succeeded_job(db_session, aoi_id).id == second.id


def _scene_id(session: Session) -> int:
    from datetime import UTC, datetime

    from shapely.geometry import box as _box

    from overwatch.db.scenes import upsert_scene
    from overwatch.imagery.models import SceneMeta

    meta = SceneMeta(
        stac_id="t3-scene-jobs",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 6, 10, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, "t3-job", _box(0, 0, 0.01, 0.01), 1.0)
