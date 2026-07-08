"""Geodesic area + reprojection helpers."""

from pyproj import Transformer
from shapely.geometry import box

from overwatch.geodesy import geodesic_area_km2, to_wgs84


def test_one_degree_equatorial_box_area() -> None:
    # 1 deg x 1 deg at the equator is about 12,300 km^2
    assert 12_000 < geodesic_area_km2(box(0.0, 0.0, 1.0, 1.0)) < 12_700


def test_vizhinjam_bbox_is_well_under_cap() -> None:
    area = geodesic_area_km2(box(76.960, 8.355, 77.010, 8.395))
    assert 20 < area < 30  # about 24 km^2


def test_to_wgs84_round_trips_utm() -> None:
    fwd = Transformer.from_crs(4326, 32643, always_xy=True)
    x, y = fwd.transform(76.98, 8.37)
    utm_square = box(x - 500, y - 500, x + 500, y + 500)
    lonlat = to_wgs84(utm_square, 32643)
    assert abs(lonlat.centroid.x - 76.98) < 1e-3
    assert abs(lonlat.centroid.y - 8.37) < 1e-3


def test_to_wgs84_is_noop_for_4326() -> None:
    square = box(0, 0, 1, 1)
    assert to_wgs84(square, 4326) is square
