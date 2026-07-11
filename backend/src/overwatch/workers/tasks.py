"""Detection job chain: ingest before → ingest after → detect (design doc §4).

Transient errors (network/STAC) retry with exponential backoff; permanent failures
(no usable scene, coregistration mismatch) fail fast with a structured error on the
job row. JobTask.on_failure guarantees no job is left 'running' after a terminal crash.
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
from overwatch.briefs.models import BriefRequest, DetectionRow
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
from overwatch.db.scenes import upsert_scene
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.gating import MIN_USABLE_FRACTION, find_usable_scene
from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.models import SceneMeta
from overwatch.imagery.provider import ImageryProvider
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


def dispatch_detection_job(job_id: str) -> None:
    chain(
        ingest_scene.si(job_id, "before"),
        ingest_scene.si(job_id, "after"),
        run_detection.si(job_id),
    ).apply_async()


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
                claims=[(c.text, c.claim_type, c.evidence) for c in result.draft.claims],
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
