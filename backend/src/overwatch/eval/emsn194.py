"""Adapter for EMSN194's date-specific Porto Alegre flood delineation."""

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import shape as to_shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as transform_geometry
from shapely.validation import make_valid

EXPECTED_AOI = "01"
EXPECTED_DATE = date(2024, 5, 8)
EXPECTED_METHOD = "Semi-automatic extraction"
EXPECTED_FLOOD_TYPE = "Inland flood"
EXPECTED_CRS = "urn:ogc:def:crs:OGC:1.3:CRS84"
OFFICIAL_AREA_REL_TOLERANCE = 0.002

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FloodFeature:
    geometry: BaseGeometry
    official_area_m2: float


def decode_flood_extent(
    raw: bytes,
    *,
    expected_aoi: str = EXPECTED_AOI,
    expected_date: date = EXPECTED_DATE,
) -> list[BaseGeometry]:
    """Decode the P04 observed-flood layer, rejecting incompatible EMS products."""
    return [
        feature.geometry
        for feature in _decode_flood_features(
            raw,
            expected_aoi=expected_aoi,
            expected_date=expected_date,
        )
    ]


def _decode_flood_features(
    raw: bytes,
    *,
    expected_aoi: str,
    expected_date: date,
) -> list[_FloodFeature]:
    document = json.loads(raw)
    if document.get("type") != "FeatureCollection":
        raise ValueError("expected an EMSN194 GeoJSON FeatureCollection")
    crs_name = (document.get("crs") or {}).get("properties", {}).get("name")
    if crs_name != EXPECTED_CRS:
        raise ValueError(f"expected EMSN194 CRS84 declaration; found {crs_name!r}")

    features: list[_FloodFeature] = []
    repaired_count = 0
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        if str(properties.get("aoi_id")) != expected_aoi:
            raise ValueError(
                f"unexpected EMSN194 AOI {properties.get('aoi_id')!r}; expected {expected_aoi!r}"
            )
        source_date = _parse_source_date(properties.get("source_dat"))
        if source_date != expected_date:
            raise ValueError(
                f"unexpected EMSN194 source date {source_date}; expected {expected_date}"
            )
        if properties.get("det_method") != EXPECTED_METHOD:
            raise ValueError(
                f"unexpected EMSN194 extraction method {properties.get('det_method')!r}"
            )
        if properties.get("flood_type") != EXPECTED_FLOOD_TYPE:
            raise ValueError(f"unexpected EMSN194 flood type {properties.get('flood_type')!r}")
        try:
            official_area_m2 = float(properties["area_ha"]) * 10_000
        except (KeyError, TypeError, ValueError) as exc:
            value = properties.get("area_ha")
            raise ValueError(f"invalid EMSN194 official area {value!r}") from exc
        if official_area_m2 <= 0:
            raise ValueError(f"invalid EMSN194 official area {official_area_m2}")

        raw_geometry = feature.get("geometry")
        if raw_geometry is None:
            raise ValueError("EMSN194 flood extent contains a missing geometry")
        geometry = to_shape(raw_geometry)
        if geometry.is_empty:
            raise ValueError("EMSN194 flood extent contains an empty geometry")
        if not geometry.is_valid:
            original_area = geometry.area
            geometry = make_valid(geometry)
            repaired_count += 1
            if not math.isclose(
                geometry.area,
                original_area,
                rel_tol=1e-9,
                abs_tol=1e-15,
            ):
                raise ValueError("repair changed EMSN194 geometry area")
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("EMSN194 flood extent geometry could not be repaired")
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"unexpected EMSN194 geometry type {geometry.geom_type}")
        features.append(_FloodFeature(geometry=geometry, official_area_m2=official_area_m2))

    if not features:
        raise ValueError("EMSN194 flood extent contains no features")
    if repaired_count:
        logger.warning(
            "repaired %d EMSN194 polygon ring self-intersections with make_valid",
            repaired_count,
        )
    return features


def flood_truth_mask(
    raw: bytes,
    *,
    shape: tuple[int, int],
    transform: Affine,
    epsg: int,
    expected_aoi: str = EXPECTED_AOI,
    expected_date: date = EXPECTED_DATE,
) -> np.ndarray:
    """Rasterise CRS84 flood polygons onto the detector's projected pixel grid."""
    features = _decode_flood_features(
        raw,
        expected_aoi=expected_aoi,
        expected_date=expected_date,
    )
    project = Transformer.from_crs(4326, epsg, always_xy=True).transform
    projected: list[BaseGeometry] = []
    for feature in features:
        geometry = transform_geometry(project, feature.geometry)
        relative_error = abs(geometry.area - feature.official_area_m2) / feature.official_area_m2
        if relative_error > OFFICIAL_AREA_REL_TOLERANCE:
            raise ValueError(
                "EMSN194 geometry disagrees with its official area: "
                f"measured={geometry.area:.1f} m2 official={feature.official_area_m2:.1f} m2"
            )
        projected.append(geometry)
    return rasterize(
        [(geometry, 1) for geometry in projected],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=False,
    ).astype(bool)


def _parse_source_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError(f"unexpected EMSN194 source date {value!r}")
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError(f"unexpected EMSN194 source date {value!r}") from exc
