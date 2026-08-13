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
    SHADED_FOREST,
    TURBID_WATER,
    WATER,
    flat_window,
    inject_rect,
    rect_geometry,
)

RECT = (40, 50, 30, 50)  # 10 x 20 px = 200 px = 20,000 m² — clears every min-area floor
DETECTOR = ClassicalChangeDetector()

SITE_SHAPE = (120, 400)  # 4 km wide: room for the terminal AND a stray well outside 2 km
TERMINAL = (30, 90, 30, 90)  # 60 x 60 px = 36 ha, the dominant structure the prior anchors on


def _pair(
    background: dict[str, int], change: dict[str, int], **inject_kwargs
) -> tuple[AOIWindow, AOIWindow]:
    before = flat_window(background, seed=1)
    after = flat_window(background, seed=2)
    inject_rect(after, change, RECT, **inject_kwargs)
    return before, after


def _site_pair(stray_rect: tuple[int, int, int, int]) -> tuple[AOIWindow, AOIWindow]:
    """A big terminal build plus one smaller build elsewhere, both appearing in the after scene."""
    before = flat_window(FOREST, shape=SITE_SHAPE, seed=1)
    after = flat_window(FOREST, shape=SITE_SHAPE, seed=2)
    inject_rect(after, BUILT, TERMINAL)
    inject_rect(after, BUILT, stray_rect, seed=13)
    return before, after


def _iou(a: Polygon, b: Polygon) -> float:
    return a.intersection(b).area / a.union(b).area


def _covers(det: Polygon, target: Polygon) -> float:
    """Fraction of `target` covered by `det` (recall). SSIM's window spreads a detection a few
    pixels past the true edge, so a covered footprint is a truer success signal than tight IoU."""
    return det.intersection(target).area / target.area


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


def test_flood_ignores_water_that_merely_clears() -> None:
    # Regression guard: NDWI-increase alone cannot tell "land became water" from "water got
    # clearer/deeper". Sediment settling between two dates raises NDWI well past the 0.20 gate
    # on pixels that were already water. On the real Porto Alegre pair that put 26% of detected
    # area (719.7 ha) on already-water pixels, including one 251 ha polygon that was 100% water
    # in the before scene. Flooding means land that became water; a was-NOT-water precondition
    # is what makes the distinction.
    before, after = _pair(TURBID_WATER, WATER)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["flood"]) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN LIMITATION, tracked not fixed: shading a canopy suppresses NIR harder than "
        "green, so NDWI climbs ~0.37 (clearing the 0.20 delta gate) from -0.71 (clearing the "
        "was-not-water gate) to -0.33, and darkened land reads as flood. An absolute after-NDWI "
        "floor closed this but rejected sediment-laden floodwater with it — 1,932.7 -> 925.8 ha "
        "on the real Porto Alegre pair — and ndvi_after showed no separating threshold either. "
        "Needs SWIR (MNDWI/AWEI_sh); see the flood preset's comment. strict=True so that whoever "
        "adds SWIR is told to delete this marker rather than leaving a passing xfail behind."
    ),
)
def test_flood_ignores_darkening_that_never_becomes_water() -> None:
    before, after = _pair(FOREST, SHADED_FOREST)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["flood"]) == []


def test_port_reclamation_detected() -> None:
    # The port preset is SSIM-only, so it catches construction over ANY prior cover. Sea ->
    # concrete (reclamation) is the headline transition.
    before, after = _pair(WATER, BUILT)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["port"])
    assert det.change_type is ChangeType.CONSTRUCTION
    assert _covers(det.geometry, rect_geometry(RECT)) > 0.9


def test_port_keeps_construction_beside_the_terminal() -> None:
    # SSIM is agnostic to prior cover, so vegetation -> built is caught as readily as
    # sea -> concrete; the OLD index-gated rule vetoed non-water builds and left the terminal
    # body half-outlined. The focus prior must not reintroduce that: an apron 300 m from the
    # terminal is exactly the port-adjacent development the console is meant to show.
    stray = (40, 60, 120, 140)
    before, after = _site_pair(stray)
    dets = DETECTOR.detect(before, after, VERTICAL_PRESETS["port"])
    assert len(dets) == 2
    assert all(d.change_type is ChangeType.CONSTRUCTION for d in dets)
    assert max(_covers(d.geometry, rect_geometry(stray)) for d in dets) > 0.9


def test_port_drops_construction_far_from_the_terminal() -> None:
    # Vizhinjam kept flagging scattered buildings well away from the harbour. Those ARE
    # structural change — on the real pair they scored ssim_dissim ~0.87, as high as the
    # terminal itself — so no SSIM threshold separates them: raising it drops the terminal too.
    # What disqualifies them is location, so the gate is geometric, applied alongside the
    # spectral rule rather than instead of it.
    stray = (40, 60, 350, 370)  # 2.6 km from the terminal's edge, outside the 2 km radius
    before, after = _site_pair(stray)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["port"])
    assert _covers(det.geometry, rect_geometry(TERMINAL)) > 0.9


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
    inject_rect(after, BARE, (40, 43, 30, 34))  # 12 px = 1,200 m² < forest's 3,000 m²
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_change_under_cloud_is_not_detected() -> None:
    before, after = _pair(FOREST, BARE, scl_class=SCL_CLOUD_HIGH)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_mismatched_windows_raise() -> None:
    before = flat_window(FOREST, seed=1, shape=(120, 120))
    after = flat_window(FOREST, seed=2, shape=(100, 100))
    with pytest.raises(ValueError, match="shape"):
        DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
