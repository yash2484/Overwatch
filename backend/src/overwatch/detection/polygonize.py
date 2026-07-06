"""Connected change regions -> typed Detection polygons."""

import numpy as np
from affine import Affine
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from overwatch.detection.models import Detection
from overwatch.detection.presets import DetectionPreset


def polygonize_mask(
    mask: np.ndarray,
    maps: dict[str, np.ndarray],
    preset: DetectionPreset,
    transform: Affine,
    epsg: int,
) -> list[Detection]:
    """One Detection per connected region, dropping regions under preset.min_area_m2."""
    pixel_area = abs(transform.a * transform.e)
    labels, n_regions = ndimage.label(mask)
    if n_regions == 0:
        return []
    primary = maps[preset.primary_map]
    primary_rule = next(r for r in preset.rules if r.map == preset.primary_map)
    detections: list[Detection] = []
    for region_id in range(1, n_regions + 1):
        region = labels == region_id
        area_m2 = float(np.count_nonzero(region) * pixel_area)
        if area_m2 < preset.min_area_m2:
            continue
        geometry = unary_union(
            [
                shape(geom)
                for geom, _ in features.shapes(
                    region.astype(np.uint8), mask=region, transform=transform
                )
            ]
        )
        values = primary[region]
        finite = values[np.isfinite(values)]
        magnitude = float(np.mean(np.abs(finite))) if finite.size else 0.0
        if primary_rule.direction == "decrease":
            exceeding = int(np.count_nonzero(finite <= -primary_rule.threshold))
        else:
            exceeding = int(np.count_nonzero(finite >= primary_rule.threshold))
        confidence = float(exceeding / finite.size) if finite.size else 0.0
        contributing = {
            name: (float(np.mean(vals[np.isfinite(vals)])) if np.isfinite(vals).any() else 0.0)
            for name, m in maps.items()
            for vals in [m[region]]
        }
        detections.append(
            Detection(
                geometry=geometry,
                epsg=epsg,
                area_m2=area_m2,
                change_type=preset.change_type,
                magnitude=magnitude,
                confidence=confidence,
                contributing_indices=contributing,
            )
        )
    return detections
