"""generate_brief Celery task: happy-path validation, rejection, transient retry, permanent
failure (design spec §4, task 7). All retry-path assertions go through `task.apply()` —
calling a task directly sets `request.called_directly`, which makes Celery's `retry()` a
no-op and re-raise the original exception instead of retrying (see test_tasks.py for the
same rule applied to the job chain).
"""

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.briefs.generator import FakeBriefGenerator, PermanentBriefError, TransientBriefError
from overwatch.briefs.models import BriefDraft, ClaimDraft
from overwatch.db.aois import upsert_aoi
from overwatch.db.briefs import (
    claims_with_evidence,
    create_brief,
    detection_rows_for_pair,
    get_brief,
)
from overwatch.db.detections import replace_detections
from overwatch.db.jobs import create_job
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta
from overwatch.workers import tasks

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
AOI_SLUG = "t3-brieftask"
DET_AREA_M2 = 20_000.0

_scene_seq = itertools.count(1)


def _seed_scene(session: Session) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t3-brieftask-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=n),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, AOI_SLUG, AOI_GEOM, 1.0)


def _seed_brief(session: Session, *, n_detections: int = 1) -> tuple[int, list[int]]:
    """Seed AOI + 2 scenes + detections + a 'generating' brief row. Commits (the task's own
    session_scope() is a separate connection, so the row must be durable before .apply())."""
    aoi_id = upsert_aoi(
        session, slug=AOI_SLUG, name="Brief Task AOI", vertical="port", geometry=AOI_GEOM
    )
    before_id = _seed_scene(session)
    after_id = _seed_scene(session)
    job = create_job(session, aoi_id, {})
    dets = [
        Detection(
            geometry=box(76.91 + i * 0.01, 8.31, 76.915 + i * 0.01, 8.315),
            epsg=4326,
            area_m2=DET_AREA_M2,
            change_type=ChangeType.CONSTRUCTION,
            magnitude=0.5,
            confidence=0.9,
            contributing_indices={"ssim_dissim": 0.5},
        )
        for i in range(n_detections)
    ]
    replace_detections(
        session,
        aoi_id=aoi_id,
        job_id=str(job.id),
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=dets,
    )
    brief = create_brief(session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    session.flush()
    det_ids = [
        row.id
        for row in detection_rows_for_pair(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
    ]
    session.commit()
    return brief.id, det_ids


def test_happy_path_validates_first_try(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief_id, det_ids = _seed_brief(db_session, n_detections=1)
    draft = BriefDraft(
        headline="Construction activity detected at the port AOI.",
        claims=[
            ClaimDraft(
                text="New construction was observed within the AOI.",
                claim_type="observed",
                evidence=det_ids,
            )
        ],
    )
    generator = FakeBriefGenerator(drafts=[draft])
    monkeypatch.setattr(tasks, "get_brief_generator", lambda: generator)

    result = tasks.generate_brief.apply(args=(brief_id,))
    assert result.state == "SUCCESS"

    db_session.expire_all()
    brief = get_brief(db_session, brief_id)
    assert brief.status == "validated"
    assert brief.model == "fake"
    assert brief.attempts == 1
    assert brief.usage == {"input_tokens": 100, "output_tokens": 50}
    assert brief.headline == draft.headline
    assert brief.violations == []

    pairs = claims_with_evidence(db_session, brief_id)
    assert len(pairs) == 1
    claim, links = pairs[0]
    assert claim.claim_type == "observed"
    assert sorted(link.detection_id for link in links) == sorted(det_ids)


def test_rejection_after_max_attempts_records_three_unlinked_claim_violations(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief_id, _det_ids = _seed_brief(db_session, n_detections=1)
    # No evidence cited -> validate_brief (the real one) draws `unlinked_claim` every attempt.
    bad_draft = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Something changed.", claim_type="observed", evidence=[])],
    )
    generator = FakeBriefGenerator(drafts=[bad_draft, bad_draft, bad_draft])
    monkeypatch.setattr(tasks, "get_brief_generator", lambda: generator)

    result = tasks.generate_brief.apply(args=(brief_id,))
    assert result.state == "SUCCESS"

    db_session.expire_all()
    brief = get_brief(db_session, brief_id)
    assert brief.status == "rejected"
    assert brief.attempts == 3
    assert brief.headline is None
    assert len(brief.violations) == 3
    for attempt_record in brief.violations:
        codes = [v["code"] for v in attempt_record["violations"]]
        assert codes == ["unlinked_claim"]


def test_transient_error_retries_then_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenGenerator:
        def generate(self, request, failures):
            raise TransientBriefError("rate limited")

    brief_id, _det_ids = _seed_brief(db_session)
    monkeypatch.setattr(tasks, "get_brief_generator", lambda: BrokenGenerator())

    result = tasks.generate_brief.apply(args=(brief_id,))
    assert result.state == "FAILURE"
    assert isinstance(result.result, TransientBriefError)

    db_session.expire_all()
    brief = get_brief(db_session, brief_id)
    assert brief.status == "failed"
    assert brief.error["code"] == "task_failed"


def test_permanent_error_fails_fast_no_retry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0

    class AuthFailGenerator:
        def generate(self, request, failures):
            nonlocal call_count
            call_count += 1
            raise PermanentBriefError("anthropic_auth", "invalid api key")

    brief_id, _det_ids = _seed_brief(db_session)
    monkeypatch.setattr(tasks, "get_brief_generator", lambda: AuthFailGenerator())

    result = tasks.generate_brief.apply(args=(brief_id,))
    assert result.state == "SUCCESS"  # caught in-task, not a Celery-level failure
    assert call_count == 1  # no retries

    db_session.expire_all()
    brief = get_brief(db_session, brief_id)
    assert brief.status == "failed"
    assert brief.error["code"] == "anthropic_auth"
    assert brief.error["message"] == "invalid api key"


def test_skips_brief_not_in_generating_status(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A brief already resolved (e.g. re-delivered task message) is left untouched."""
    brief_id, _det_ids = _seed_brief(db_session)
    from overwatch.db.briefs import mark_failed

    with_db = db_session
    mark_failed(with_db, brief_id, code="already_done", message="pre-set")
    with_db.commit()

    def _boom() -> None:
        raise AssertionError("generator should not be called for a non-generating brief")

    monkeypatch.setattr(tasks, "get_brief_generator", _boom)

    result = tasks.generate_brief.apply(args=(brief_id,))
    assert result.state == "SUCCESS"

    db_session.expire_all()
    brief = get_brief(db_session, brief_id)
    assert brief.status == "failed"
    assert brief.error["code"] == "already_done"
