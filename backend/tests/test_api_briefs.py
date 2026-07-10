"""Brief submit/poll/latest endpoints with guards (Phase 4 design §3)."""

import itertools
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box
from sqlalchemy import select

from overwatch.api import briefs as briefs_module
from overwatch.api.main import app
from overwatch.db.aois import upsert_aoi
from overwatch.db.briefs import create_brief, mark_rejected, persist_validated
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.models import DetectionEvent
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

client = TestClient(app)
AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)

_scene_seq = itertools.count(1)


def _seed_aoi(session, slug: str) -> int:
    return upsert_aoi(session, slug=slug, name="B", vertical="port", geometry=AOI_GEOM)


def _seed_scene(session, slug: str) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t3-api-brief-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, slug, AOI_GEOM, 1.0)


def _seed_succeeded_job(session, aoi_id: int, before_id: int, after_id: int) -> None:
    job = create_job(session, aoi_id, {})
    set_scene(session, job.id, "before", before_id)
    set_scene(session, job.id, "after", after_id)
    mark_succeeded(session, job.id, 0)


def _seed_detection_ids(session, aoi_id: int, before_id: int, after_id: int) -> list[int]:
    job = create_job(session, aoi_id, {})
    replace_detections(
        session,
        aoi_id=aoi_id,
        job_id=job.id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=[
            Detection(
                geometry=box(76.97, 8.36, 76.99, 8.38),
                epsg=4326,
                area_m2=20_000.0,
                change_type=ChangeType.CONSTRUCTION,
                magnitude=0.5,
                confidence=0.9,
                contributing_indices={"ssim_dissim": 0.5},
            )
        ],
    )
    return list(
        session.scalars(
            select(DetectionEvent.id).where(
                DetectionEvent.aoi_id == aoi_id,
                DetectionEvent.before_scene_id == before_id,
                DetectionEvent.after_scene_id == after_id,
            )
        )
    )


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


