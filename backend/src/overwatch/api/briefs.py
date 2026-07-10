"""Brief submit/poll/latest endpoints (Phase 4 design §3).

Guard order on submit matters: unknown AOI (404) is checked before the Anthropic key
(422), which is checked before the baseline-job lookup (409) — an unconfigured server
should never leak a 409 about a missing baseline before it reports its own missing key.
"""

from fastapi import APIRouter
from sqlalchemy.orm import Session

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.api.schemas import BriefOut, BriefSubmit, ClaimOut
from overwatch.config import settings
from overwatch.db.briefs import (
    claims_with_evidence,
    create_brief,
    get_brief,
    latest_validated_brief,
)
from overwatch.db.jobs import latest_succeeded_job
from overwatch.db.models import Aoi, Brief
from overwatch.workers.tasks import dispatch_brief

router = APIRouter(tags=["briefs"])


def _to_brief_out(session: Session, brief: Brief) -> BriefOut:
    slug = session.get(Aoi, brief.aoi_id).slug
    claims: list[ClaimOut] = []
    if brief.status in ("validated", "stale"):
        for claim, links in claims_with_evidence(session, brief.id):
            claims.append(
                ClaimOut(
                    seq=claim.seq,
                    text=claim.text,
                    claim_type=claim.claim_type,
                    detection_ids=[
                        link.detection_id for link in links if link.detection_id is not None
                    ],
                )
            )
    return BriefOut(
        id=brief.id,
        aoi_slug=slug,
        status=brief.status,
        attempts=brief.attempts,
        headline=brief.headline,
        model=brief.model,
        usage=brief.usage,
        violations=brief.violations,
        error=brief.error,
        before_scene_id=brief.before_scene_id,
        after_scene_id=brief.after_scene_id,
        claims=claims,
        created_at=brief.created_at,
        updated_at=brief.updated_at,
    )


@router.post("/aois/{slug}/briefs", status_code=202)
def submit_brief(slug: str, payload: BriefSubmit, session: SessionDep) -> dict[str, int]:
    aoi = require_aoi(session, slug)
    if not settings.anthropic_api_key:
        raise ApiError(422, "briefs_unconfigured", "server has no Anthropic API key configured")
    if payload.before_scene_id is not None and payload.after_scene_id is not None:
        before_scene_id, after_scene_id = payload.before_scene_id, payload.after_scene_id
    else:
        baseline = latest_succeeded_job(session, aoi.id)
        if baseline is None:
            raise ApiError(409, "no_baseline_run", f"no succeeded job for AOI {slug!r}")
        before_scene_id, after_scene_id = baseline.before_scene_id, baseline.after_scene_id
    brief = create_brief(
        session, aoi_id=aoi.id, before_scene_id=before_scene_id, after_scene_id=after_scene_id
    )
    brief_id = brief.id
    # Commit BEFORE dispatch: the worker reads this row from another process.
    session.commit()
    dispatch_brief(brief_id)
    return {"brief_id": brief_id}


@router.get("/briefs/{brief_id}", response_model=BriefOut)
def poll_brief(brief_id: int, session: SessionDep) -> BriefOut:
    brief = get_brief(session, brief_id)
    if brief is None:
        raise ApiError(404, "brief_not_found", f"no brief {brief_id}")
    return _to_brief_out(session, brief)


@router.get("/aois/{slug}/brief", response_model=BriefOut)
def latest_brief(slug: str, session: SessionDep) -> BriefOut:
    aoi = require_aoi(session, slug)
    brief = latest_validated_brief(session, aoi.id)
    if brief is None:
        raise ApiError(404, "no_validated_brief", f"no validated brief for AOI {slug!r}")
    return _to_brief_out(session, brief)
