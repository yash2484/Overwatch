"""News-article repository — replace-set on (aoi, after_scene) + stale-brief flip (§5)."""

import itertools
from datetime import UTC, datetime, timedelta

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.briefs import create_brief
from overwatch.db.jobs import create_job
from overwatch.db.news import articles_for_pair, replace_articles
from overwatch.db.scenes import upsert_scene
from overwatch.fusion.models import GateResult, RawArticle
from overwatch.imagery.models import SceneMeta

AOI_GEOM = box(-55.50, -7.20, -55.30, -7.00)
AOI_SLUG = "t3-news"
QUERY = '"Novo Progresso" (theme:ENV_DEFORESTATION OR theme:ENV_FORESTRY)'

_scene_seq = itertools.count(1)


def _seed_scene(session: Session) -> int:
    n = next(_scene_seq)
    meta = SceneMeta(
        stac_id=f"t3-news-scene-{n}",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=n),
        cloud_pct=1.0,
        epsg=32721,
        assets={},
    )
    return upsert_scene(session, meta, AOI_SLUG, AOI_GEOM, 1.0)


def _seed_pair(session: Session) -> tuple[int, str, int, int]:
    aoi_id = upsert_aoi(
        session,
        slug=AOI_SLUG,
        name="News AOI",
        vertical="forest",
        geometry=AOI_GEOM,
        place_terms=["Novo Progresso"],
        region_terms=["Amazon"],
    )
    before_id = _seed_scene(session)
    after_id = _seed_scene(session)
    job = create_job(session, aoi_id, {})
    session.flush()
    return aoi_id, str(job.id), before_id, after_id


def _admitted(url: str, title: str = "Amazon deforestation report", suppressed=None):
    article = RawArticle(
        url=url,
        title=title,
        domain="news.mongabay.com",
        language="English",
        seendate=datetime(2023, 8, 11, tzinfo=UTC),
        socialimage="https://img/1.jpg",
        sourcecountry="Indonesia",  # publisher registration — NOT a geo signal
    )
    gates = GateResult(passed=True, toponym=["Amazon"], temporal=True, thematic=["deforest"])
    return (article, gates, suppressed or [], QUERY)


def test_replace_articles_persists_and_records_why_it_passed(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    n = replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://a.example/1")],
    )
    assert n == 1
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert len(rows) == 1
    # Every citation is auditable back to the terms that admitted it.
    assert rows[0].gates_passed["toponym"] == ["Amazon"]
    assert rows[0].gates_passed["thematic"] == ["deforest"]
    assert rows[0].query == QUERY
    # sourcecountry is carried for provenance only, in meta — never as geography.
    assert rows[0].meta["sourcecountry"] == "Indonesia"


def test_rerun_is_idempotent_zero_duplicates(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    args = {
        "aoi_id": aoi_id,
        "job_id": job_id,
        "before_scene_id": before_id,
        "after_scene_id": after_id,
        "admitted": [_admitted("https://a.example/1")],
    }
    replace_articles(db_session, **args)
    replace_articles(db_session, **args)
    assert len(articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)) == 1


def test_replace_set_drops_articles_that_no_longer_pass(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://a.example/1"), _admitted("https://a.example/2")],
    )
    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://a.example/2")],
    )
    urls = [r.url for r in articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)]
    assert urls == ["https://a.example/2"]


def test_suppressed_duplicates_are_visible_in_meta_not_silent(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://usnews.example/x", suppressed=["https://yahoo.example/x"])],
    )
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert rows[0].meta["duplicates"] == ["https://yahoo.example/x"]


def test_refusing_flips_validated_briefs_on_that_pair_to_stale(db_session: Session) -> None:
    """A validated brief citing articles must not keep a dangling article_id after a
    re-fusion replaces the article set. Same invariant as replace_detections.

    Sets the status directly rather than going through persist_validated: what is under
    test is replace_articles' stale flip, not the brief writer.
    """
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    brief = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id
    )
    brief.status = "validated"
    db_session.flush()

    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://a.example/1")],
    )
    db_session.refresh(brief)
    assert brief.status == "stale"


def test_refusing_does_not_touch_briefs_on_a_different_pair(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    other_after = _seed_scene(db_session)
    other = create_brief(
        db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=other_after
    )
    other.status = "validated"
    db_session.flush()

    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[_admitted("https://a.example/1")],
    )
    db_session.refresh(other)
    assert other.status == "validated"  # untouched — different pair


def test_articles_are_ordered_by_seendate(db_session: Session) -> None:
    aoi_id, job_id, before_id, after_id = _seed_pair(db_session)
    late, gates, _, q = _admitted("https://a.example/late")
    late = late.model_copy(update={"seendate": datetime(2023, 9, 7, tzinfo=UTC)})
    early, _, _, _ = _admitted("https://a.example/early")
    early = early.model_copy(update={"seendate": datetime(2023, 8, 4, tzinfo=UTC)})
    replace_articles(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        admitted=[(late, gates, [], q), (early, gates, [], q)],
    )
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert [r.url for r in rows] == ["https://a.example/early", "https://a.example/late"]
