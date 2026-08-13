"""Dev-only: seed hand-authored demo briefs.

The console's narrative + bidirectional click-to-evidence is the product's headline, but
generating real briefs needs the Anthropic key (blocked on Console funding — see the Phase 5
handover). These briefs are hand-authored yet DATA-GROUNDED: they cite the real detection
ids over the AOI's actual scene pair and quote areas computed from those rows, so the map
join lights up exactly as a real brief would. They are marked ``model="demo-seed"`` so they
are never mistaken for LLM output; re-run ``generate_brief`` to replace them once the key is
funded.

Run:  docker compose exec -T api python -m overwatch.db.seed_briefs
"""

from __future__ import annotations

import sys

from sqlalchemy import delete, select

from overwatch.db.aois import get_aoi
from overwatch.db.briefs import create_brief, detection_rows_for_pair, persist_validated
from overwatch.db.engine import session_scope
from overwatch.db.models import Brief, BriefClaim, DetectionEvent, EvidenceLink

# (text, claim_type, detection_ids, article_ids) — the shape persist_validated wants.
Claim = tuple[str, str, list[int], list[int]]

# Marks a brief as hand-authored. Any other model value on a validated brief means the
# Anthropic API produced it, which the seeder refuses to overwrite (see _has_real_brief).
DEMO_MODEL = "demo-seed"


def _ha(m2: float) -> str:
    return f"{m2 / 10_000:.1f} ha"


def _vizhinjam(rows: list[DetectionEvent]) -> tuple[str, list[Claim]]:
    total = sum(r.area_m2 for r in rows)
    largest = rows[0]  # detection_rows_for_pair returns area-descending
    all_ids = [r.id for r in rows]
    headline = (
        "Vizhinjam International Seaport: a container terminal and breakwater were built "
        "between February 2021 and February 2025"
    )
    claims: list[Claim] = [
        (
            f"Between 12 February 2021 and 11 February 2025, {len(rows)} distinct areas of new "
            f"construction totalling {_ha(total)} were detected across the port site.",
            "observed",
            all_ids,
            [],
        ),
        (
            f"The largest single change, {largest.area_m2:,.0f} m², is the reclaimed "
            "terminal apron on the landward side of the harbour.",
            "observed",
            [largest.id],
            [],
        ),
        (
            "Further construction footprints trace the quay and the southern breakwater arm "
            "extending into the Arabian Sea.",
            "observed",
            [r.id for r in rows[1:5]],
            [],
        ),
        (
            "Vizhinjam is India’s first deep-water transshipment container terminal; "
            "build-out accelerated through 2023–2024 ahead of commercial commissioning.",
            "context",
            [],
            [],
        ),
    ]
    return headline, claims


def _novo_progresso(rows: list[DetectionEvent]) -> tuple[str, list[Claim]]:
    total = sum(r.area_m2 for r in rows)
    largest = rows[0]
    all_ids = [r.id for r in rows]
    headline = (
        f"Novo Progresso (BR-163): {len(rows)} new forest-clearing events detected between "
        "July 2023 and July 2024"
    )
    claims: list[Claim] = [
        (
            f"Between 30 July 2023 and 24 July 2024, {len(rows)} areas of forest loss totalling "
            f"{_ha(total)} were detected along the BR-163 corridor.",
            "observed",
            all_ids,
            [],
        ),
        (
            f"The largest single clearing, {_ha(largest.area_m2)}, sits on a standing-forest "
            "edge adjacent to previously cleared land.",
            "observed",
            [largest.id],
            [],
        ),
        (
            "The BR-163 corridor through Pará is a documented Amazon deforestation front; "
            "clearings of this pattern typically precede cattle pasture or soy conversion.",
            "context",
            [],
            [],
        ),
    ]
    return headline, claims


