"""Threshold -> morphology: the raw-mask stage before polygonization (design spec §6)."""

import numpy as np
from scipy import ndimage

from overwatch.detection.presets import ThresholdRule


def rule_mask(
    maps: dict[str, np.ndarray], rules: list[ThresholdRule], usable: np.ndarray
) -> np.ndarray:
    """AND of every rule, restricted to usable pixels. NaN map values never pass."""
    out = usable.astype(bool).copy()
    for rule in rules:
        values = maps[rule.map]
        if rule.direction == "decrease":
            out &= values <= -rule.threshold
        else:
            out &= values >= rule.threshold
    return out


def clean_mask(mask: np.ndarray, *, open_px: int, close_px: int) -> np.ndarray:
    """Binary opening (drop speckle) then closing (fill pinholes), square structuring elements."""
    out = mask
    if open_px > 1:
        out = ndimage.binary_opening(out, structure=np.ones((open_px, open_px)))
    if close_px > 1:
        out = ndimage.binary_closing(out, structure=np.ones((close_px, close_px)))
    return out.astype(bool)
