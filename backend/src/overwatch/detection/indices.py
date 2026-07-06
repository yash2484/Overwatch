"""Spectral indices as pure NaN-aware functions (design spec §6)."""

import numpy as np


def _normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) as float32; NaN where the denominator is 0 or an input is NaN."""
    a32 = a.astype(np.float32)
    b32 = b.astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a32 - b32) / (a32 + b32)
    return out.astype(np.float32)


def ndvi(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Vegetation: (nir - red) / (nir + red)."""
    return _normalized_difference(bands["nir"], bands["red"])


def ndwi(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Open water (McFeeters): (green - nir) / (green + nir)."""
    return _normalized_difference(bands["green"], bands["nir"])


def nbr(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Burn ratio: (nir - swir22) / (nir + swir22)."""
    return _normalized_difference(bands["nir"], bands["swir22"])
