"""Typed detection outputs (design spec §4)."""

from dataclasses import dataclass
from enum import StrEnum

from shapely.geometry import Polygon


class ChangeType(StrEnum):
    CONSTRUCTION = "construction"
    VEGETATION_LOSS = "vegetation_loss"
    FLOODING = "flooding"


@dataclass
class Detection:
    """One change-event polygon, in the source window's projected CRS."""

    geometry: Polygon
    epsg: int
    area_m2: float
    change_type: ChangeType
    magnitude: float  # mean |primary-map delta| over the polygon's pixels
    confidence: float  # fraction of polygon pixels exceeding the primary threshold, [0, 1]
    contributing_indices: dict[str, float]  # change-map name -> mean value over the polygon
