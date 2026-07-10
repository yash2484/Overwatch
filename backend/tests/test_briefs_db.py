"""Brief repository — persistence + staleness on detection replace-set (design spec §2)."""

import itertools
from datetime import UTC, datetime, timedelta

from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.briefs import (
    claims_with_evidence,
    create_brief,
    get_brief,
    latest_validated_brief,
    mark_rejected,
    persist_validated,
)
from overwatch.db.detections import replace_detections
from overwatch.db.jobs import create_job
from overwatch.db.models import DetectionEvent
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
AOI_SLUG = "t3-brief"

_scene_seq = itertools.count(1)


def _seed_pair(session: Session) -> tuple[int, int, int]:
    aoi_id = upsert_aoi(
        session, slug=AOI_SLUG, name="Brief AOI", vertical="port", geometry=AOI_GEOM
    )
    before_id = _seed_scene(session, aoi_id)
    after_id = _seed_scene(session, aoi_id)
    return aoi_id, before_id, after_id


def _seed_scene(session: Session, aoi_id: int) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t3-brief-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=n),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, AOI_SLUG, AOI_GEOM, 1.0)


def _seed_job(session: Session, aoi_id: int) -> str:
    job = create_job(session, aoi_id, {})
    return str(job.id)


def _detection(i: int) -> Detection:
    lo = 76.91 + i * 0.01
    return Detection(
        geometry=box(lo, 8.31, lo + 0.005, 8.315),
        epsg=4326,
        area_m2=20_000.0,
        change_type=ChangeType.CONSTRUCTION,
        magnitude=0.5,
        confidence=0.9,
        contributing_indices={"ssim_dissim": 0.5},
    )


def _seed_detections(
    session: Session, aoi_id: int, before_id: int, after_id: int, n: int
) -> list[int]:
    job_id = _seed_job(session, aoi_id)
    dets = [_detection(i) for i in range(n)]
    replace_detections(
        session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=dets,
    )
    session.flush()
    return list(
        session.scalars(
            select(DetectionEvent.id).where(
                DetectionEvent.aoi_id == aoi_id,
                DetectionEvent.before_scene_id == before_id,
                DetectionEvent.after_scene_id == after_id,
            )
        )
    )


def test_create_and_get_brief(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    brief = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    assert brief.status == "generating" and brief.attempts == 0
    assert get_brief(db_session, brief.id).id == brief.id
    assert get_brief(db_session, 999_999) is None


def test_persist_validated_writes_claims_and_links(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    det_ids = _seed_detections(db_session, aoi_id, before_id, after_id, n=2)
    brief = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    persist_validated(
        db_session,
        brief.id,
        headline="H",
        claims=[("obs claim", "observed", det_ids), ("ctx claim", "context", [])],
        model="claude-opus-4-8",
        usage={"input_tokens": 10, "output_tokens": 5},
        attempts=1,
        failures=[],
    )
    got = get_brief(db_session, brief.id)
    assert got.status == "validated" and got.headline == "H"
    pairs = claims_with_evidence(db_session, brief.id)
    assert [c.seq for c, _ in pairs] == [0, 1]
    assert sorted(link.detection_id for link in pairs[0][1]) == sorted(det_ids)
    assert pairs[1][1] == []


def test_latest_validated_brief_skips_non_validated(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    rejected = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    mark_rejected(
        db_session, rejected.id, failures=[{"violations": []}], attempts=3, model="m", usage={}
    )
    old = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    persist_validated(
        db_session,
        old.id,
        headline="old",
        claims=[("c", "context", [])],
        model="m",
        usage={},
        attempts=1,
        failures=[],
    )
    new = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    persist_validated(
        db_session,
        new.id,
        headline="new",
        claims=[("c", "context", [])],
        model="m",
        usage={},
        attempts=1,
        failures=[],
    )
    assert latest_validated_brief(db_session, aoi_id).id == new.id


def test_replace_detections_marks_validated_briefs_stale(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    det_ids = _seed_detections(db_session, aoi_id, before_id, after_id, n=1)
    brief = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    persist_validated(
        db_session,
        brief.id,
        headline="H",
        claims=[("c", "observed", det_ids)],
        model="m",
        usage={},
        attempts=1,
        failures=[],
    )
    job_id = _seed_job(db_session, aoi_id)
    replace_detections(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=[],
    )
    assert get_brief(db_session, brief.id).status == "stale"
    # evidence links cascade away with the deleted detections
    assert claims_with_evidence(db_session, brief.id)[0][1] == []


def test_replace_detections_leaves_other_pairs_and_statuses_alone(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    other_before, other_after = _seed_scene(db_session, aoi_id), _seed_scene(db_session, aoi_id)
    rejected_same_pair = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    mark_rejected(db_session, rejected_same_pair.id, failures=[], attempts=3, model="m", usage={})
    validated_other_pair = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=other_before, after_scene_id=other_after
    )
    persist_validated(
        db_session,
        validated_other_pair.id,
        headline="H",
        claims=[("c", "context", [])],
        model="m",
        usage={},
        attempts=1,
        failures=[],
    )
    job_id = _seed_job(db_session, aoi_id)
    replace_detections(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=[],
    )
    assert get_brief(db_session, rejected_same_pair.id).status == "rejected"
    assert get_brief(db_session, validated_other_pair.id).status == "validated"
