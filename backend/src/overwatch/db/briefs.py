"""Brief persistence — briefs/brief_claims/evidence_links (Phase 4 design §2).

Every claim a brief makes must trace to a real stored detection row: `persist_validated`
writes one `EvidenceLink(evidence_type="detection")` per detection id a claim cites.
`mark_stale_briefs` is called from `replace_detections`' transaction so a re-run of a
detection job demotes any `validated` brief over that exact scene pair to `stale` before
the underlying detections it cited are deleted.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from overwatch.db.models import Brief, BriefClaim, DetectionEvent, EvidenceLink


def create_brief(
    session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int
) -> Brief:
    brief = Brief(
        aoi_id=aoi_id,
        before_scene_id=before_scene_id,
        after_scene_id=after_scene_id,
        status="generating",
        attempts=0,
        usage={},
    )
    session.add(brief)
    session.flush()
    return brief


def get_brief(session: Session, brief_id: int) -> Brief | None:
    return session.get(Brief, brief_id)


def latest_validated_brief(session: Session, aoi_id: int) -> Brief | None:
    # Secondary sort on id: Postgres' func.now() returns the *transaction* start time,
    # so briefs created inside the same transaction (e.g. in tests) can share an
    # identical created_at; id DESC breaks the tie deterministically by insertion order.
    return session.scalar(
        select(Brief)
        .where(Brief.aoi_id == aoi_id, Brief.status == "validated")
        .order_by(Brief.created_at.desc(), Brief.id.desc())
        .limit(1)
    )


def claims_with_evidence(
    session: Session, brief_id: int
) -> list[tuple[BriefClaim, list[EvidenceLink]]]:
    claims = list(
        session.scalars(
            select(BriefClaim).where(BriefClaim.brief_id == brief_id).order_by(BriefClaim.seq)
        )
    )
    if not claims:
        return []
    claim_ids = [c.id for c in claims]
    links = list(session.scalars(select(EvidenceLink).where(EvidenceLink.claim_id.in_(claim_ids))))
    by_claim: dict[int, list[EvidenceLink]] = {cid: [] for cid in claim_ids}
    for link in links:
        by_claim[link.claim_id].append(link)
    return [(c, by_claim[c.id]) for c in claims]


def persist_validated(
    session: Session,
    brief_id: int,
    *,
    headline: str,
    claims: list[tuple[str, str, list[int]]],
    model: str,
    usage: dict[str, int],
    attempts: int,
    failures: list[dict],
) -> None:
    # ORM attribute mutation (not a Core update()) so an already-loaded Brief instance
    # in this session's identity map reflects the change immediately — including
    # nullable/no-default columns like headline, which a bulk update() does not
    # reliably back-propagate onto an instance that never loaded them.
    brief = session.get(Brief, brief_id)
    if brief is None:
        return
    brief.status = "validated"
    brief.headline = headline
    brief.model = model
    brief.usage = usage
    brief.attempts = attempts
    brief.violations = failures
    brief.updated_at = func.now()
    for seq, (claim_text, claim_type, detection_ids) in enumerate(claims):
        claim = BriefClaim(brief_id=brief_id, seq=seq, text=claim_text, claim_type=claim_type)
        session.add(claim)
        session.flush()
        for detection_id in detection_ids:
            session.add(
                EvidenceLink(
                    claim_id=claim.id, evidence_type="detection", detection_id=detection_id
                )
            )
    session.flush()


def mark_rejected(
    session: Session,
    brief_id: int,
    *,
    failures: list[dict],
    attempts: int,
    model: str | None,
    usage: dict[str, int],
) -> None:
    brief = session.get(Brief, brief_id)
    if brief is None:
        return
    brief.status = "rejected"
    brief.violations = failures
    brief.attempts = attempts
    brief.model = model
    brief.usage = usage
    brief.updated_at = func.now()
    session.flush()


def mark_failed(session: Session, brief_id: int, *, code: str, message: str) -> None:
    brief = session.get(Brief, brief_id)
    if brief is None:
        return
    brief.status = "failed"
    brief.error = {"code": code, "message": message}
    brief.updated_at = func.now()
    session.flush()


def mark_stale_briefs(
    session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int
) -> int:
    result = session.execute(
        update(Brief)
        .where(
            Brief.aoi_id == aoi_id,
            Brief.before_scene_id == before_scene_id,
            Brief.after_scene_id == after_scene_id,
            Brief.status == "validated",
        )
        .values(status="stale", updated_at=func.now())
    )
    return result.rowcount


def detection_rows_for_pair(
    session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int
) -> list[DetectionEvent]:
    return list(
        session.scalars(
            select(DetectionEvent)
            .where(
                DetectionEvent.aoi_id == aoi_id,
                DetectionEvent.before_scene_id == before_scene_id,
                DetectionEvent.after_scene_id == after_scene_id,
            )
            .order_by(DetectionEvent.area_m2.desc())
        )
    )
