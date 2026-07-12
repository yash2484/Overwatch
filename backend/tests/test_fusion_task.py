"""The `fuse` Celery task: chain wiring, the FUSION_ENABLED kill-switch, and the funnel
from GDELT candidates to persisted rows (Phase 5 design §6).

No network. The provider is monkeypatched to `FakeNewsProvider`, replaying the recorded
GDELT artlist fixture — CI never touches GDELT.

The scene pair here is the REAL Vizhinjam pair (2021-02-12 -> 2025-02-11, a 1,460-day
gap), not invented dates. That makes the capped-interval window (design decision 3,
revised) do real work: the 400-day cap turns a four-year baseline into a ~14-month news
window, which still admits the June-2024 coverage sitting ~8 months before the after
scene. The after-scene-anchored window this replaced would have rejected every one of
these articles, so these tests are the regression guard on that correction.
"""

import itertools
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.news import articles_for_pair
from overwatch.db.scenes import upsert_scene
from overwatch.fusion.provider import FakeNewsProvider
from overwatch.imagery.models import SceneMeta
from overwatch.workers import tasks

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
AOI_SLUG = "t5-fuse"

# The real Vizhinjam scene pair (design §2 spike, and the handover's window table).
BEFORE_CAPTURED = datetime(2021, 2, 12, tzinfo=UTC)
AFTER_CAPTURED = datetime(2025, 2, 11, tzinfo=UTC)

JOB_UUID = "00000000-0000-0000-0000-000000000000"

_scene_seq = itertools.count(1)


def _fake_provider() -> FakeNewsProvider:
    body = json.loads((FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8"))
    return FakeNewsProvider.from_artlist(body)


def _seed_scene(session: Session, captured_at: datetime) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t5-fuse-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=captured_at,
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, AOI_SLUG, AOI_GEOM, 1.0)


def _seed_job(
    session: Session,
    *,
    place_terms: list[str] | None,
    region_terms: list[str] | None = None,
    vertical: str = "port",
) -> tuple[str, int, int]:
    """AOI + the real scene pair + a succeeded job. Commits, because `fuse` opens its own
    `session_scope()` on a separate connection and will not see uncommitted rows."""
    aoi_id = upsert_aoi(
        session,
        slug=AOI_SLUG,
        name="Vizhinjam International Seaport",
        vertical=vertical,
        geometry=AOI_GEOM,
        place_terms=place_terms,
        region_terms=region_terms,
    )
    before_id = _seed_scene(session, BEFORE_CAPTURED)
    after_id = _seed_scene(session, AFTER_CAPTURED)
    job = create_job(session, aoi_id, {})
    job_id = str(job.id)
    set_scene(session, job_id, "before", before_id)
    set_scene(session, job_id, "after", after_id)
    mark_succeeded(session, job_id, 0)
    session.commit()
    return job_id, aoi_id, after_id


# --- the kill-switch ---------------------------------------------------------------


def _capture_chain(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    class _FakeChain:
        def __init__(self, *signatures) -> None:
            captured["tasks"] = [s.task for s in signatures]

        def apply_async(self) -> None:
            captured["applied"] = True

    monkeypatch.setattr(tasks, "chain", _FakeChain)
    return captured


def test_chain_includes_fuse_when_fusion_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks.settings, "fusion_enabled", True)
    captured = _capture_chain(monkeypatch)

    tasks.dispatch_detection_job(JOB_UUID)

    assert captured["applied"] is True
    # Asserting the task NAMES, not just the count: a chain of the right length built from
    # the wrong signatures would pass a length check.
    assert captured["tasks"] == [
        "overwatch.ingest_scene",
        "overwatch.ingest_scene",
        "overwatch.run_detection",
        "overwatch.fuse",
    ]


def test_chain_excludes_fuse_when_fusion_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks.settings, "fusion_enabled", False)
    captured = _capture_chain(monkeypatch)

    tasks.dispatch_detection_job(JOB_UUID)

    assert captured["applied"] is True
    assert captured["tasks"] == [
        "overwatch.ingest_scene",
        "overwatch.ingest_scene",
        "overwatch.run_detection",
    ]
    assert "overwatch.fuse" not in captured["tasks"]


# --- the funnel --------------------------------------------------------------------


def test_fuse_persists_only_gate_passing_articles(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four candidates in, three rows out: the Malayalam article fails the language
    precondition. The three survivors clear all three gates and land auditable."""
    job_id, aoi_id, after_id = _seed_job(
        db_session,
        place_terms=["Vizhinjam"],
        region_terms=["Thiruvananthapuram", "Kerala"],
    )
    monkeypatch.setattr(tasks, "get_news_provider", _fake_provider)

    result = tasks.fuse.apply(args=(job_id,))
    assert result.state == "SUCCESS"
    assert result.result == 3

    db_session.expire_all()
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)

    assert len(rows) == 3
    assert {row.language for row in rows} == {"English"}
    assert "mathrubhumi.com" not in {row.domain for row in rows}
    assert any("Customs grants approval" in row.title for row in rows)

    # Every citation is auditable: the row records which terms and keywords admitted it,
    # and the query that retrieved it.
    for row in rows:
        assert "Vizhinjam" in row.gates_passed["toponym"]
        assert row.gates_passed["temporal"] is True
        assert row.gates_passed["thematic"]
        assert "Vizhinjam" in row.query

    # These stories sit ~8 months BEFORE the after scene. Under the after-scene-anchored
    # window that the capped interval replaced, every one of them would have been rejected
    # as out-of-window and this AOI would have shipped with no news section at all.
    assert all((AFTER_CAPTURED - row.seendate).days > 200 for row in rows)


def test_fuse_is_idempotent_on_a_re_run(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # replace-set semantics: re-fusing the same pair rewrites identical rows, never doubles.
    job_id, aoi_id, after_id = _seed_job(db_session, place_terms=["Vizhinjam"])
    monkeypatch.setattr(tasks, "get_news_provider", _fake_provider)

    assert tasks.fuse.apply(args=(job_id,)).result == 3
    assert tasks.fuse.apply(args=(job_id,)).result == 3

    db_session.expire_all()
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert len(rows) == 3
    assert len({row.url for row in rows}) == 3


def test_fuse_is_a_noop_when_the_aoi_has_no_place_terms(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An AOI with no terms cannot be gated. Skip it and say so — never guess a toponym."""
    job_id, aoi_id, after_id = _seed_job(db_session, place_terms=None)

    def _boom() -> None:
        raise AssertionError("the provider must not be called for an AOI with no place_terms")

    monkeypatch.setattr(tasks, "get_news_provider", _boom)

    with caplog.at_level(logging.INFO, logger="overwatch.workers.tasks"):
        result = tasks.fuse.apply(args=(job_id,))

    assert result.state == "SUCCESS"
    assert result.result == 0
    assert "no place_terms" in caplog.text
    assert articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id) == []


def test_fuse_retry_policy_is_configured() -> None:
    from overwatch.fusion.provider import TransientFusionError

    assert TransientFusionError in tasks.fuse.autoretry_for
    assert tasks.fuse.max_retries == 3
    assert tasks.fuse.retry_backoff is True
