"""Job submission + polling (design doc §3). REST polling ~2 s; no WebSocket in v0.1."""

from uuid import UUID

from fastapi import APIRouter

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.api.schemas import JobOut, JobSubmit
from overwatch.db.jobs import create_job, get_job
from overwatch.db.models import Aoi
from overwatch.workers.tasks import dispatch_detection_job

router = APIRouter(tags=["jobs"])


@router.post("/aois/{slug}/jobs", status_code=202)
def submit_job(slug: str, payload: JobSubmit, session: SessionDep) -> dict[str, str]:
    aoi = require_aoi(session, slug)
    job = create_job(session, aoi.id, payload.model_dump(mode="json"))
    job_id = str(job.id)
    # Commit BEFORE dispatch: the worker reads this row from another process.
    session.commit()
    dispatch_detection_job(job_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JobOut)
def poll_job(job_id: UUID, session: SessionDep) -> JobOut:
    job = get_job(session, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", f"no job {job_id}")
    slug = session.get(Aoi, job.aoi_id).slug
    return JobOut(
        id=job.id,
        aoi_slug=slug,
        status=job.status,
        stage=job.stage,
        attempts=job.attempts,
        params=job.params,
        before_scene_id=job.before_scene_id,
        after_scene_id=job.after_scene_id,
        detection_count=job.detection_count,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
