"""Burn detection polygons back onto the pixel grid they came from.

Scoring the emitted polygons rather than the detector's internal threshold mask is the
point: it measures what the system actually outputs, morphology and the min-area floor
included, so the reported accuracy is the accuracy a consumer of the API would get.
"""

from collections.abc import Sequence

import numpy as np
from affine import Affine
from rasterio import features
from shapely.geometry.base import BaseGeometry


def mask_from_geometries(
    geometries: Sequence[BaseGeometry], shape: tuple[int, int], transform: Affine
) -> np.ndarray:
    """Boolean mask of the union of `geometries` on a `shape` grid.

    Overlapping polygons union rather than accumulate — a pixel is changed or it isn't.
    """
    if not geometries:
        return np.zeros(shape, dtype=bool)
    burned = features.rasterize(
        ((geom, 1) for geom in geometries),
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=False,
    )
    return burned.astype(bool)
