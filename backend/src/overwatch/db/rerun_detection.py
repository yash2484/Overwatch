"""Dev/maintenance: re-run detection for an AOI against its existing scene pair.

Reruns ONLY the detection step — no re-ingest, no Celery — so preset tuning iterates in
seconds instead of minutes. For each AOI it re-reads the most-recent detected scene pair,
runs the current ``VERTICAL_PRESETS[vertical]`` through ``ClassicalChangeDetector``, and
replace-sets the rows. This is the exact code path ``overwatch.run_detection`` uses, minus
the job orchestration, so the results are identical to a fresh pipeline run.

Detection ids change on every run (replace-set), so re-seed the demo briefs afterwards:

    docker compose exec -T api python -m overwatch.db.rerun_detection [slug ...]
    docker compose exec -T api python -m overwatch.db.seed_briefs
"""

from __future__ import annotations

import sys

from geoalchemy2.shape import to_shape
from sqlalchemy import select

from overwatch.api.scenes import _scene_meta  # backfills meta for pre-Phase-6 scene rows
from overwatch.db.aois import get_aoi
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.models import DetectionEvent, Scene
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.harmonize import harmonize_window
from overwatch.workers.tasks import BANDS, get_provider

DEFAULT_SLUGS = ["vizhinjam", "novo-progresso"]


def rerun(slug: str) -> None:
    with session_scope() as session:
        aoi = get_aoi(session, slug)
        if aoi is None:
            print(f"skip {slug}: no AOI")
            return
        # Derive the scene pair from the AOI's latest detection (same convention as the brief
        # seeder), so imagery URLs and any downstream joins stay pinned to the same scenes.
        latest = session.scalar(
            select(DetectionEvent)
            .where(DetectionEvent.aoi_id == aoi.id)
            .order_by(DetectionEvent.created_at.desc())
            .limit(1)
        )
        if latest is None:
            print(f"skip {slug}: no prior detection to derive the scene pair from")
            return
        aoi_id, vertical = aoi.id, aoi.vertical
        geometry = to_shape(aoi.geom)
        job_id = latest.job_id
        before_id, after_id = latest.before_scene_id, latest.after_scene_id
        before_meta = _scene_meta(session.get(Scene, before_id))
        after_meta = _scene_meta(session.get(Scene, after_id))

    provider = get_provider()
    before = harmonize_window(provider.read_window(before_meta, geometry, BANDS), before_meta)
    after = harmonize_window(provider.read_window(after_meta, geometry, BANDS), after_meta)
    detections = ClassicalChangeDetector().detect(before, after, VERTICAL_PRESETS[vertical])

    with session_scope() as session:
        count = replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job_id,
            before_scene_id=before_id,
            after_scene_id=after_id,
            detections=detections,
        )
    total_ha = sum(d.area_m2 for d in detections) / 10_000
    largest_ha = (max(d.area_m2 for d in detections) / 10_000) if detections else 0.0
    print(
        f"{slug} ({vertical}): {count} detections, {total_ha:.1f} ha total, "
        f"largest {largest_ha:.1f} ha"
    )


def main() -> None:
    slugs = sys.argv[1:] or DEFAULT_SLUGS
    for slug in slugs:
        rerun(slug)


if __name__ == "__main__":
    main()
