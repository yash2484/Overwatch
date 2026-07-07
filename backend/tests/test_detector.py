"""End-to-end engine tests on synthetic pairs: inject a known change, assert the polygon."""

import pytest
from shapely.geometry import Polygon

from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.models import ChangeType
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.models import AOIWindow
from tests.synthetic import (
    BARE,
    BUILT,
    CROP,
    FOREST,
    SCL_CLOUD_HIGH,
    WATER,
    flat_window,
    inject_rect,
    rect_geometry,
)

RECT = (40, 50, 30, 50)  # 10 x 20 px = 200 px = 20,000 m² — clears every min-area floor
DETECTOR = ClassicalChangeDetector()


def _pair(
    background: dict[str, int], change: dict[str, int], **inject_kwargs
) -> tuple[AOIWindow, AOIWindow]:
    before = flat_window(background, seed=1)
    after = flat_window(background, seed=2)
    inject_rect(after, change, RECT, **inject_kwargs)
    return before, after


def _iou(a: Polygon, b: Polygon) -> float:
    return a.intersection(b).area / a.union(b).area


def test_forest_clearing_detected() -> None:
    before, after = _pair(FOREST, BARE)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
    assert det.change_type is ChangeType.VEGETATION_LOSS
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5
    assert det.magnitude > 0.4
    assert 0.0 < det.confidence <= 1.0
    assert det.contributing_indices["ndvi"] < -0.3


def test_flood_inundation_detected() -> None:
    before, after = _pair(BARE, WATER)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["flood"])
    assert det.change_type is ChangeType.FLOODING
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5
    assert det.contributing_indices["ndwi"] > 0.3


def test_port_construction_detected() -> None:
    before, after = _pair(FOREST, BUILT)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["port"])
    assert det.change_type is ChangeType.CONSTRUCTION
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5


def test_no_change_yields_no_detections() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    for preset in VERTICAL_PRESETS.values():
        assert DETECTOR.detect(before, after, preset) == []


def test_crop_harvest_is_not_flagged_as_deforestation() -> None:
    # Harvesting a green (but non-forest) crop drops NDVI enough to trip the bare
    # decrease rule, but the was-forest precondition rejects it: the *before* image
    # was cropland (NDVI ~0.4), never forest (>0.6).
    before, after = _pair(CROP, BARE)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_real_forest_clearing_still_detected_with_precondition() -> None:
    # Regression guard: the precondition must not suppress genuine forest loss.
    before, after = _pair(FOREST, BARE)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
    assert det.change_type is ChangeType.VEGETATION_LOSS
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5


def test_sub_min_area_change_is_dropped() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    inject_rect(after, BARE, (40, 43, 30, 34))  # 12 px = 1,200 m² < forest's 5,000 m²
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_change_under_cloud_is_not_detected() -> None:
    before, after = _pair(FOREST, BARE, scl_class=SCL_CLOUD_HIGH)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_mismatched_windows_raise() -> None:
    before = flat_window(FOREST, seed=1, shape=(120, 120))
    after = flat_window(FOREST, seed=2, shape=(100, 100))
    with pytest.raises(ValueError, match="shape"):
        DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