def _porto_alegre(rows: list[DetectionEvent]) -> tuple[str, list[Claim]]:
    total = sum(r.area_m2 for r in rows)
    largest = rows[0]
    all_ids = [r.id for r in rows]
    headline = (
        f"Porto Alegre: {_ha(total)} of new standing water detected across the Guaíba "
        "floodplain between April and May 2024"
    )
    claims: list[Claim] = [
        (
            f"Between 18 April 2024 and 21 May 2024, {len(rows)} areas of new standing water "
            f"totalling {_ha(total)} were detected across the observed area.",
            "observed",
            all_ids,
            [],
        ),
        (
            f"The largest contiguous inundation, {_ha(largest.area_m2)}, covers low-lying "
            "floodplain adjacent to the existing water body.",
            "observed",
            [largest.id],
            [],
        ),
        (
            "Open water rose from roughly 37% to 48% of the observed area between the two "
            "dates, a change consistent with river flooding rather than a local drainage event.",
            "observed",
            [r.id for r in rows[:5]],
            [],
        ),
        (
            "Rio Grande do Sul was reported to have suffered catastrophic flooding in "
            "May 2024, with the Guaíba reaching record levels at Porto Alegre in early May. "
            "The 21 May scene falls during the recession, so the detected extent is a "
            "lower bound on the flood's peak.",
            "context",
            [],
            [],
        ),
    ]
    return headline, claims


SEEDERS = {
    "vizhinjam": _vizhinjam,
    "novo-progresso": _novo_progresso,
    "porto-alegre": _porto_alegre,
}


def _has_real_brief(session, aoi_id: int) -> bool:
    """True if a real LLM-generated brief exists for the AOI.

    The seeder purges every brief for an AOI before writing its demo one, so running it
    after a live ``generate_brief`` run would silently destroy real, paid-for output. Any
    validated brief whose model is not ``demo-seed`` came from the Anthropic API.
    """
    return (
        session.scalar(
            select(Brief.id)
            .where(Brief.aoi_id == aoi_id, Brief.status == "validated", Brief.model != DEMO_MODEL)
            .limit(1)
        )
        is not None
    )


def _purge_briefs(session, aoi_id: int) -> None:
    """Delete any existing briefs for the AOI in FK order (dev seed is re-runnable)."""
    brief_ids = list(session.scalars(select(Brief.id).where(Brief.aoi_id == aoi_id)))
    if not brief_ids:
        return
    claim_ids = list(
        session.scalars(select(BriefClaim.id).where(BriefClaim.brief_id.in_(brief_ids)))
    )
    if claim_ids:
        session.execute(delete(EvidenceLink).where(EvidenceLink.claim_id.in_(claim_ids)))
    session.execute(delete(BriefClaim).where(BriefClaim.brief_id.in_(brief_ids)))
    session.execute(delete(Brief).where(Brief.id.in_(brief_ids)))
    session.flush()


def main() -> None:
    force = "--force" in sys.argv
    with session_scope() as session:
        for slug, seeder in SEEDERS.items():
            aoi = get_aoi(session, slug)
            if aoi is None:
                print(f"skip {slug}: no AOI")
                continue
            # Derive the scene pair from the detections themselves (no job lookup needed).
            latest = session.scalar(
                select(DetectionEvent)
                .where(DetectionEvent.aoi_id == aoi.id)
                .order_by(DetectionEvent.created_at.desc())
                .limit(1)
            )
            if latest is None:
                print(f"skip {slug}: no detections")
                continue
            if _has_real_brief(session, aoi.id) and not force:
                print(
                    f"skip {slug}: a real LLM brief exists — seeding would delete it "
                    "(--force to override)"
                )
                continue
            rows = detection_rows_for_pair(
                session,
                aoi_id=aoi.id,
                before_scene_id=latest.before_scene_id,
                after_scene_id=latest.after_scene_id,
            )
            _purge_briefs(session, aoi.id)
            brief = create_brief(
                session,
                aoi_id=aoi.id,
                before_scene_id=latest.before_scene_id,
                after_scene_id=latest.after_scene_id,
            )
            headline, claims = seeder(rows)
            persist_validated(
                session,
                brief.id,
                headline=headline,
                claims=claims,
                model=DEMO_MODEL,
                usage={},
                attempts=1,
                failures=[],
            )
            cited = sum(len(c[2]) for c in claims)
            print(
                f"seeded {slug}: brief {brief.id}, {len(claims)} claims, "
                f"{len(rows)} detections, {cited} citations"
            )


if __name__ == "__main__":
    main()
