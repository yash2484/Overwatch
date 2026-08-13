"""Adapter from the OSCD benchmark to the shapes `ClassicalChangeDetector` consumes.

OSCD (Onera Satellite Change Detection) is the standard public benchmark for Sentinel-2
change detection: 24 image pairs with hand-drawn pixel-level change masks. Its labels
cover **urban change** — new buildings and construction — which is why it scores the
construction (`port`) preset and not the vegetation or water ones.

Two caveats that belong on any number produced from it:
  * OSCD ships L1C top-of-atmosphere imagery; the pipeline normally reads L2A surface
    reflectance. The indices and SSIM this detector uses are relative, so the comparison
    holds, but it is not identical radiometry.
  * There is no SCL plane, so no pixel can be excluded as cloud — every pixel is scored.
"""

import numpy as np
from affine import Affine

from overwatch.imagery.models import AOIWindow

# Sentinel-2 L1C plane order: B01,B02,B03,B04,B05,B06,B07,B08,B8A,B09,B10,B11,B12.
# Only the four the presets read are mapped; the rest are carried by the dataset but unused.
MSI_BAND_INDEX: dict[str, int] = {"blue": 1, "green": 2, "red": 3, "nir": 7}

MSI_BAND_COUNT = 13

# OSCD tiles have no georeferencing in the HF export. The detector only uses the transform
# to convert pixel counts to areas and to reproject polygons, and every OSCD band used here
# is a 10 m band, so a bare 10 m grid gives correct areas.
_TRANSFORM_10M = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 0.0)
_EPSG = 32631  # any projected CRS in metres; areas are what matter, not position

# An SCL class that `usable_mask` does not exclude. OSCD has no cloud plane, so every
# pixel must read as observable rather than silently dropping out of the score.
_SCL_CLEAR = 4


def window_from_msi(stack: np.ndarray) -> AOIWindow:
    """Wrap a 13-band OSCD stack as an `AOIWindow` with an all-clear SCL plane."""
    if stack.ndim != 3 or stack.shape[0] != MSI_BAND_COUNT:
        raise ValueError(
            f"expected a {MSI_BAND_COUNT}-band stack (13, H, W), got shape {stack.shape}"
        )
    shape = stack.shape[1:]
    return AOIWindow(
        bands={name: stack[idx] for name, idx in MSI_BAND_INDEX.items()},
        scl=np.full(shape, _SCL_CLEAR, dtype=np.uint8),
        transform=_TRANSFORM_10M,
        epsg=_EPSG,
    )


# Label encoding in `<city>/cm/<city>-cm.tif`, verified against the shipped dataset.
CM_UNCHANGED = 1
CM_CHANGED = 2


def decode_cm(raw: np.ndarray) -> np.ndarray:
    """Boolean change mask from OSCD's `cm.tif`, which stores 1 = unchanged, 2 = changed.

    Deliberately strict. The sibling `cm.png` files are *not* interchangeable: some are
    RGBA with an all-255 alpha channel (so "any non-zero" marks the entire scene changed)
    and others carry antialiasing artifacts spanning most of 0-255. Rejecting anything
    outside {1, 2} turns that silent, catastrophic mislabelling into an error.
    """
    arr = np.asarray(raw)
    if arr.ndim != 2:
        raise ValueError(f"expected a single-band label array, got shape {arr.shape}")
    present = set(np.unique(arr).tolist())
    if not present <= {CM_UNCHANGED, CM_CHANGED}:
        raise ValueError(
            f"unexpected label values {sorted(present)[:8]} — expected only "
            f"{{{CM_UNCHANGED}, {CM_CHANGED}}}; is this a cm.png rather than cm.tif?"
        )
    return arr == CM_CHANGED
