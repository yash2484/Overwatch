"""Usable-scene selection: SCL cloud gate + auto-widened search (design spec §6)."""

import logging
from dataclasses import dataclass
from datetime import date

from shapely.geometry import Polygon

from overwatch.imagery.masking import usable_fraction
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.imagery.provider import ImageryProvider, SceneCoverageError
from overwatch.imagery.search_windows import candidate_windows

logger = logging.getLogger(__name__)

MIN_USABLE_FRACTION = 0.7
DEFAULT_BANDS: tuple[str, ...] = ("red", "green", "blue")


@dataclass
class SceneSelection:
    scene: SceneMeta
    window: AOIWindow
    usable_fraction: float


def find_usable_scene(
    provider: ImageryProvider,
    geometry: Polygon,
    start: date,
    end: date,
    *,
    max_cloud_pct: float = 60.0,
    min_usable: float = MIN_USABLE_FRACTION,
    bands: tuple[str, ...] = DEFAULT_BANDS,
) -> SceneSelection | None:
    """First scene whose AOI window clears the usable-pixel gate; None if the cap exhausts.

    Scenes are tried clearest-first (scene-level cloud metadata), but the SCL gate on the
    actual AOI window decides — scene-level cloud % routinely lies about a small window.
    """
    seen: set[str] = set()
    for win_start, win_end in candidate_windows(start, end):
        scenes = provider.search_scenes(geometry, win_start, win_end, max_cloud_pct=max_cloud_pct)
        fresh = [s for s in scenes if s.stac_id not in seen]
        for scene in sorted(fresh, key=lambda s: s.cloud_pct):
            seen.add(scene.stac_id)
            try:
                window = provider.read_window(scene, geometry, bands)
            except SceneCoverageError as exc:
                logger.info("skipping %s: %s", scene.stac_id, exc)
                continue
            fraction = usable_fraction(window.scl)
            if fraction >= min_usable:
                logger.info(
                    "selected %s: usable=%.3f cloud=%.1f%%",
                    scene.stac_id,
                    fraction,
                    scene.cloud_pct,
                )
                return SceneSelection(scene=scene, window=window, usable_fraction=fraction)
            logger.info("skipping %s: usable=%.3f < %.3f", scene.stac_id, fraction, min_usable)
        if (win_start, win_end) != (start, end):
            logger.info("widened window to %s..%s exhausted", win_start, win_end)
    logger.warning("no usable scene for %s..%s after widening to +60d", start, end)
    return None
