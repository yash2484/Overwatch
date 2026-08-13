"""OSCD -> AOIWindow conversion.

The dataset ships a 13-band Sentinel-2 stack; the detector wants named bands and an SCL
plane. Getting the band indices wrong would silently score a different detector than the
one we ship, so the mapping is pinned here.
"""

import numpy as np
import pytest

from overwatch.eval.oscd import MSI_BAND_INDEX, decode_cm, window_from_msi
from overwatch.imagery.masking import usable_mask


def _stack(shape: tuple[int, int] = (6, 6)) -> np.ndarray:
    """13-band stack where every band is filled with its own index, so mapping is visible."""
    return np.stack([np.full(shape, i, dtype=np.uint16) for i in range(13)])


def test_band_indices_match_sentinel2_msi_order() -> None:
    # L1C band order is B01,B02,B03,B04,B05,B06,B07,B08,B8A,B09,B10,B11,B12.
    # blue=B02, green=B03, red=B04, nir=B08 — the four the presets actually read.
    assert MSI_BAND_INDEX == {"blue": 1, "green": 2, "red": 3, "nir": 7}


def test_window_carries_the_named_bands_from_the_right_planes() -> None:
    window = window_from_msi(_stack())
    assert set(window.bands) == {"blue", "green", "red", "nir"}
    for name, idx in MSI_BAND_INDEX.items():
        assert np.all(window.bands[name] == idx), f"{name} read the wrong plane"


def test_every_pixel_is_usable_because_oscd_ships_no_scl() -> None:
    # No cloud plane exists in the dataset, so nothing may be excluded from scoring.
    window = window_from_msi(_stack((5, 7)))
    assert usable_mask(window.scl).all()
    assert window.scl.shape == (5, 7)


def test_rejects_a_stack_that_is_not_13_band() -> None:
    with pytest.raises(ValueError, match="13"):
        window_from_msi(np.zeros((4, 6, 6), dtype=np.uint16))


def test_decode_cm_uses_the_one_two_convention() -> None:
    # Verified against the shipped labels: cm.tif stores 1 = unchanged, 2 = changed.
    # "any non-zero is change" would mark the whole scene changed.
    raw = np.array([[1, 2], [2, 1]], dtype=np.uint8)
    decoded = decode_cm(raw)
    assert decoded.dtype == bool
    assert decoded.tolist() == [[False, True], [True, False]]


def test_decode_cm_rejects_a_png_style_mask() -> None:
    # The cm.png files in the same folder are RGBA with an all-255 alpha channel, so
    # passing one here would silently score every pixel as changed. Fail loudly instead.
    png_like = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    with pytest.raises(ValueError, match="unexpected label values"):
        decode_cm(png_like)


def test_decode_cm_rejects_a_multichannel_array() -> None:
    with pytest.raises(ValueError, match="single-band"):
        decode_cm(np.ones((2, 2, 3), dtype=np.uint8))