def test_submit_defaults_to_latest_succeeded_job(
    clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", "test-key")
    dispatched: list[int] = []
    monkeypatch.setattr(briefs_module, "dispatch_brief", dispatched.append)

    slug = "t3-api-brief-def"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        _seed_succeeded_job(session, aoi_id, before_id, after_id)

    resp = client.post(f"/aois/{slug}/briefs", json={})
    assert resp.status_code == 202
    brief_id = resp.json()["brief_id"]
    assert dispatched == [brief_id]

    polled = client.get(f"/briefs/{brief_id}")
    assert polled.status_code == 200
    body = polled.json()
    assert body["before_scene_id"] == before_id
    assert body["after_scene_id"] == after_id
    assert body["status"] == "generating"
    assert body["claims"] == []


def test_submit_explicit_pair_honored(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(briefs_module, "dispatch_brief", lambda _: None)

    slug = "t3-api-brief-explicit"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        other_before = _seed_scene(session, slug)
        other_after = _seed_scene(session, slug)
        _seed_succeeded_job(session, aoi_id, before_id, after_id)

    resp = client.post(
        f"/aois/{slug}/briefs",
        json={"before_scene_id": other_before, "after_scene_id": other_after},
    )
    assert resp.status_code == 202
    brief_id = resp.json()["brief_id"]

    polled = client.get(f"/briefs/{brief_id}").json()
    assert polled["before_scene_id"] == other_before
    assert polled["after_scene_id"] == other_after


def test_submit_no_baseline_409(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", "test-key")
    slug = "t3-api-brief-nobaseline"
    with session_scope() as session:
        _seed_aoi(session, slug)

    resp = client.post(f"/aois/{slug}/briefs", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_baseline_run"


def test_submit_unconfigured_422(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", None)
    slug = "t3-api-brief-unconf"
    with session_scope() as session:
        _seed_aoi(session, slug)

    resp = client.post(f"/aois/{slug}/briefs", json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "briefs_unconfigured"


def test_submit_unknown_aoi_404(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", "test-key")
    resp = client.post("/aois/t3-ghost-brief/briefs", json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "aoi_not_found"


def test_submit_guard_order_404_before_422(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown AOI + unset key must still surface aoi_not_found, not briefs_unconfigured."""
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", None)
    resp = client.post("/aois/t3-ghost-brief-2/briefs", json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "aoi_not_found"


def test_submit_guard_order_422_before_409(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Known AOI, unset key, no baseline job: must surface briefs_unconfigured, not
    no_baseline_run — the key check runs before the baseline lookup."""
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", None)
    slug = "t3-api-brief-order"
    with session_scope() as session:
        _seed_aoi(session, slug)

    resp = client.post(f"/aois/{slug}/briefs", json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "briefs_unconfigured"


def test_submit_one_scene_id_422(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefs_module.settings, "anthropic_api_key", "test-key")
    slug = "t3-api-brief-oneid"
    with session_scope() as session:
        _seed_aoi(session, slug)

    resp = client.post(f"/aois/{slug}/briefs", json={"before_scene_id": 1})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"

    resp2 = client.post(f"/aois/{slug}/briefs", json={"after_scene_id": 1})
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


def test_poll_validated_brief_returns_claims(clean_t3: None) -> None:
    slug = "t3-api-brief-poll"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        det_ids = _seed_detection_ids(session, aoi_id, before_id, after_id)
        brief = create_brief(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
        brief_id = brief.id
        persist_validated(
            session,
            brief_id,
            headline="New construction detected",
            claims=[
                ("Construction observed", "observed", det_ids),
                ("Context note", "context", []),
            ],
            model="claude-opus-4-8",
            usage={"input_tokens": 10, "output_tokens": 5},
            attempts=1,
            failures=[],
        )

    resp = client.get(f"/briefs/{brief_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "validated"
    assert body["headline"] == "New construction detected"
    assert body["aoi_slug"] == slug
    assert body["model"] == "claude-opus-4-8"
    assert body["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert len(body["claims"]) == 2
    assert body["claims"][0] == {
        "seq": 0,
        "text": "Construction observed",
        "claim_type": "observed",
        "detection_ids": det_ids,
    }
    assert body["claims"][1]["detection_ids"] == []


def test_poll_rejected_brief_exposes_violations_and_empty_claims(clean_t3: None) -> None:
    slug = "t3-api-brief-rejected"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        brief = create_brief(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
        brief_id = brief.id
        failures = [{"claim_index": 0, "violation": "unsupported_claim"}]
        mark_rejected(
            session, brief_id, failures=failures, attempts=3, model="claude-opus-4-8", usage={}
        )

    resp = client.get(f"/briefs/{brief_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["violations"] == failures
    assert body["claims"] == []


def test_poll_unknown_brief_404(clean_t3: None) -> None:
    resp = client.get("/briefs/999999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "brief_not_found"


# ---------------------------------------------------------------------------
# latest
# ---------------------------------------------------------------------------


def test_latest_returns_newest_validated(clean_t3: None) -> None:
    slug = "t3-api-brief-latest"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        old = create_brief(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
        persist_validated(
            session,
            old.id,
            headline="old",
            claims=[("c", "context", [])],
            model="m",
            usage={},
            attempts=1,
            failures=[],
        )
        new = create_brief(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
        persist_validated(
            session,
            new.id,
            headline="new",
            claims=[("c", "context", [])],
            model="m",
            usage={},
            attempts=1,
            failures=[],
        )
        new_id = new.id

    resp = client.get(f"/aois/{slug}/brief")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == new_id
    assert body["headline"] == "new"


def test_latest_no_validated_404(clean_t3: None) -> None:
    slug = "t3-api-brief-noval"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug)
        before_id = _seed_scene(session, slug)
        after_id = _seed_scene(session, slug)
        brief = create_brief(
            session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
        )
        mark_rejected(session, brief.id, failures=[], attempts=3, model="m", usage={})

    resp = client.get(f"/aois/{slug}/brief")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "no_validated_brief"


def test_latest_unknown_aoi_404(clean_t3: None) -> None:
    resp = client.get("/aois/t3-ghost-brief-latest/brief")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "aoi_not_found"
