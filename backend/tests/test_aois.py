from pyproj import Geod

from overwatch.aois import SHOWCASE_AOIS


def test_three_showcase_aois_present() -> None:
    assert set(SHOWCASE_AOIS) == {"vizhinjam", "novo-progresso", "porto-alegre"}
    assert {a.vertical for a in SHOWCASE_AOIS.values()} == {"port", "forest", "flood"}


def test_bboxes_are_ordered() -> None:
    for aoi in SHOWCASE_AOIS.values():
        west, south, east, north = aoi.bbox
        assert west < east and south < north
        assert -180 <= west <= 180 and -90 <= south <= 90


def test_aoi_areas_between_1_and_500_km2() -> None:
    geod = Geod(ellps="WGS84")
    for aoi in SHOWCASE_AOIS.values():
        area_km2 = abs(geod.geometry_area_perimeter(aoi.geometry())[0]) / 1e6
        assert 1.0 < area_km2 < 500.0, f"{aoi.slug}: {area_km2:.1f} km2"
