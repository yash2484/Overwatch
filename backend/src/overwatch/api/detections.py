"""Detections as GeoJSON, filterable by spatial predicate (design doc §3)."""

from datetime import date
from typing import Any

import shapely.wkt
from fastapi import APIRouter
from geoalchemy2.shape import to_shape
from shapely.geometry import Polygon, box, mapping

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.db.detections import query_detections
from overwatch.db.jobs import latest_succeeded_job
from overwatch.db.models import DetectionEvent

router = APIRouter(tags=["detections"])


def _parse_intersects(raw: str) -> Polygon:
    """Accepts 'west,south,east,north' bbox or a WKT polygon."""
    parts = raw.split(",")
    if len(parts) == 4:
        try:
            return box(*(float(p) for p in parts))
        except ValueError:
            pass
    try:
        geom = shapely.wkt.loads(raw)
    except Exception as exc:
        raise ApiError(
            422, "invalid_intersects", f"expected bbox 'w,s,e,n' or WKT polygon: {exc}"
        ) from exc
    if not isinstance(geom, Polygon):
        raise ApiError(422, "invalid_intersects", "WKT must describe a polygon")
    return geom


def _feature(row: DetectionEvent) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": mapping(to_shape(row.geom)),
        "properties": {
            "id": row.id,
            "job_id": str(row.job_id),
            "before_scene_id": row.before_scene_id,
            "after_scene_id": row.after_scene_id,
            "change_type": row.change_type,
            "area_m2": row.area_m2,
            "magnitude": row.magnitude,
            "confidence": row.confidence,
            "contributing_indices": row.contributing_indices,
            "src_epsg": row.src_epsg,
            "created_at": row.created_at.isoformat(),
        },
    }


@router.get("/aois/{slug}/detections")
def list_detections(
    slug: str,
    session: SessionDep,
    intersects: str | None = None,
    since: date | None = None,
    change_type: str | None = None,
) -> dict[str, Any]:
    aoi = require_aoi(session, slug)
    geom = _parse_intersects(intersects) if intersects else None
    active_job = latest_succeeded_job(session, aoi.id)
    active_pair = (
        (active_job.before_scene_id, active_job.after_scene_id)
        if active_job is not None
        and active_job.before_scene_id is not None
        and active_job.after_scene_id is not None
        else None
    )
    rows = query_detections(
        session,
        aoi.id,
        before_scene_id=active_pair[0] if active_pair else None,
        after_scene_id=active_pair[1] if active_pair else None,
        intersects=geom,
        since=since,
        change_type=change_type,
    )
    return {"type": "FeatureCollection", "features": [_feature(row) for row in rows]}
