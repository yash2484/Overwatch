"""Tests for mask -> Detection polygonization."""

import numpy as np
import pytest

from overwatch.detection.models import ChangeType
from overwatch.detection.polygonize import polygonize_mask
from overwatch.detection.presets import VERTICAL_PRESETS
from tests.synthetic import EPSG, TRANSFORM_10M

FOREST_PRESET = VERTICAL_PRESETS["forest"]  # ndvi decrease 0.20, min area 5,000 m²


def _mask_and_maps(
    regions: list[tuple[int, int, int, int]], delta: float = -0.5
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    mask = np.zeros((30, 30), dtype=bool)
    ndvi = np.zeros((30, 30), dtype=np.float32)
    for r0, r1, c0, c1 in regions:
        mask[r0:r1, c0:c1] = True
        ndvi[r0:r1, c0:c1] = delta
    return mask, {"ndvi": ndvi}


def test_single_region_geometry_area_and_stats() -> None:
    mask, maps = _mask_and_maps([(5, 15, 5, 15)])  # 100 px = 10,000 m²
    [det] = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert det.change_type is ChangeType.VEGETATION_LOSS
    assert det.epsg == EPSG
    assert det.area_m2 == pytest.approx(10_000.0)
    assert det.geometry.bounds == (500_050.0, 999_850.0, 500_150.0, 999_950.0)
    assert det.magnitude == pytest.approx(0.5)
    assert det.confidence == pytest.approx(1.0)  # every pixel exceeds the 0.2 threshold
    assert det.contributing_indices["ndvi"] == pytest.approx(-0.5)


def test_region_below_min_area_is_dropped() -> None:
    mask, maps = _mask_and_maps([(5, 10, 5, 12)])  # 35 px = 3,500 m² < 5,000
    assert polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG) == []


def test_disjoint_regions_yield_separate_detections() -> None:
    mask, maps = _mask_and_maps([(2, 12, 2, 12), (18, 28, 18, 28)])
    dets = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert len(dets) == 2


def test_empty_mask_yields_no_detections() -> None:
    mask, maps = _mask_and_maps([])
    assert polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG) == []


def test_confidence_counts_only_pixels_over_threshold() -> None:
    mask, maps = _mask_and_maps([(5, 15, 5, 15)], delta=-0.5)
    maps["ndvi"][5:10, 5:15] = -0.1  # half the region below the 0.2 threshold
    [det] = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert det.confidence == pytest.approx(0.5)
