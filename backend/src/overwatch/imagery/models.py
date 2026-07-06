"""Typed imagery interfaces (design spec §4)."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from pydantic import BaseModel


class SceneMeta(BaseModel):
    """STAC scene metadata, provider-agnostic."""

    stac_id: str
    collection: str
    captured_at: datetime
    cloud_pct: float
    epsg: int
    assets: dict[str, str]  # asset key -> href, only the bands we may read
    dn_offset: int = 0  # add to DNs before index math (baseline >= 04.00 BOA offset)


@dataclass
class AOIWindow:
    """Windowed pixel data for one AOI within one scene, on the 10 m grid."""

    bands: dict[str, np.ndarray]  # all arrays share one shape
    scl: np.ndarray  # uint8, upsampled nearest to the same shape
    transform: Affine  # window transform in the scene's CRS
    epsg: int
