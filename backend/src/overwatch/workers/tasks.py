"""Detection job chain: ingest before → ingest after → detect → fuse (design doc §4, §5.6).

Transient errors (network/STAC) retry with exponential backoff; permanent failures
(no usable scene, coregistration mismatch) fail fast with a structured error on the
job row. JobTask.on_failure guarantees no job is left 'running' after a terminal crash.

`fuse` is the last link and the only one that leans on a third party we do not control, so
it is both removable (`FUSION_ENABLED`) and unable to fail the job behind it — see the note
above `_FUSION_RETRY`.
"""

import logging
from datetime import UTC, date, datetime
from typing import NoReturn

from celery import Task, chain
from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from overwatch.briefs.generator import (
    AnthropicBriefGenerator,
    BriefGenerator,
    PermanentBriefError,
    TransientBriefError,
)
from overwatch.briefs.loop import run_brief_loop
from overwatch.briefs.models import ArticleRow, BriefRequest, DetectionRow
from overwatch.briefs.validator import validate_brief
from overwatch.config import settings
from overwatch.db.aois import list_aois, stamp_checked
from overwatch.db.briefs import (
    detection_rows_for_pair,
    get_brief,
    mark_rejected,
    persist_validated,
)
from overwatch.db.briefs import mark_failed as mark_brief_failed
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
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
from overwatch.db.models import Aoi, Brief, Scene
from overwatch.db.news import articles_for_pair, replace_articles
from overwatch.db.scenes import upsert_scene
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.fusion.models import FusionWindow, GateResult, RawArticle
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.provider import (
    GdeltDocProvider,
    NewsProvider,
    TransientFusionError,
    build_query,
)
from overwatch.fusion.scorer import dedupe, score_article
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.gating import MIN_USABLE_FRACTION, find_usable_scene
from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.models import SceneMeta
from overwatch.imagery.provider import ImageryProvider
from overwatch.imagery.render import render_rgb_png
from overwatch.workers.celery_app import celery_app
from overwatch.workers.recheck import is_due, recheck_windows

logger = logging.getLogger(__name__)

BANDS: tuple[str, ...] = ("red", "green", "blue", "nir")


class TransientIngestError(Exception):
    """Network/STAC hiccup — safe to retry with backoff."""


class JobFailure(Exception):
    """Permanent failure; the structured error is already on the job row."""


def get_provider() -> ImageryProvider:
    """Module-level factory so tests can monkeypatch the provider."""
    return EarthSearchProvider()


def get_news_provider() -> NewsProvider:
    """Module-level factory so tests can monkeypatch the provider."""
    return GdeltDocProvider()


def dispatch_detection_job(job_id: str) -> None:
    signatures = [
        ingest_scene.si(job_id, "before"),
        ingest_scene.si(job_id, "after"),
        run_detection.si(job_id),
    ]
    # The kill-switch. Fusion is the only stage that depends on a third party we do not
    # control, so it must be removable without touching the pipeline that does the sensing.
    if settings.fusion_enabled:
        signatures.append(fuse.si(job_id))
    chain(*signatures).apply_async()


def dispatch_fusion_job(job_id: str) -> None:
    fuse.delay(job_id)


def _fail(job_id: str, code: str, message: str) -> NoReturn:
    with session_scope() as session:
        mark_failed(session, job_id, code=code, message=message)
    raise JobFailure(message)


class JobTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        if isinstance(exc, JobFailure):
            return  # already recorded structurally
        job_id = args[0] if args else kwargs.get("job_id")
        if job_id is None:
            return
        with session_scope() as session:
            mark_failed(
                session, job_id, code="task_failed", message=str(exc), detail={"task": self.name}
            )


