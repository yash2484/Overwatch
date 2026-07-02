"""ImageryProvider protocol — Earth Search today, swappable later (design spec §4)."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from shapely.geometry import Polygon

from overwatch.imagery.models import AOIWindow, SceneMeta


class SceneCoverageError(Exception):
    """The scene raster does not fully cover the requested AOI window."""


class ImageryProvider(Protocol):
    def search_scenes(
        self, geometry: Polygon, start: date, end: date, *, max_cloud_pct: float
    ) -> list[SceneMeta]:
        """Scenes intersecting geometry (EPSG:4326) within [start, end], oldest first."""
        ...

    def read_window(self, scene: SceneMeta, geometry: Polygon, bands: Sequence[str]) -> AOIWindow:
        """Windowed read of bands + SCL. Raises SceneCoverageError on partial coverage."""
        ...
