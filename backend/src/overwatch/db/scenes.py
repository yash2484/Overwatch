"""Scene persistence — idempotent upsert on the (stac_id, aoi_slug) natural key."""

from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from overwatch.db.models import Scene
from overwatch.imagery.models import SceneMeta


def upsert_scene(
    session: Session,
    scene: SceneMeta,
    aoi_slug: str,
    window_geometry: Polygon,
    usable_fraction: float | None,
    meta: dict[str, Any] | None = None,
) -> int:
    """Insert or update the row for (stac_id, aoi_slug); returns the stable row id."""
    values = {
        "stac_id": scene.stac_id,
        "aoi_slug": aoi_slug,
        "captured_at": scene.captured_at,
        "cloud_pct": scene.cloud_pct,
        "usable_fraction": usable_fraction,
        "epsg": scene.epsg,
        "window_geom": from_shape(window_geometry, srid=4326),
        "meta": meta or {},
    }
    update_cols = {k: v for k, v in values.items() if k not in ("stac_id", "aoi_slug")}
    update_cols["updated_at"] = func.now()
    stmt = (
        insert(Scene)
        .values(**values)
        .on_conflict_do_update(constraint="uq_scenes_stac_id_aoi_slug", set_=update_cols)
        .returning(Scene.id)
    )
    return session.execute(stmt).scalar_one()
