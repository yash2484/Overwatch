from pyproj import Geod

from overwatch.aois import DEMO_ORDER, SHOWCASE_AOIS


def test_demo_order_covers_every_showcase_aoi() -> None:
    # list_aois sorts by this, and the console takes aois[0] as its default selection —
    # a slug missing here would silently fall to the end of the nav.
    assert set(DEMO_ORDER) == set(SHOWCASE_AOIS)
    assert len(DEMO_ORDER) == len(SHOWCASE_AOIS)


def test_demo_opens_on_the_flood() -> None:
    # Deliberate: the flood is the change a first-time viewer reads without being taught.
    assert DEMO_ORDER[0] == "porto-alegre"
    assert SHOWCASE_AOIS[DEMO_ORDER[0]].vertical == "flood"


def test_two_showcase_aois_present() -> None:
    assert set(SHOWCASE_AOIS) == {"vizhinjam", "porto-alegre"}
    assert {a.vertical for a in SHOWCASE_AOIS.values()} == {"port", "flood"}


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
