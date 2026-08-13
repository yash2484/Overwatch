"""Detections -> pixel mask, so polygon output can be scored against a pixel truth mask.

Scoring the detector's *polygons* rather than its internal threshold mask is deliberate:
it measures what the system actually emits, min-area filtering and morphology included.
"""

import numpy as np
from affine import Affine
from shapely.geometry import box

from overwatch.eval.rasterize import mask_from_geometries

TRANSFORM = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 0.0)


def test_a_box_rasterizes_back_to_the_pixels_it_came_from() -> None:
    # With this transform, col c spans x=[10c, 10c+10) and row r spans y=(-10r-10, -10r].
    geom = box(20.0, -30.0, 60.0, -10.0)  # cols 2..5, rows 1..2
    mask = mask_from_geometries([geom], shape=(6, 8), transform=TRANSFORM)
    expected = np.zeros((6, 8), dtype=bool)
    expected[1:3, 2:6] = True
    assert mask.dtype == bool
    assert mask.tolist() == expected.tolist()


def test_no_detections_gives_an_all_false_mask() -> None:
    mask = mask_from_geometries([], shape=(4, 4), transform=TRANSFORM)
    assert mask.shape == (4, 4)
    assert not mask.any()


def test_overlapping_detections_do_not_double_count() -> None:
    # Union semantics: a pixel covered by two polygons is one changed pixel, not two.
    a = box(0.0, -20.0, 20.0, 0.0)
    b = box(10.0, -20.0, 30.0, 0.0)
    mask = mask_from_geometries([a, b], shape=(4, 4), transform=TRANSFORM)
    assert mask[0:2, 0:3].all()
    assert int(mask.sum()) == 6
