"""Re-check due logic (pure) + the enqueue task."""

from datetime import UTC, date, datetime, timedelta

import pytest
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import get_aoi, upsert_aoi
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.models import SceneMeta
from overwatch.workers import tasks
from overwatch.workers.recheck import is_due, recheck_windows

NOW = datetime(2026, 7, 7, 3, 0, tzinfo=UTC)


def test_is_due_matrix() -> None:
    assert is_due(7, None, NOW) is True  # cadence set, never checked
    assert is_due(None, None, NOW) is False  # no cadence -> never due
    assert is_due(7, NOW - timedelta(days=8), NOW) is True
    assert is_due(7, NOW - timedelta(days=3), NOW) is False


def test_recheck_windows_shape() -> None:
    windows = recheck_windows(date(2026, 6, 20), date(2026, 7, 7))
    assert windows.before == (date(2026, 6, 20), date(2026, 6, 21))
    assert windows.after == (date(2026, 6, 21), date(2026, 7, 7))
    assert recheck_windows(date(2026, 7, 7), date(2026, 7, 7)) is None  # nothing newer possible


def test_enqueue_submits_only_for_due_aois_with_history(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_detection_job", dispatched.append)

    geom = box(0, 0, 0.01, 0.01)
    # due, with a successful prior job
    ready_id = upsert_aoi(
        db_session, slug="t3-rc-ready", name="R", vertical="forest", geometry=geom, cadence_days=7
    )
    meta = SceneMeta(
        stac_id="t3-rc-scene",
        collection="sentinel-2-l2a",
        captured_at=datetime(2026, 6, 20, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    scene_id = upsert_scene(db_session, meta, "t3-rc-ready", geom, 1.0)
    prior = create_job(db_session, ready_id, {})
    set_scene(db_session, prior.id, "after", scene_id)
    mark_succeeded(db_session, prior.id, detection_count=3)
    # due but no history -> skipped
    upsert_aoi(
        db_session, slug="t3-rc-bare", name="B", vertical="port", geometry=geom, cadence_days=7
    )
    # no cadence -> never due
    upsert_aoi(db_session, slug="t3-rc-off", name="O", vertical="flood", geometry=geom)
    db_session.commit()

    assert tasks.enqueue_due_rechecks() == 1
    assert len(dispatched) == 1

    db_session.expire_all()
    assert get_aoi(db_session, "t3-rc-ready").last_checked_at is not None
    assert get_aoi(db_session, "t3-rc-bare").last_checked_at is None

    assert tasks.enqueue_due_rechecks() == 0  # freshly stamped -> no longer due


def test_beat_schedule_registered() -> None:
    from overwatch.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["enqueue-due-rechecks"]
    assert entry["task"] == "overwatch.enqueue_due_rechecks"