_RETRY = {
    "base": JobTask,
    "bind": True,
    "autoretry_for": (TransientIngestError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
}


@celery_app.task(name="overwatch.ingest_scene", **_RETRY)
def ingest_scene(self: Task, job_id: str, which: str) -> None:
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None:
            raise JobFailure(f"job {job_id} not found")
        set_stage(session, job_id, f"ingest_{which}")
        record_attempt(session, job_id)
        aoi = session.get(Aoi, job.aoi_id)
        geometry = to_shape(aoi.geom)
        slug = aoi.slug
        window = job.params[which]
    start = date.fromisoformat(window["start"])
    end = date.fromisoformat(window["end"])
    try:
        selection = find_usable_scene(get_provider(), geometry, start, end, bands=BANDS)
    except Exception as exc:
        raise TransientIngestError(f"scene search/read failed: {exc}") from exc
    if selection is None:
        _fail(
            job_id,
            "no_usable_scene",
            f"no scene ≥{MIN_USABLE_FRACTION:.0%} usable in {start}..{end} after widening",
        )
    with session_scope() as session:
        scene_id = upsert_scene(
            session,
            selection.scene,
            slug,
            geometry,
            selection.usable_fraction,
            meta=selection.scene.model_dump(mode="json"),
        )
        set_scene(session, job_id, which, scene_id)
    # Write the console's true-colour PNG on the deterministic path, reusing the window the
    # gate already read (no second HTTPS fetch). Best-effort: a render failure must never
    # fail an otherwise-good ingestion — GET /scenes/{id}/image renders on demand instead.
    try:
        from overwatch.api.scenes import scene_image_path

        render_rgb_png(
            harmonize_window(selection.window, selection.scene),
            scene_image_path(slug, selection.scene.stac_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("job %s: scene PNG render failed (non-fatal): %s", job_id, exc)
    logger.info("job %s: %s scene %s (id=%s)", job_id, which, selection.scene.stac_id, scene_id)


@celery_app.task(name="overwatch.run_detection", **_RETRY)
def run_detection(self: Task, job_id: str) -> None:
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None or job.before_scene_id is None or job.after_scene_id is None:
            raise JobFailure(f"job {job_id} is missing ingested scenes")
        set_stage(session, job_id, "detect")
        record_attempt(session, job_id)
        aoi = session.get(Aoi, job.aoi_id)
        geometry = to_shape(aoi.geom)
        vertical = aoi.vertical
        aoi_id, before_id, after_id = job.aoi_id, job.before_scene_id, job.after_scene_id
        before_meta = SceneMeta.model_validate(session.get(Scene, before_id).meta)
        after_meta = SceneMeta.model_validate(session.get(Scene, after_id).meta)
    provider = get_provider()
    try:
        before = harmonize_window(provider.read_window(before_meta, geometry, BANDS), before_meta)
        after = harmonize_window(provider.read_window(after_meta, geometry, BANDS), after_meta)
    except Exception as exc:
        raise TransientIngestError(f"window re-read failed: {exc}") from exc
    try:
        detections = ClassicalChangeDetector().detect(before, after, VERTICAL_PRESETS[vertical])
    except ValueError as exc:
        _fail(job_id, "coregistration_error", str(exc))
    with session_scope() as session:
        count = replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job_id,
            before_scene_id=before_id,
            after_scene_id=after_id,
            detections=detections,
        )
        mark_succeeded(session, job_id, count)
    logger.info("job %s: %d detections persisted", job_id, count)


# Deliberately NOT `base: JobTask`. By the time fusion runs, ingestion and detection have
# already succeeded and `mark_succeeded` is on the job row — so `JobTask.on_failure`, which
# calls `mark_failed`, would let a GDELT outage reach back and flip a genuinely succeeded
# detection job to `failed`. A fusion failure must cost exactly one thing: a brief with no
# news section.
_FUSION_RETRY = {
    "bind": True,
    "autoretry_for": (TransientFusionError,),
    # Node-level floor, enforced by the worker's consumer ACROSS the whole prefork pool.
    # The provider's own throttle is per PROCESS, and Celery forks children (the first live
    # run's retries landed on ForkPoolWorker-7 and -8) — so two concurrent fuse tasks in two
    # children would each see a cold clock and fire at GDELT together. This is the only limit
    # that spans them. 10/m == one every 6 s, matching settings.gdelt_min_interval_s.
    "rate_limit": "10/m",
    # Backoff is tuned to GDELT, not to a generic 5xx. It documents 1 request / 5 s, and after
    # a burst it stays angry for ~75 s — so retries start at 15 s and escalate (15/30/60),
    # rather than the default 1 s that lands right back inside the limit.
    "retry_backoff": 15,
    "retry_backoff_max": 600,
    # NO jitter. Celery's jitter picks uniformly from [0, countdown], so it can retry SOONER
    # than the backoff intends — the first live run drew a literal "Retry in 0s". Jitter exists
    # to spread a thundering herd; we are one process behind one IP hitting a PER-IP limit, so
    # there is no herd to spread and retrying early is strictly worse.
    "retry_jitter": False,
    "max_retries": 3,
}

# Domain preference for syndication dedup — wires rank above the outlets that carry them.
_DOMAIN_RANK = [
    "reuters.com",
    "apnews.com",
    "bbc.co.uk",
    "thehindu.com",
    "thehindubusinessline.com",
    "news.mongabay.com",
    "riotimesonline.com",
    "usnews.com",
    "yahoo.com",
]


@celery_app.task(name="overwatch.fuse", **_FUSION_RETRY)
def fuse(self: Task, job_id: str) -> int:
    """Correlate news against this job's scene pair (Phase 5 design §6). Returns the count.

    Retrieval is GDELT-side and STRICT (the full-text place term). The three gates —
    toponym, temporal, thematic — are ours, pure, and ANDed, so an article must clear all
    three to be cited. Gate 1 is a TOPONYM gate, not a spatial one: GDELT exposes no
    article geotag, and its geocoder is centroid-based (design §2.4).
    """
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None or job.before_scene_id is None or job.after_scene_id is None:
            raise JobFailure(f"job {job_id} has no scene pair to anchor fusion on")
        aoi = session.get(Aoi, job.aoi_id)
        aoi_id, vertical, slug = aoi.id, aoi.vertical, aoi.slug
        place_terms = list(aoi.place_terms or [])
        region_terms = list(aoi.region_terms or [])
        before_id, after_id = job.before_scene_id, job.after_scene_id
        before_captured_at = session.get(Scene, before_id).captured_at
        after_captured_at = session.get(Scene, after_id).captured_at

    if not place_terms:
        logger.info("fusion skip %s: no place_terms configured on the AOI", slug)
        return 0

    preset = FUSION_PRESETS[vertical]
    # The CAPPED INTERVAL, anchored on BOTH scenes (design decision 3, revised). Anchoring
    # on the after-scene alone returned ZERO articles for the forest AOI on a live query:
    # coverage lands when the change happens, not when we got around to looking.
    window = FusionWindow.around(before_captured_at, after_captured_at, preset)
    query = build_query(place_terms[0], preset)  # STRICT term — full text, GDELT-side

    candidates = get_news_provider().search(query, window.start, window.end)

    scored: list[tuple[RawArticle, GateResult]] = []
    for candidate in candidates:
        gates = score_article(
            candidate,
            place_terms=place_terms,
            region_terms=region_terms,
            window=window,
            preset=preset,
            languages=settings.fusion_languages,
        )
        if gates.passed:
            scored.append((candidate, gates))

    # Dedup AFTER the gates: a syndicated copy that never passed them is not a duplicate to
    # suppress, it is an article we rejected outright.
    survivors = dedupe([article for article, _ in scored], domain_rank=_DOMAIN_RANK)
    gates_by_url = {article.url: gates for article, gates in scored}
    admitted = [
        (article, gates_by_url[article.url], suppressed, query) for article, suppressed in survivors
    ]

    with session_scope() as session:
        count = replace_articles(
            session,
            aoi_id=aoi_id,
            job_id=job_id,
            before_scene_id=before_id,
            after_scene_id=after_id,
            admitted=admitted,
        )
    logger.info(
        "job %s: %d/%d candidates admitted for %s (query=%s)",
        job_id,
        count,
        len(candidates),
        slug,
        query,
    )
    return count


class BriefTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        brief_id = args[0] if args else kwargs.get("brief_id")
        if brief_id is None:
            return
        with session_scope() as session:
            mark_brief_failed(session, brief_id, code="task_failed", message=str(exc))


_BRIEF_RETRY = {
    "base": BriefTask,
    "bind": True,
    "autoretry_for": (TransientBriefError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
}


def get_brief_generator() -> BriefGenerator:
    """Module-level factory so tests can monkeypatch the generator."""
    return AnthropicBriefGenerator()


def dispatch_brief(brief_id: int) -> None:
    generate_brief.delay(brief_id)


def _build_brief_request(session: Session, brief: Brief) -> BriefRequest:
    aoi = session.get(Aoi, brief.aoi_id)
    before_scene = session.get(Scene, brief.before_scene_id)
    after_scene = session.get(Scene, brief.after_scene_id)
    rows = detection_rows_for_pair(
        session,
        aoi_id=brief.aoi_id,
        before_scene_id=brief.before_scene_id,
        after_scene_id=brief.after_scene_id,
    )
    # Keyed on (aoi, after_scene) — the same replace-set key `replace_articles` writes
    # under. Empty when fusion is off or when no article cleared the three gates, and an
    # empty list simply renders no SOURCES block: the brief degrades to Phase 4 behavior.
    articles = articles_for_pair(session, aoi_id=brief.aoi_id, after_scene_id=brief.after_scene_id)
    return BriefRequest(
        aoi_name=aoi.name,
        aoi_slug=aoi.slug,
        vertical=aoi.vertical,
        before_scene_id=brief.before_scene_id,
        after_scene_id=brief.after_scene_id,
        before_date=before_scene.captured_at.date(),
        after_date=after_scene.captured_at.date(),
        detections=[
            DetectionRow(
                id=row.id,
                change_type=row.change_type,
                area_m2=row.area_m2,
                magnitude=row.magnitude,
                confidence=row.confidence,
            )
            for row in rows
        ],
        articles=[
            ArticleRow(
                id=a.id,
                title=a.title,
                domain=a.domain,
                # news_articles.seendate is a tz-aware DateTime; the prompt and the
                # validator both deal in calendar dates.
                seendate=a.seendate.date(),
            )
            for a in articles
        ],
    )


@celery_app.task(name="overwatch.generate_brief", **_BRIEF_RETRY)
def generate_brief(self: Task, brief_id: int) -> None:
    with session_scope() as session:
        brief = get_brief(session, brief_id)
        if brief is None or brief.status != "generating":
            return
        request = _build_brief_request(session, brief)
    try:
        result = run_brief_loop(
            get_brief_generator(),
            request,
            validate=validate_brief,
            max_attempts=settings.brief_max_attempts,
        )
    except PermanentBriefError as exc:
        with session_scope() as session:
            mark_brief_failed(session, brief_id, code=exc.code, message=str(exc))
        return
    # TransientBriefError propagates -> Celery autoretry; on exhaustion BriefTask.on_failure
    # marks the brief failed with code "task_failed".
    with session_scope() as session:
        if result.status == "validated":
            persist_validated(
                session,
                brief_id,
                headline=result.draft.headline,
                claims=[
                    (c.text, c.claim_type, c.evidence, c.article_evidence)
                    for c in result.draft.claims
                ],
                model=result.model,
                usage=result.usage,
                attempts=result.attempts,
                failures=[f.model_dump(mode="json") for f in result.failures],
            )
        else:
            mark_rejected(
                session,
                brief_id,
                failures=[f.model_dump(mode="json") for f in result.failures],
                attempts=result.attempts,
                model=result.model,
                usage=result.usage,
            )


@celery_app.task(name="overwatch.enqueue_due_rechecks")
def enqueue_due_rechecks() -> int:
    """Daily beat tick: submit a detection job per due AOI with a prior baseline."""
    now = datetime.now(UTC)
    submitted = 0
    with session_scope() as session:
        for aoi in list_aois(session):
            if not is_due(aoi.cadence_days, aoi.last_checked_at, now):
                continue
            baseline = latest_succeeded_job(session, aoi.id)
            if baseline is None:
                logger.info("recheck skip %s: no successful job to baseline from", aoi.slug)
                continue
            capture = session.get(Scene, baseline.after_scene_id).captured_at.date()
            windows = recheck_windows(capture, now.date())
            if windows is None:
                logger.info("recheck skip %s: baseline capture is today", aoi.slug)
                continue
            params = {
                "before": {
                    "start": windows.before[0].isoformat(),
                    "end": windows.before[1].isoformat(),
                },
                "after": {
                    "start": windows.after[0].isoformat(),
                    "end": windows.after[1].isoformat(),
                },
            }
            job = create_job(session, aoi.id, params)
            job_id = str(job.id)
            stamp_checked(session, aoi.id, now)
            session.commit()  # visible to the worker before dispatch
            dispatch_detection_job(job_id)
            submitted += 1
    return submitted
