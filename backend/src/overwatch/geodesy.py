"""Geodesic + CRS helpers shared by API validation and detection persistence."""

from functools import lru_cache

import shapely.ops
from pyproj import Geod, Transformer
from shapely.geometry import Polygon

_GEOD = Geod(ellps="WGS84")


def geodesic_area_km2(polygon: Polygon) -> float:
    """Unsigned geodesic area of an EPSG:4326 polygon, in square kilometres."""
    area_m2, _ = _GEOD.geometry_area_perimeter(polygon)
    return abs(area_m2) / 1_000_000.0


@lru_cache(maxsize=16)
def _to_wgs84_transformer(src_epsg: int) -> Transformer:
    return Transformer.from_crs(src_epsg, 4326, always_xy=True)


def to_wgs84(geometry: Polygon, src_epsg: int) -> Polygon:
    """Reproject a polygon from a projected CRS to EPSG:4326 (lon/lat)."""
    if src_epsg == 4326:
        return geometry
    return shapely.ops.transform(_to_wgs84_transformer(src_epsg).transform, geometry)
