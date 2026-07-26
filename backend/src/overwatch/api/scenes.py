"""Scene metadata + imagery for the Phase 6 console (design §4).

The image path is DETERMINISTIC — {aoi_slug}_{stac_id}.png — so serving imagery needs no
schema change. A missing file renders on demand and caches, which backfills every scene
ingested before this phase without a migration or a job re-run.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.config import settings
from overwatch.db.models import Scene
from overwatch.imagery.models import SceneMeta
from overwatch.imagery.render import render_rgb_png

logger = logging.getLogger(__name__)

# Own prefix-less router with full paths (the detections/briefs pattern): these routes span
# two roots (/aois/{slug}/scenes and /scenes/{id}/image), so they can't hang off the /aois
# prefix.
router = APIRouter(tags=["scenes"])


# Console true-colour rendering. A FIXED reflectance ceiling (S2 L2A BOA is reflectance
# x10000; ~3000 is a standard bright-surface ceiling) makes a before/after pair render
# consistently — per-scene percentiles let a bright new port crush the after scene to a
# "night" look. A mild gamma lift keeps water-heavy scenes reading as daytime. (Phase-1/2
# eyeball tooling keeps the default per-scene percentile stretch.)
CONSOLE_GAMMA = 0.75
CONSOLE_MAX_REFLECTANCE = 3000.0


def scene_image_path(aoi_slug: str, stac_id: str) -> Path:
    return settings.scene_image_dir / f"{aoi_slug}_{stac_id}.png"


def _epsg_from_stac_id(stac_id: str) -> int:
    """Derive the scene's native UTM EPSG from its MGRS tile (e.g. S2A_22JDM_... -> 32722).

    Pre-Phase-6 scene rows stored only assets + window_shape in ``meta``; the UTM zone is
    still recoverable from the STAC id's tile token. Band letters C..M are the southern
    hemisphere (327xx), N..X the northern (326xx).
    """
    tile = stac_id.split("_")[1]  # e.g. "22JDM"
    zone = int(tile[:2])
    southern = tile[2].upper() < "N"
    return (32700 if southern else 32600) + zone


def _scene_meta(scene: Scene) -> SceneMeta:
    """Build a SceneMeta, backfilling fields absent from pre-Phase-6 rows from the row itself."""
    m = dict(scene.meta or {})
    m.setdefault("stac_id", scene.stac_id)
    m.setdefault("collection", "sentinel-2-l2a")
    m.setdefault("captured_at", scene.captured_at.isoformat())
    m.setdefault("cloud_pct", scene.cloud_pct)
    if "epsg" not in m:
        m["epsg"] = _epsg_from_stac_id(scene.stac_id)
    return SceneMeta.model_validate(m)


def render_scene_png(scene: Scene, out_path: Path) -> Path:
    """Re-read the scene's window from the provider and render a true-colour PNG.

    Imports the provider lazily to avoid a circular import (workers/ imports api/ for the
    deterministic path at ingest time); api/ importing workers/ at module load would close
    the loop.
    """
    from overwatch.imagery.harmonize import harmonize_window
    from overwatch.workers.tasks import BANDS, get_provider

    meta = _scene_meta(scene)
    geometry = to_shape(scene.window_geom)
    window = harmonize_window(get_provider().read_window(meta, geometry, BANDS), meta)
    return render_rgb_png(
        window, out_path, gamma=CONSOLE_GAMMA, fixed_max=CONSOLE_MAX_REFLECTANCE
    )


@router.get("/aois/{slug}/scenes")
def list_scenes(slug: str, session: SessionDep) -> list[dict[str, Any]]:
    aoi = require_aoi(session, slug)
    rows = list(
        session.scalars(
            select(Scene).where(Scene.aoi_slug == aoi.slug).order_by(Scene.captured_at, Scene.id)
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        west, south, east, north = to_shape(row.window_geom).bounds
        out.append(
            {
                "id": row.id,
                "stac_id": row.stac_id,
                "captured_at": row.captured_at.isoformat(),
                "cloud_pct": row.cloud_pct,
                "usable_fraction": row.usable_fraction,
                "bounds": [west, south, east, north],  # [W, S, E, N] — MapLibre image source
            }
        )
    return out


@router.get("/scenes/{scene_id}/image")
def scene_image(scene_id: int, session: SessionDep) -> FileResponse:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise ApiError(404, "scene_not_found", f"no scene {scene_id}")
    path = scene_image_path(scene.aoi_slug, scene.stac_id)
    if not path.exists():
        logger.info("scene %s: image cache miss, rendering %s", scene_id, path)
        try:
            render_scene_png(scene, path)
        except Exception as exc:  # noqa: BLE001 — surface as a structured 503, never a 500
            raise ApiError(
                503, "scene_render_failed", f"could not render scene {scene_id}: {exc}"
            ) from exc
    return FileResponse(path, media_type="image/png")
