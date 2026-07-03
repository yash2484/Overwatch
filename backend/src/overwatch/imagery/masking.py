"""SCL-based cloud masking (design spec §6).

Masked (unusable): 0 no-data, 1 saturated/defective, 3 cloud shadow,
8 cloud medium prob, 9 cloud high prob, 10 thin cirrus, 11 snow/ice.
Usable: 2 dark area, 4 vegetation, 5 not vegetated, 6 water, 7 unclassified.
"""

import numpy as np

MASKED_SCL_CLASSES: frozenset[int] = frozenset({0, 1, 3, 8, 9, 10, 11})


def usable_mask(scl: np.ndarray) -> np.ndarray:
    """Boolean array, True where the pixel is usable for analysis."""
    return ~np.isin(scl, list(MASKED_SCL_CLASSES))


def usable_fraction(scl: np.ndarray) -> float:
    """Fraction of usable pixels in [0.0, 1.0]. Empty input counts as fully unusable."""
    if scl.size == 0:
        return 0.0
    return float(np.count_nonzero(usable_mask(scl)) / scl.size)


def apply_mask(band: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return band as float32 with unusable pixels set to NaN. Does not mutate input."""
    out = band.astype(np.float32, copy=True)
    out[~mask] = np.nan
    return out
