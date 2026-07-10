"""Detection persistence — replace-set on the (aoi, before, after) pair (design doc §2).

The engine is deterministic, so the pair is the natural key: one transaction deletes the
pair's rows and reinserts. Re-running a job rewrites identical rows — zero duplicates.
"""

import uuid
from datetime import date

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from overwatch.db.briefs import mark_stale_briefs
from overwatch.db.models import DetectionEvent, Scene
from overwatch.detection.models import Detection
from overwatch.geodesy import to_wgs84


def replace_detections(
    session: Session,
    *,
    aoi_id: int,
    job_id: str | uuid.UUID,
    before_scene_id: int,
    after_scene_id: int,
    detections: list[Detection],
) -> int:
    # Demote validated briefs over this exact pair before the detections they cite
    # are deleted below — same transaction, so a rolled-back replace-set never leaves
    # a brief falsely marked stale.
    mark_stale_briefs(
        session, aoi_id=aoi_id, before_scene_id=before_scene_id, after_scene_id=after_scene_id
    )
    session.execute(
        delete(DetectionEvent).where(
            DetectionEvent.aoi_id == aoi_id,
            DetectionEvent.before_scene_id == before_scene_id,
            DetectionEvent.after_scene_id == after_scene_id,
        )
    )
    for det in detections:
        session.add(
            DetectionEvent(
                aoi_id=aoi_id,
                job_id=uuid.UUID(str(job_id)),
                before_scene_id=before_scene_id,
                after_scene_id=after_scene_id,
                geom=from_shape(to_wgs84(det.geometry, det.epsg), srid=4326),
                src_epsg=det.epsg,
                area_m2=det.area_m2,
                change_type=det.change_type.value,
                magnitude=det.magnitude,
                confidence=det.confidence,
                contributing_indices=det.contributing_indices,
            )
        )
    session.flush()
    return len(detections)


def query_detections(
    session: Session,
    aoi_id: int,
    *,
    intersects: Polygon | None = None,
    since: date | None = None,
    change_type: str | None = None,
) -> list[DetectionEvent]:
    """Events for an AOI; `since` filters on the after scene's capture date."""
    stmt = select(DetectionEvent).where(DetectionEvent.aoi_id == aoi_id)
    if intersects is not None:
        stmt = stmt.where(
            func.ST_Intersects(DetectionEvent.geom, from_shape(intersects, srid=4326))
        )
    if since is not None:
        after_scene = aliased(Scene)
        stmt = stmt.join(after_scene, DetectionEvent.after_scene_id == after_scene.id).where(
            after_scene.captured_at >= since
        )
    if change_type is not None:
        stmt = stmt.where(DetectionEvent.change_type == change_type)
    return list(session.scalars(stmt.order_by(DetectionEvent.area_m2.desc())))
