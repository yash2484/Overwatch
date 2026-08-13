"""Pixel-level detection scoring against a labelled truth mask.

These are the numbers that turn "it detects the change" into a defensible claim, so the
conventions they encode — especially what a zero denominator means — are asserted here
rather than left to the reader of the implementation.
"""

import numpy as np
import pytest

from overwatch.eval.metrics import PixelScore, aggregate, score_masks


def _rect(shape: tuple[int, int], rows: slice, cols: slice) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    m[rows, cols] = True
    return m


def test_perfect_prediction_scores_one() -> None:
    truth = _rect((10, 10), slice(2, 6), slice(2, 6))
    score = score_masks(truth.copy(), truth)
    assert score.tp == 16 and score.fp == 0 and score.fn == 0
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0
    assert score.iou == 1.0


def test_disjoint_prediction_scores_zero() -> None:
    truth = _rect((10, 10), slice(0, 3), slice(0, 3))
    pred = _rect((10, 10), slice(6, 9), slice(6, 9))
    score = score_masks(pred, truth)
    assert score.tp == 0 and score.fp == 9 and score.fn == 9
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0
    assert score.iou == 0.0


def test_partial_overlap_gives_known_precision_and_recall() -> None:
    # truth = 4x4 = 16 px; pred = 4x4 shifted by 2 cols -> 8 px overlap, 8 fp, 8 fn.
    truth = _rect((10, 10), slice(2, 6), slice(2, 6))
    pred = _rect((10, 10), slice(2, 6), slice(4, 8))
    score = score_masks(pred, truth)
    assert (score.tp, score.fp, score.fn) == (8, 8, 8)
    assert score.precision == pytest.approx(0.5)
    assert score.recall == pytest.approx(0.5)
    assert score.f1 == pytest.approx(0.5)
    assert score.iou == pytest.approx(8 / 24)


def test_predicting_nothing_scores_zero_not_one() -> None:
    # A detector that never fires must not look perfect on precision. sklearn's
    # zero_division=0 convention: an undefined ratio is 0.0, never 1.0.
    truth = _rect((8, 8), slice(1, 4), slice(1, 4))
    score = score_masks(np.zeros((8, 8), dtype=bool), truth)
    assert score.tp == 0 and score.fp == 0 and score.fn == 9
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0


def test_valid_mask_excludes_pixels_from_every_count() -> None:
    # Cloud/no-data pixels must not be scored either way — a detector is not credited
    # for missing change it could not see, nor charged for a false positive there.
    truth = _rect((6, 6), slice(0, 3), slice(0, 6))
    pred = _rect((6, 6), slice(0, 6), slice(0, 6))
    valid = _rect((6, 6), slice(0, 3), slice(0, 6))  # only the top half is observable
    score = score_masks(pred, truth, valid=valid)
    assert score.tp == 18 and score.fp == 0 and score.fn == 0
    assert score.precision == 1.0 and score.recall == 1.0


def test_shape_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="shape"):
        score_masks(np.zeros((4, 4), dtype=bool), np.zeros((5, 5), dtype=bool))


def test_aggregate_micro_averages_by_summing_counts() -> None:
    # Micro-average is the OSCD convention: pool pixels across scenes so a large scene
    # carries proportionally more weight than a small one.
    a = PixelScore(tp=10, fp=0, fn=10, tn=0)
    b = PixelScore(tp=0, fp=10, fn=0, tn=0)
    total = aggregate([a, b])
    assert (total.tp, total.fp, total.fn) == (10, 10, 10)
    assert total.precision == pytest.approx(0.5)
    assert total.recall == pytest.approx(0.5)


def test_aggregate_of_nothing_is_all_zero() -> None:
    total = aggregate([])
    assert (total.tp, total.fp, total.fn, total.tn) == (0, 0, 0, 0)
    assert total.f1 == 0.0
