"""Fusion backfill endpoint (Phase 5 design §6).

Fusion normally rides the detection chain. This endpoint exists to re-fuse an AOI whose
scenes are already ingested — after tuning `place_terms`, say, or after a GDELT outage let
the chain's `fuse` link fail. It re-uses the AOI's latest succeeded job rather than opening
a new one, because the articles it writes are keyed to that job's scene pair — the same
pair a brief is written over.

Guard order mirrors the brief endpoint's: the kill-switch is checked FIRST, so a server
with fusion disabled reports that plainly instead of leaking a 404, or a 409 about a
baseline it would never have used.
"""

from fastapi import APIRouter

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.config import settings
from overwatch.db.jobs import latest_succeeded_job
from overwatch.workers.tasks import dispatch_fusion_job

router = APIRouter(tags=["fusion"])


@router.post("/aois/{slug}/fusion", status_code=202)
def submit_fusion(slug: str, session: SessionDep) -> dict[str, str]:
    if not settings.fusion_enabled:
        raise ApiError(503, "fusion_disabled", "fusion is disabled on this server")
    aoi = require_aoi(session, slug)
    # No terms, no toponym gate — and Gate 1 is the only thing standing between this AOI
    # and every article that merely mentions its vertical. Refuse; never guess a place name.
    if not aoi.place_terms:
        raise ApiError(
            409,
            "fusion_unconfigured",
            f"AOI {slug!r} has no place_terms; fusion cannot be gated without them",
        )
    baseline = latest_succeeded_job(session, aoi.id)
    if baseline is None:
        raise ApiError(409, "no_baseline_run", f"no succeeded job for AOI {slug!r}")
    job_id = str(baseline.id)
    dispatch_fusion_job(job_id)
    return {"job_id": job_id}
