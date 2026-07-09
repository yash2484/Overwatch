"""Job state — durable in Postgres, polled via the API (design doc §2)."""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from overwatch.db.models import Job


def create_job(session: Session, aoi_id: int, params: dict[str, Any]) -> Job:
    job = Job(id=uuid.uuid4(), aoi_id=aoi_id, status="queued", params=params, attempts=0)
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: str | uuid.UUID) -> Job | None:
    return session.get(Job, uuid.UUID(str(job_id)))


def _update(session: Session, job_id: str | uuid.UUID, **values: Any) -> None:
    values["updated_at"] = func.now()
    session.execute(update(Job).where(Job.id == uuid.UUID(str(job_id))).values(**values))


def set_stage(session: Session, job_id: str | uuid.UUID, stage: str) -> None:
    _update(session, job_id, stage=stage, status="running")


def record_attempt(session: Session, job_id: str | uuid.UUID) -> None:
    _update(session, job_id, attempts=Job.attempts + 1)


def set_scene(session: Session, job_id: str | uuid.UUID, which: str, scene_id: int) -> None:
    if which not in ("before", "after"):
        raise ValueError(f"which must be 'before' or 'after', got {which!r}")
    _update(session, job_id, **{f"{which}_scene_id": scene_id})


def mark_succeeded(session: Session, job_id: str | uuid.UUID, detection_count: int) -> None:
    _update(session, job_id, status="succeeded", detection_count=detection_count, error=None)


def mark_failed(
    session: Session, job_id: str | uuid.UUID, *, code: str, message: str, detail: Any = None
) -> None:
    _update(
        session, job_id, status="failed", error={"code": code, "message": message, "detail": detail}
    )


def latest_succeeded_job(session: Session, aoi_id: int) -> Job | None:
    """Most recent succeeded job that recorded an after scene (re-check baseline)."""
    return session.scalar(
        select(Job)
        .where(Job.aoi_id == aoi_id, Job.status == "succeeded", Job.after_scene_id.is_not(None))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
