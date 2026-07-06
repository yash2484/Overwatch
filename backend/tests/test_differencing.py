"""Tests for change maps: index deltas and SSIM dissimilarity."""

import numpy as np
import pytest

from overwatch.detection.differencing import index_delta, ssim_dissimilarity
from tests.synthetic import BUILT, FOREST, flat_window, inject_rect


def test_index_delta_is_after_minus_before() -> None:
    before = np.array([[0.8, 0.2]], dtype=np.float32)
    after = np.array([[0.1, np.nan]], dtype=np.float32)
    out = index_delta(before, after)
    assert out[0, 0] == pytest.approx(-0.7)
    assert np.isnan(out[0, 1])
    assert out.dtype == np.float32


def test_ssim_dissimilarity_low_for_same_landcover() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)  # different noise, same landcover
    dissim = ssim_dissimilarity(before.bands["red"], after.bands["red"])
    assert dissim.shape == before.bands["red"].shape
    assert float(np.mean(dissim)) < 0.2


def test_ssim_dissimilarity_high_inside_changed_patch() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    inject_rect(after, BUILT, (40, 50, 30, 50))
    dissim = ssim_dissimilarity(before.bands["red"], after.bands["red"])
    inside = float(np.mean(dissim[42:48, 33:47]))  # patch interior, clear of the 7px window edge
    outside = float(np.mean(dissim[0:30, 0:30]))
    assert inside > 0.35
    assert outside < 0.2


def test_ssim_dissimilarity_tolerates_nan() -> None:
    before = flat_window(FOREST, seed=1).bands["red"].astype(np.float32)
    after = flat_window(FOREST, seed=2).bands["red"].astype(np.float32)
    before[0:10, 0:10] = np.nan
    out = ssim_dissimilarity(before, after)
    assert np.isfinite(out).all()
