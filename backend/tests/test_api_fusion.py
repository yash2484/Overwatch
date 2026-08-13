"""POST /aois/{slug}/fusion — the backfill endpoint and its guards (Phase 5 design §6).

The guard ORDER is under test as much as the guards are. The kill-switch is checked first,
so a server with fusion disabled says exactly that, rather than leaking a 404 or a 409
about a baseline it would never have used. Same discipline as the Phase-4 brief endpoint,
where the missing-key check precedes the baseline lookup.
"""

import itertools
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.api import fusion as fusion_module
from overwatch.api.main import app
from overwatch.db.aois import upsert_aoi
from overwatch.db.engine import session_scope
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.models import SceneMeta

client = TestClient(app)
AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
GHOST_SLUG = "t5-ghost-fusion"

_scene_seq = itertools.count(1)


def _seed_scene(session: Session, slug: str) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t5-api-fusion-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, slug, AOI_GEOM, 1.0)


def _seed_aoi(session: Session, slug: str, *, place_terms: list[str] | None) -> int:
    return upsert_aoi(
        session,
        slug=slug,
        name="Fusion AOI",
        vertical="port",
        geometry=AOI_GEOM,
        place_terms=place_terms,
    )


def _seed_succeeded_job(session: Session, aoi_id: int, slug: str) -> str:
    before_id = _seed_scene(session, slug)
    after_id = _seed_scene(session, slug)
    job = create_job(session, aoi_id, {})
    set_scene(session, job.id, "before", before_id)
    set_scene(session, job.id, "after", after_id)
    mark_succeeded(session, job.id, 0)
    return str(job.id)


def test_fusion_disabled_returns_503_before_any_other_guard(
    clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fusion_module.settings, "fusion_enabled", False)

    # The slug does not exist. If the kill-switch were checked after `require_aoi`, this
    # would come back 404 — which is precisely the leak the guard order exists to prevent.
    resp = client.post(f"/aois/{GHOST_SLUG}/fusion")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "fusion_disabled"


def test_unknown_aoi_returns_404(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fusion_module.settings, "fusion_enabled", True)

    resp = client.post(f"/aois/{GHOST_SLUG}/fusion")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "aoi_not_found"


def test_aoi_without_place_terms_returns_409(
    clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No terms, no toponym gate. Refuse rather than guess a place name for the AOI."""
    monkeypatch.setattr(fusion_module.settings, "fusion_enabled", True)
    slug = "t5-api-fusion-noterms"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug, place_terms=None)
        # A baseline DOES exist here: the terms are the only thing missing, so this test
        # cannot pass by accidentally tripping the no_baseline_run guard instead.
        _seed_succeeded_job(session, aoi_id, slug)

    resp = client.post(f"/aois/{slug}/fusion")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "fusion_unconfigured"


def test_aoi_without_a_succeeded_job_returns_409(
    clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fusion_module.settings, "fusion_enabled", True)
    slug = "t5-api-fusion-nobaseline"
    with session_scope() as session:
        _seed_aoi(session, slug, place_terms=["Vizhinjam"])  # terms present, no job

    resp = client.post(f"/aois/{slug}/fusion")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_baseline_run"


def test_happy_path_returns_202_and_dispatches_the_baseline_job(
    clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fusion_module.settings, "fusion_enabled", True)
    dispatched: list[str] = []
    monkeypatch.setattr(fusion_module, "dispatch_fusion_job", dispatched.append)

    slug = "t5-api-fusion-ok"
    with session_scope() as session:
        aoi_id = _seed_aoi(session, slug, place_terms=["Vizhinjam"])
        job_id = _seed_succeeded_job(session, aoi_id, slug)

    resp = client.post(f"/aois/{slug}/fusion")

    assert resp.status_code == 202
    assert resp.json() == {"job_id": job_id}
    # Fusion re-uses the baseline job rather than opening a new one: the articles it writes
    # are keyed to that job's scene pair, which is the pair a brief will be written over.
    assert dispatched == [job_id]
