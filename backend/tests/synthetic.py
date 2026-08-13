"""Synthetic AOIWindow pairs with a known injected change (design spec §8).

DN profiles approximate Sentinel-2 L2A surface reflectance * 10000.
"""

import numpy as np
from affine import Affine
from shapely.geometry import Polygon, box

from overwatch.imagery.models import AOIWindow

FOREST = {"red": 400, "green": 600, "blue": 300, "nir": 3500}  # NDVI ~0.79
BARE = {"red": 2200, "green": 1900, "blue": 1500, "nir": 2600}  # NDVI ~0.08
WATER = {"red": 300, "green": 500, "blue": 600, "nir": 150}  # NDWI ~+0.54: clear open water
# Sediment-laden water: suspended solids raise NIR, so NDWI stays positive but much lower
# (~+0.14). Turbid -> clear is a water-to-water transition that still clears an NDWI-increase
# threshold, which is how flood detection acquires false positives over pre-existing water.
TURBID_WATER = {"red": 700, "green": 800, "blue": 800, "nir": 600}
# Canopy in deep shade (terrain shadow, or a low-sun after-scene). Every band darkens but NIR
# darkens hardest, so NDWI *rises* ~0.37 while the pixel stays firmly on the land side of
# McFeeters' 0.0 boundary (-0.33). This is the flood rule's other false positive: the delta gate
# passes AND the was-not-water precondition passes, because shaded forest was never water. Only
# an absolute floor on the after-image NDWI rejects it.
SHADED_FOREST = {"red": 250, "green": 450, "blue": 200, "nir": 900}
BUILT = {"red": 2600, "green": 2400, "blue": 2200, "nir": 2300}
CROP = {"red": 1500, "green": 1600, "blue": 1000, "nir": 3500}  # NDVI ~0.40: green but not forest

TRANSFORM_10M = Affine(10.0, 0.0, 500_000.0, 0.0, -10.0, 1_000_000.0)
EPSG = 32643  # UTM 43N (Vizhinjam's zone); any projected CRS works
SCL_VEGETATION = 4
SCL_CLOUD_HIGH = 9


def flat_window(
    profile: dict[str, int],
    shape: tuple[int, int] = (120, 120),
    *,
    scl_class: int = SCL_VEGETATION,
    noise: float = 40.0,
    seed: int = 7,
) -> AOIWindow:
    """Uniform landcover + deterministic Gaussian noise on the 10 m grid."""
    rng = np.random.default_rng(seed)
    bands = {
        name: np.clip(rng.normal(dn, noise, shape), 0, 10_000).astype(np.uint16)
        for name, dn in profile.items()
    }
    scl = np.full(shape, scl_class, dtype=np.uint8)
    return AOIWindow(bands=bands, scl=scl, transform=TRANSFORM_10M, epsg=EPSG)


def inject_rect(
    window: AOIWindow,
    profile: dict[str, int],
    rect: tuple[int, int, int, int],
    *,
    scl_class: int | None = None,
    noise: float = 40.0,
    seed: int = 11,
) -> tuple[int, int, int, int]:
    """Overwrite rows r0:r1, cols c0:c1 with another landcover. Mutates window in place."""
    r0, r1, c0, c1 = rect
    rng = np.random.default_rng(seed)
    for name, dn in profile.items():
        patch = np.clip(rng.normal(dn, noise, (r1 - r0, c1 - c0)), 0, 10_000)
        window.bands[name][r0:r1, c0:c1] = patch.astype(np.uint16)
    if scl_class is not None:
        window.scl[r0:r1, c0:c1] = scl_class
    return rect


def rect_geometry(rect: tuple[int, int, int, int]) -> Polygon:
    """The injected rect's footprint in TRANSFORM_10M map coordinates."""
    r0, r1, c0, c1 = rect
    x0, y0 = TRANSFORM_10M * (c0, r0)  # upper-left corner
    x1, y1 = TRANSFORM_10M * (c1, r1)  # lower-right corner
    return box(x0, y1, x1, y0)
