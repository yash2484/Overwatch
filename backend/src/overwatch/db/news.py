"""News-article persistence — replace-set on (aoi, after_scene) (Phase 5 design §5).

Mirrors `replace_detections` exactly: the scorer is deterministic, so the pair is the
natural key. Re-fusing rewrites identical rows — zero duplicates — and demotes any
validated brief over that pair to `stale` FIRST, so a brief can never keep a dangling
article_id after the articles it cited are replaced.

Invariant preserved, same as Phase 4's: **validated => every evidence link resolves.**
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from overwatch.db.briefs import mark_stale_briefs
from overwatch.db.models import NewsArticle
from overwatch.fusion.models import GateResult, RawArticle

# (article, gates, suppressed_urls, query) — what the fuse task hands us per survivor.
Admitted = tuple[RawArticle, GateResult, list[str], str]


def replace_articles(
    session: Session,
    *,
    aoi_id: int,
    job_id: str | uuid.UUID,
    before_scene_id: int,
    after_scene_id: int,
    admitted: list[Admitted],
) -> int:
    """Replace this pair's article set. Returns the number persisted.

    `before_scene_id` is required even though the table does not store it: a brief is
    scoped to the full (aoi, before, after) pair, so the stale flip must key on all three.
    """
    # Demote validated briefs over this exact pair BEFORE deleting the articles they may
    # cite — same transaction, so a rolled-back replace never leaves a brief falsely stale.
    mark_stale_briefs(
        session, aoi_id=aoi_id, before_scene_id=before_scene_id, after_scene_id=after_scene_id
    )
    session.execute(
        delete(NewsArticle).where(
            NewsArticle.aoi_id == aoi_id,
            NewsArticle.after_scene_id == after_scene_id,
        )
    )
    for article, gates, suppressed, query in admitted:
        session.add(
            NewsArticle(
                aoi_id=aoi_id,
                job_id=uuid.UUID(str(job_id)),
                after_scene_id=after_scene_id,
                url=article.url,
                title=article.title,
                domain=article.domain,
                language=article.language,
                seendate=article.seendate,
                # Which terms/keywords admitted it — every citation is auditable.
                gates_passed=gates.model_dump(mode="json", exclude={"passed", "reason"}),
                query=query,
                meta={
                    "socialimage": article.socialimage,
                    # Provenance only. sourcecountry is the PUBLISHER's registration
                    # country, not the story's location (design §2.3) — never a geo signal.
                    "sourcecountry": article.sourcecountry,
                    # Syndicated copies we suppressed, kept visible rather than silent.
                    "duplicates": suppressed,
                },
            )
        )
    session.flush()
    return len(admitted)


def articles_for_pair(session: Session, *, aoi_id: int, after_scene_id: int) -> list[NewsArticle]:
    """This pair's admitted articles, oldest first."""
    return list(
        session.scalars(
            select(NewsArticle)
            .where(
                NewsArticle.aoi_id == aoi_id,
                NewsArticle.after_scene_id == after_scene_id,
            )
            .order_by(NewsArticle.seendate, NewsArticle.id)
        )
    )
