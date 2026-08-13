"""Spatial priors: where a change may plausibly be, independent of how it looks.

Threshold rules answer "did this pixel change in the right spectral direction?". They cannot
answer "is this the subject we are watching?" — that is geometry, not spectra.
"""

from shapely.geometry import box

from overwatch.detection.models import ChangeType, Detection
from overwatch.detection.priors import keep_near_largest

EPSG = 32643


def _det(x0: float, y0: float, size: float) -> Detection:
    """A square detection with its lower-left corner at (x0, y0), in projected metres."""
    return Detection(
        geometry=box(x0, y0, x0 + size, y0 + size),
        epsg=EPSG,
        area_m2=size * size,
        change_type=ChangeType.CONSTRUCTION,
        magnitude=0.8,
        confidence=1.0,
        contributing_indices={},
    )


TERMINAL = _det(0, 0, 600)  # 36 ha, the dominant structure


def test_the_largest_detection_is_always_kept() -> None:
    assert keep_near_largest([TERMINAL], radius_m=2_000.0) == [TERMINAL]


def test_a_detection_inside_the_radius_survives() -> None:
    near = _det(1_000, 0, 80)  # 400 m from the terminal's right edge
    assert keep_near_largest([TERMINAL, near], radius_m=2_000.0) == [TERMINAL, near]


def test_a_detection_beyond_the_radius_is_dropped() -> None:
    far = _det(3_000, 0, 80)  # 2.4 km from the terminal's right edge
    assert keep_near_largest([TERMINAL, far], radius_m=2_000.0) == [TERMINAL]


def test_distance_is_edge_to_edge_not_centroid_to_centroid() -> None:
    # A long quay runs for hundreds of metres; measuring from its centroid would push its own
    # apron outside the radius. Shapely's distance between polygons is already edge-to-edge —
    # assert it, because switching to centroids would silently shrink the kept set.
    just_inside = _det(2_500, 0, 80)  # edge gap 1.9 km, centroid gap ~2.24 km
    assert keep_near_largest([TERMINAL, just_inside], radius_m=2_000.0) == [
        TERMINAL,
        just_inside,
    ]


def test_input_order_is_preserved() -> None:
    a, b = _det(700, 0, 90), _det(900, 0, 80)
    assert keep_near_largest([a, TERMINAL, b], radius_m=2_000.0) == [a, TERMINAL, b]


def test_no_detections_yields_no_detections() -> None:
    assert keep_near_largest([], radius_m=2_000.0) == []


def test_the_anchor_is_the_largest_not_the_first() -> None:
    # Ordering out of polygonize follows label id, not area, so anchoring on the first element
    # would pin the radius to whichever speck happened to be labelled first.
    speck = _det(10_000, 0, 80)
    kept = keep_near_largest([speck, TERMINAL], radius_m=2_000.0)
    assert kept == [TERMINAL]
