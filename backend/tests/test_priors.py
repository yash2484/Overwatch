"""Spatial priors: where a change may plausibly BE, independent of how it looks.

Threshold rules answer "did this pixel change in the right spectral direction?". They cannot
answer "is this somewhere that kind of change happens at all?" — that is geometry, not spectra.
"""

import numpy as np

from overwatch.detection.priors import near_water_mask

SHAPE = (8, 40)


def _sea_on_the_left(water_cols: int = 2) -> np.ndarray:
    """Before-image NDWI: an open-water strip down the left edge, land everywhere else."""
    ndwi = np.full(SHAPE, -0.6, dtype=np.float32)
    ndwi[:, :water_cols] = 0.5
    return ndwi


def test_water_itself_is_inside_the_buffer() -> None:
    near = near_water_mask(_sea_on_the_left(), buffer_m=100.0, pixel_size_m=10.0)
    assert near[:, :2].all()


def test_pixels_adjacent_to_water_are_inside_the_buffer() -> None:
    near = near_water_mask(_sea_on_the_left(), buffer_m=100.0, pixel_size_m=10.0)
    assert near[0, 5]  # 4 px from the water edge = 40 m


def test_pixels_beyond_the_buffer_are_excluded() -> None:
    near = near_water_mask(_sea_on_the_left(), buffer_m=100.0, pixel_size_m=10.0)
    assert not near[0, 30]  # 29 px = 290 m


def test_buffer_is_measured_in_metres_not_pixels() -> None:
    # Same array, same buffer, coarser grid: col 5 is 40 m from water at 10 m/px but 240 m at
    # 60 m/px. A prior that forgot to multiply by pixel size would return identical masks.
    fine = near_water_mask(_sea_on_the_left(), buffer_m=100.0, pixel_size_m=10.0)
    coarse = near_water_mask(_sea_on_the_left(), buffer_m=100.0, pixel_size_m=60.0)
    assert fine[0, 5]
    assert not coarse[0, 5]


def test_window_without_water_has_no_near_water_pixels() -> None:
    # Fail closed. A port AOI whose before-scene contains no water is a broken scene or a wrong
    # bbox, not a licence to ignore the prior: returning all-True would silently disable it and
    # the emptiness would never surface.
    land = np.full(SHAPE, -0.6, dtype=np.float32)
    assert not near_water_mask(land, buffer_m=1000.0, pixel_size_m=10.0).any()


def test_nan_pixels_do_not_count_as_water() -> None:
    # Cloud-masked pixels arrive as NaN. A NaN sea would anchor the buffer to cloud, not coast.
    clouded = np.full(SHAPE, np.nan, dtype=np.float32)
    assert not near_water_mask(clouded, buffer_m=1000.0, pixel_size_m=10.0).any()


def test_small_water_bodies_do_not_seed_the_buffer() -> None:
    # Measured on the real Vizhinjam pair: the before-image water mask holds the 1,538 ha sea
    # plus 16 specks of 0.1 ha or less scattered inland. Every speck seeds a buffer of its own,
    # so a 1 km coastal gate kept 20 of 22 detections and discriminated almost nothing. A port
    # is on the sea, and the sea is large, so size is what separates coast from a wet speck.
    ndwi = np.full(SHAPE, -0.6, dtype=np.float32)
    ndwi[:, :2] = 0.5  # the sea: 8 x 2 px = 1,600 m² at 10 m
    ndwi[4, 20] = 0.5  # an inland pond: 1 px = 100 m²
    near = near_water_mask(ndwi, buffer_m=100.0, pixel_size_m=10.0, min_water_area_m2=1_000.0)
    assert near[4, 3]  # 20 m from the sea
    assert not near[4, 20]  # the pond does not qualify, not even at its own centre


def test_min_water_area_defaults_to_no_size_filter() -> None:
    # The size cut is a preset decision, so the prior itself stays unopinionated by default.
    ndwi = np.full(SHAPE, -0.6, dtype=np.float32)
    ndwi[4, 20] = 0.5
    assert near_water_mask(ndwi, buffer_m=100.0, pixel_size_m=10.0)[4, 20]


def test_marginally_negative_ndwi_is_land_not_coastline() -> None:
    # The water cut follows NDWI's own design (McFeeters: water is positive), so wet soil just
    # below zero does not seed a 1 km buffer around itself.
    marginal = np.full(SHAPE, -0.01, dtype=np.float32)
    assert not near_water_mask(marginal, buffer_m=1000.0, pixel_size_m=10.0).any()
