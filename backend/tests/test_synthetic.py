"""The synthetic generator itself must be trustworthy — pin its spectral guarantees."""

import numpy as np

from overwatch.detection.indices import ndvi, ndwi
from tests.synthetic import (
    BARE,
    FOREST,
    SCL_CLOUD_HIGH,
    WATER,
    flat_window,
    inject_rect,
    rect_geometry,
)


def test_profiles_have_expected_index_signatures() -> None:
    forest = flat_window(FOREST, seed=1)
    bare = flat_window(BARE, seed=2)
    water = flat_window(WATER, seed=3)
    assert np.nanmean(ndvi(forest.bands)) > 0.6
    assert np.nanmean(ndvi(bare.bands)) < 0.2
    assert np.nanmean(ndwi(water.bands)) > 0.4
    assert np.nanmean(ndwi(bare.bands)) < 0.0


def test_flat_window_is_deterministic() -> None:
    a = flat_window(FOREST, seed=5)
    b = flat_window(FOREST, seed=5)
    assert all(np.array_equal(a.bands[k], b.bands[k]) for k in a.bands)


def test_inject_rect_changes_only_the_rect() -> None:
    window = flat_window(FOREST, seed=1)
    pristine = {k: v.copy() for k, v in window.bands.items()}
    inject_rect(window, BARE, (40, 50, 30, 50))
    outside = np.ones((120, 120), dtype=bool)
    outside[40:50, 30:50] = False
    for k in window.bands:
        assert np.array_equal(window.bands[k][outside], pristine[k][outside])
        assert not np.array_equal(window.bands[k][40:50, 30:50], pristine[k][40:50, 30:50])


def test_inject_rect_can_set_scl() -> None:
    window = flat_window(FOREST, seed=1)
    inject_rect(window, BARE, (40, 50, 30, 50), scl_class=SCL_CLOUD_HIGH)
    assert (window.scl[40:50, 30:50] == SCL_CLOUD_HIGH).all()
    assert (window.scl[0:40, :] != SCL_CLOUD_HIGH).all()


def test_rect_geometry_maps_pixels_to_utm() -> None:
    geom = rect_geometry((40, 50, 30, 50))
    assert geom.bounds == (500_300.0, 999_500.0, 500_500.0, 999_600.0)
    assert geom.area == 200 * 100.0  # 200 px * 100 m² each
