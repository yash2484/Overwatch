"""Overlay PNG: detection outlines drawn over the true-colour after-image."""

import numpy as np
from PIL import Image
from shapely.geometry import box

from overwatch.detection.models import ChangeType, Detection
from overwatch.detection.overlay import render_detections_png
from tests.synthetic import EPSG, FOREST, flat_window


def test_overlay_draws_red_outline(tmp_path) -> None:
    window = flat_window(FOREST, seed=1)
    det = Detection(
        geometry=box(500_300.0, 999_500.0, 500_500.0, 999_600.0),  # rows 40..60, cols 30..50
        epsg=EPSG,
        area_m2=20_000.0,
        change_type=ChangeType.VEGETATION_LOSS,
        magnitude=0.5,
        confidence=0.9,
        contributing_indices={"ndvi": -0.5},
    )
    path = render_detections_png(window, [det], tmp_path / "overlay.png")
    img = np.asarray(Image.open(path))
    assert img.shape == (120, 120, 3)
    top_edge = img[38:43, 31:49]  # tolerate line width around row 40
    assert ((top_edge[..., 0] == 255) & (top_edge[..., 1] == 40)).any()
