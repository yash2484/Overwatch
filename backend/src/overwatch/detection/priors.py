"""Spatial priors: physical constraints on WHERE a change can plausibly be (design spec §6).

A threshold rule gates on how a pixel changed. A prior gates on where the pixel sits. Some
verticals need both, because the spectral evidence can be perfectly real and still be the wrong
subject: construction 3 km inland is a genuine structural rebuild, so no SSIM threshold rejects
it — raising the threshold far enough to drop it drops the harbour too. Only its distance from
the water disqualifies it.

Pure module: numpy in, boolean mask out. No I/O, no LLM.
"""

import numpy as np
from scipy import ndimage

# NDWI's own design boundary (McFeeters 1996): water positive, land negative. This is the water
# cut for priors only — detection rules carry their own thresholds in the preset.
WATER_NDWI = 0.0


def near_water_mask(
    ndwi_before: np.ndarray,
    *,
    buffer_m: float,
    pixel_size_m: float,
    water_ndwi: float = WATER_NDWI,
    min_water_area_m2: float = 0.0,
) -> np.ndarray:
    """True where a pixel lies within `buffer_m` of open water in the BEFORE image.

    Measured on the before image on purpose: reclamation turns sea into land, so a buffer drawn
    around the AFTER image's water would disqualify the very pixels a port build is made of.

    `min_water_area_m2` drops water bodies below a size before the buffer is drawn. Without it
    the prior degrades wherever small water is common: on the real Vizhinjam pair, coastal
    Kerala's ponds and backwater put every pixel of the AOI within 2 km of "water", so a coastal
    buffer kept 20 of 22 detections and discriminated nothing. A port is on the sea, and the sea
    is large, so size is what separates a coastline from a paddy field.

    Fails closed. A window holding no qualifying water yields an all-False mask rather than
    silently passing everything, so a wrong bbox or a fully clouded coast surfaces as zero
    detections instead of as a quietly disabled prior. NaN pixels never count as water.
    """
    water = np.isfinite(ndwi_before) & (ndwi_before >= water_ndwi)
    if min_water_area_m2 > 0:
        water = _drop_small_bodies(water, min_water_area_m2, pixel_size_m**2)
    if not water.any():
        return np.zeros(ndwi_before.shape, dtype=bool)
    distance_m = ndimage.distance_transform_edt(~water) * pixel_size_m
    return np.asarray(distance_m <= buffer_m, dtype=bool)


def _drop_small_bodies(water: np.ndarray, min_area_m2: float, pixel_area_m2: float) -> np.ndarray:
    """Keep only connected water bodies of at least `min_area_m2`."""
    labels, count = ndimage.label(water)
    if count == 0:
        return water
    areas = np.bincount(labels.ravel()) * pixel_area_m2
    keeps = areas >= min_area_m2
    keeps[0] = False  # label 0 is the non-water background
    return keeps[labels]
