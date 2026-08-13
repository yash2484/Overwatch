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


def test_at_most_bounds_the_value_itself_not_its_magnitude() -> None:
    # "decrease" with 0.2 means <= -0.2, so a bound of +0.1 is unsayable that way. at_most takes
    # the threshold literally, which is what an absolute index map needs.
    maps = {"ndvi_after": np.full((4, 4), 0.05, dtype=np.float32)}
    usable = np.ones((4, 4), dtype=bool)
    passes = rule_mask(
        maps, [ThresholdRule(map="ndvi_after", direction="at_most", threshold=0.1)], usable
    )
    fails = rule_mask(
        maps, [ThresholdRule(map="ndvi_after", direction="at_most", threshold=0.0)], usable
    )
    assert passes.all()
    assert not fails.any()


def test_at_least_bounds_the_value_itself() -> None:
    maps = {"ndvi_before": np.full((4, 4), 0.55, dtype=np.float32)}
    usable = np.ones((4, 4), dtype=bool)
    assert rule_mask(
        maps, [ThresholdRule(map="ndvi_before", direction="at_least", threshold=0.5)], usable
    ).all()
    assert not rule_mask(
        maps, [ThresholdRule(map="ndvi_before", direction="at_least", threshold=0.6)], usable
    ).any()


def test_nan_never_passes_an_absolute_bound() -> None:
    # NaN comparisons are False in numpy, so cloud-masked pixels stay out — assert it rather
    # than rely on it, since at_most is the one direction where "everything below" is tempting.
    maps = {"ndvi_after": np.full((4, 4), np.nan, dtype=np.float32)}
    out = rule_mask(
        maps,
        [ThresholdRule(map="ndvi_after", direction="at_most", threshold=0.9)],
        np.ones((4, 4), dtype=bool),
    )
    assert not out.any()


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
