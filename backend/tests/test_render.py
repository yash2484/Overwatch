from pathlib import Path

import numpy as np
from affine import Affine
from PIL import Image

from overwatch.imagery.models import AOIWindow
from overwatch.imagery.render import render_rgb_png, stretch_to_uint8


def test_stretch_maps_percentile_range_to_full_uint8() -> None:
    band = np.linspace(0.0, 1000.0, 10000, dtype=np.float32).reshape(100, 100)
    out = stretch_to_uint8(band)
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_stretch_constant_band_is_all_zero() -> None:
    assert stretch_to_uint8(np.full((4, 4), 500.0, dtype=np.float32)).max() == 0


def test_stretch_nan_pixels_become_zero() -> None:
    band = np.array([[np.nan, 100.0], [200.0, 300.0]], dtype=np.float32)
    assert stretch_to_uint8(band)[0, 0] == 0


def test_render_writes_rgb_png(tmp_path: Path) -> None:
    shape = (8, 8)
    rng = np.random.default_rng(42)
    window = AOIWindow(
        bands={b: rng.integers(0, 4000, shape).astype(np.uint16) for b in ("red", "green", "blue")},
        scl=np.full(shape, 4, dtype=np.uint8),
        transform=Affine.identity(),
        epsg=32643,
    )
    out = render_rgb_png(window, tmp_path / "sub" / "scene.png")
    with Image.open(out) as img:
        assert img.mode == "RGB" and img.size == (8, 8)
