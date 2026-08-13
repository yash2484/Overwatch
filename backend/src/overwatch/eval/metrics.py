"""Pixel-level confusion counts and the ratios derived from them.

Pure arithmetic over boolean masks — no I/O, no detector imports. Every ratio uses the
`zero_division=0` convention (sklearn's): an undefined ratio is 0.0, never 1.0, so a
detector that never fires can't score a perfect precision.
"""

from collections.abc import Iterable

import numpy as np
from pydantic import BaseModel


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


class PixelScore(BaseModel, frozen=True):
    """Confusion counts for one scored pair, plus the ratios they imply."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        """Of the pixels called change, the fraction that really changed."""
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        """Of the pixels that really changed, the fraction found."""
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return _ratio(2 * p * r, p + r) if (p + r) else 0.0

    @property
    def iou(self) -> float:
        """Intersection over union — the metric OSCD results are usually quoted in."""
        return _ratio(self.tp, self.tp + self.fp + self.fn)


def score_masks(
    predicted: np.ndarray, truth: np.ndarray, valid: np.ndarray | None = None
) -> PixelScore:
    """Score a predicted change mask against a labelled truth mask.

    `valid` marks observable pixels. Anything outside it is scored neither way: a detector
    is not charged for missing change under cloud, nor credited for a false positive there.
    """
    if predicted.shape != truth.shape:
        raise ValueError(f"shape mismatch: predicted {predicted.shape} vs truth {truth.shape}")
    p = predicted.astype(bool)
    t = truth.astype(bool)
    if valid is not None:
        if valid.shape != truth.shape:
            raise ValueError(f"shape mismatch: valid {valid.shape} vs truth {truth.shape}")
        v = valid.astype(bool)
        p, t = p & v, t & v
        observable = int(v.sum())
    else:
        observable = t.size
    tp = int(np.count_nonzero(p & t))
    fp = int(np.count_nonzero(p & ~t))
    fn = int(np.count_nonzero(~p & t))
    return PixelScore(tp=tp, fp=fp, fn=fn, tn=observable - tp - fp - fn)


def aggregate(scores: Iterable[PixelScore]) -> PixelScore:
    """Micro-average: pool pixels across scenes before taking ratios.

    This is the OSCD convention. It weights a large scene more heavily than a small one,
    which is what you want when the question is "how does this behave on real imagery"
    rather than "how does it behave on the average scene".
    """
    total = PixelScore(tp=0, fp=0, fn=0, tn=0)
    for s in scores:
        total = PixelScore(
            tp=total.tp + s.tp, fp=total.fp + s.fp, fn=total.fn + s.fn, tn=total.tn + s.tn
        )
    return total
