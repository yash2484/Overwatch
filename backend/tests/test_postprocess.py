"""Tests for thresholding and morphological cleanup."""

import numpy as np

from overwatch.detection.postprocess import clean_mask, rule_mask
from overwatch.detection.presets import ThresholdRule


def _maps(shape: tuple[int, int] = (20, 20)) -> dict[str, np.ndarray]:
    ndvi = np.zeros(shape, dtype=np.float32)
    ndvi[5:10, 5:10] = -0.5
    dissim = np.zeros(shape, dtype=np.float32)
    dissim[5:10, 5:12] = 0.8
    return {"ndvi": ndvi, "ssim_dissim": dissim}


def test_single_decrease_rule() -> None:
    rules = [ThresholdRule(map="ndvi", direction="decrease", threshold=0.2)]
    out = rule_mask(_maps(), rules, usable=np.ones((20, 20), dtype=bool))
    assert out[7, 7] and not out[0, 0]
    assert np.count_nonzero(out) == 25


def test_rules_are_anded() -> None:
    rules = [
        ThresholdRule(map="ndvi", direction="decrease", threshold=0.2),
        ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.35),
    ]
    out = rule_mask(_maps(), rules, usable=np.ones((20, 20), dtype=bool))
    assert np.count_nonzero(out) == 25  # ndvi box is the intersection
    assert not out[7, 11]  # dissim-only column fails the ndvi rule


def test_unusable_and_nan_pixels_never_pass() -> None:
    maps = _maps()
    maps["ndvi"][5, 5] = np.nan
    usable = np.ones((20, 20), dtype=bool)
    usable[6, 6] = False
    rules = [ThresholdRule(map="ndvi", direction="decrease", threshold=0.2)]
    out = rule_mask(maps, rules, usable)
    assert not out[5, 5] and not out[6, 6] and out[7, 7]


def test_opening_removes_speckle() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[3, 3] = True  # single-pixel noise
    mask[10:16, 10:16] = True  # real region
    out = clean_mask(mask, open_px=3, close_px=3)
    assert not out[3, 3]
    assert out[12, 12]


def test_closing_fills_pinhole() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True
    mask[9, 9] = False  # pinhole
    out = clean_mask(mask, open_px=3, close_px=3)
    assert out[9, 9]
