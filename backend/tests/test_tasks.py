"""Chain tasks over a fake provider: happy path, idempotent re-run, failure modes."""

from datetime import UTC, datetime

import pytest
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import query_detections
from overwatch.db.jobs import create_job, get_job
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.workers import tasks
from tests.synthetic import BARE, FOREST, SCL_CLOUD_HIGH, flat_window, inject_rect

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
PARAMS = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def _meta(stac_id: str, when: datetime) -> SceneMeta:
    return SceneMeta(
        stac_id=stac_id,
        collection="sentinel-2-l2a",
        captured_at=when,
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )


class FakeProvider:
    def __init__(self, scenes: list[SceneMeta], windows: dict[str, AOIWindow]) -> None:
        self.scenes, self.windows = scenes, windows

    def search_scenes(self, geometry, start, end, *, max_cloud_pct):
        return [s for s in self.scenes if start <= s.captured_at.date() < end]

    def read_window(self, scene, geometry, bands):
        return self.windows[scene.stac_id]


def _forest_pair() -> FakeProvider:
    before = flat_window(FOREST)
    after = flat_window(FOREST)
    inject_rect(after, BARE, (20, 60, 20, 60))  # 400m x 400m clearing = 160,000 m2
    return FakeProvider(
        scenes=[
            _meta("t3-fk-before", datetime(2024, 1, 10, tzinfo=UTC)),
            _meta("t3-fk-after", datetime(2024, 6, 10, tzinfo=UTC)),
        ],
        windows={"t3-fk-before": before, "t3-fk-after": after},
    )


def _job(session: Session, vertical: str = "forest") -> tuple[int, str]:
    aoi_id = upsert_aoi(session, slug="t3-task", name="T", vertical=vertical, geometry=AOI_GEOM)
    job = create_job(session, aoi_id, PARAMS)
    session.commit()
    return aoi_id, str(job.id)


def test_full_chain_persists_detections_idempotently(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _forest_pair()
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    aoi_id, job_id = _job(db_session)

    tasks.ingest_scene(job_id, "before")
    tasks.ingest_scene(job_id, "after")
    tasks.run_detection(job_id)

    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "succeeded"
    assert job.before_scene_id is not None and job.after_scene_id is not None
    assert job.detection_count >= 1 and job.attempts == 3  # one per stage

    rows = query_detections(db_session, aoi_id)
    assert len(rows) == job.detection_count
    # synthetic grid sits near UTM 43N (500km E, 1000km N) -> about lon 75, lat 9
    assert len(query_detections(db_session, aoi_id, intersects=box(74.5, 8.5, 75.5, 9.5))) >= 1

    tasks.run_detection(job_id)  # re-run: replace-set, zero duplicates
    db_session.expire_all()
    assert len(query_detections(db_session, aoi_id)) == len(rows)


def test_no_usable_scene_fails_fast_with_structured_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloudy = flat_window(FOREST, scl_class=SCL_CLOUD_HIGH)  # usable fraction 0
    provider = FakeProvider(
        scenes=[_meta("t3-fk-cloud", datetime(2024, 1, 10, tzinfo=UTC))],
        windows={"t3-fk-cloud": cloudy},
    )
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    _, job_id = _job(db_session)

    with pytest.raises(tasks.JobFailure):
        tasks.ingest_scene(job_id, "before")
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "failed" and job.error["code"] == "no_usable_scene"


def test_network_error_retries_visibly_then_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transient errors burn all retries (attempts 1 -> 4), then land a structured failure.

    Must go through .apply(): calling a task directly sets request.called_directly, and
    Celery's retry() then re-raises the original exception instead of retrying at all.
    """

    class BrokenProvider:
        def search_scenes(self, *args, **kwargs):
            raise ConnectionError("stac unreachable")

        def read_window(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError

    monkeypatch.setattr(tasks, "get_provider", lambda: BrokenProvider())
    _, job_id = _job(db_session)

    result = tasks.ingest_scene.apply(args=(job_id, "before"))
    assert result.state == "FAILURE"
    assert isinstance(result.result, tasks.TransientIngestError)

    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.attempts == 4  # 1 initial + max_retries(3) — retries are visible while polling
    assert job.status == "failed" and job.error["code"] == "task_failed"


def test_transient_error_called_directly_does_not_mark_failed(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct call raises the transient error without touching terminal job state."""

    class BrokenProvider:
        def search_scenes(self, *args, **kwargs):
            raise ConnectionError("stac unreachable")

        def read_window(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError

    monkeypatch.setattr(tasks, "get_provider", lambda: BrokenProvider())
    _, job_id = _job(db_session)

    with pytest.raises(tasks.TransientIngestError):
        tasks.ingest_scene(job_id, "before")
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "running" and job.attempts == 1  # not failed — no on_failure hook ran


def test_retry_policy_is_configured() -> None:
    for task in (tasks.ingest_scene, tasks.run_detection):
        assert tasks.TransientIngestError in task.autoretry_for
        assert task.max_retries == 3
        assert task.retry_backoff is True


def test_on_failure_marks_job_failed(db_session: Session) -> None:
    _, job_id = _job(db_session)
    tasks.ingest_scene.on_failure(RuntimeError("boom"), "tid", (job_id, "before"), {}, None)
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "failed" and job.error["code"] == "task_failed"
