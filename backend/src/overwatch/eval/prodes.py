"""Strict adapter for PRODES Amazon annual-deforestation increments."""

import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import shapefile
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from shapely.geometry import box
from shapely.geometry import shape as to_shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as transform_geometry
from shapely.validation import make_valid

PRODES_CRS_EPSG = 4674  # SIRGAS 2000 geographic coordinates.
REQUIRED_COMPONENTS = {".shp", ".shx", ".dbf", ".prj"}
REQUIRED_FIELDS = {
    "fid",
    "state",
    "path_row",
    "main_class",
    "class_name",
    "sub_class",
    "def_cloud",
    "julian_day",
    "image_date",
    "year",
    "area_km",
    "scene_id",
    "source",
    "satellite",
    "sensor",
    "uuid",
}


@dataclass(frozen=True)
class ProdesFeature:
    geometry: BaseGeometry
    year: int
    image_date: date
    state: str
    area_m2: float
    uuid: str


def load_prodes_archive(
    archive: Path,
    *,
    expected_year: int,
    bbox: tuple[float, float, float, float],
    expected_state: str = "PA",
) -> list[ProdesFeature]:
    """Read validated annual increments intersecting one benchmark window."""
    if not archive.exists():
        raise FileNotFoundError(f"missing PRODES archive: {archive}")

    with zipfile.ZipFile(archive) as source:
        members = [name for name in source.namelist() if not name.endswith("/")]
        by_suffix = {Path(name).suffix.lower(): name for name in members}
        if not by_suffix.keys() >= REQUIRED_COMPONENTS:
            missing = sorted(REQUIRED_COMPONENTS - by_suffix.keys())
            raise ValueError(f"PRODES archive lacks required Shapefile components: {missing}")
        stems = {Path(by_suffix[suffix]).stem for suffix in REQUIRED_COMPONENTS}
        if len(stems) != 1:
            raise ValueError("PRODES archive components do not share one basename")

        projection = source.read(by_suffix[".prj"]).decode("ascii").strip()
        try:
            crs = CRS.from_wkt(projection)
        except Exception as exc:
            raise ValueError("invalid PRODES projection; expected SIRGAS 2000") from exc
        if crs.to_epsg() != PRODES_CRS_EPSG:
            raise ValueError(f"unexpected PRODES projection {crs.name!r}; expected SIRGAS 2000")

        with (
            source.open(by_suffix[".shp"]) as shp,
            source.open(by_suffix[".shx"]) as shx,
            source.open(by_suffix[".dbf"]) as dbf,
        ):
            reader = shapefile.Reader(shp=shp, shx=shx, dbf=dbf, encoding="cp1252")
            return _load_reader_features(
                reader,
                expected_year=expected_year,
                bbox=bbox,
                expected_state=expected_state,
            )


def load_prodes_shapefile(
    path: Path,
    *,
    expected_year: int,
    bbox: tuple[float, float, float, float],
    expected_state: str = "PA",
) -> list[ProdesFeature]:
    """Read a previously verified and extracted PRODES Shapefile."""
    component_paths = {suffix: path.with_suffix(suffix) for suffix in REQUIRED_COMPONENTS}
    missing = sorted(
        suffix for suffix, component in component_paths.items() if not component.exists()
    )
    if missing:
        raise ValueError(f"PRODES Shapefile lacks required components: {missing}")
    projection = component_paths[".prj"].read_text(encoding="ascii").strip()
    _validate_projection(projection)
    reader = shapefile.Reader(str(path), encoding="cp1252")
    try:
        return _load_reader_features(
            reader,
            expected_year=expected_year,
            bbox=bbox,
            expected_state=expected_state,
        )
    finally:
        reader.close()


def _load_reader_features(
    reader: shapefile.Reader,
    *,
    expected_year: int,
    bbox: tuple[float, float, float, float],
    expected_state: str,
) -> list[ProdesFeature]:
    field_names = [field[0] for field in reader.fields[1:]]
    missing_fields = sorted(REQUIRED_FIELDS - set(field_names))
    if missing_fields:
        raise ValueError(f"PRODES Shapefile lacks required fields: {missing_fields}")

    window = box(*bbox)
    features: list[ProdesFeature] = []
    seen_uuids: set[str] = set()
    for shape_record in reader.iterShapeRecords(fields=field_names, bbox=bbox):
        properties = shape_record.record.as_dict()
        if _optional_integer(properties.get("year")) != expected_year:
            continue
        if str(properties.get("state", "")).strip().upper() != expected_state:
            continue
        geometry = to_shape(shape_record.shape.__geo_interface__)
        if not geometry.intersects(window):
            continue
        feature = decode_feature(
            properties,
            geometry,
            expected_year=expected_year,
            expected_state=expected_state,
        )
        if feature.uuid in seen_uuids:
            raise ValueError(f"duplicate PRODES UUID {feature.uuid!r}")
        seen_uuids.add(feature.uuid)
        features.append(feature)
    return features


def _validate_projection(projection: str) -> None:
    try:
        crs = CRS.from_wkt(projection)
    except Exception as exc:
        raise ValueError("invalid PRODES projection; expected SIRGAS 2000") from exc
    if crs.to_epsg() != PRODES_CRS_EPSG:
        raise ValueError(f"unexpected PRODES projection {crs.name!r}; expected SIRGAS 2000")


def decode_feature(
    properties: dict[str, object],
    geometry: BaseGeometry | None,
    *,
    expected_year: int,
    expected_state: str = "PA",
) -> ProdesFeature:
    """Validate one annual-increment feature before it enters benchmark truth."""
    if properties.get("main_class") != "DESMATAMENTO":
        raise ValueError(f"unexpected PRODES main class {properties.get('main_class')!r}")

    year = _integer(properties.get("year"), "year")
    if year != expected_year:
        raise ValueError(f"unexpected PRODES year {year}; expected {expected_year}")
    expected_class = f"d{expected_year}"
    if properties.get("class_name") != expected_class:
        raise ValueError(
            f"unexpected PRODES class name {properties.get('class_name')!r}; "
            f"expected {expected_class!r}"
        )

    source = str(properties.get("source", "")).strip().lower()
    if source != "amazonia":
        raise ValueError(f"unexpected PRODES source {properties.get('source')!r}")
    state = str(properties.get("state", "")).strip().upper()
    if state != expected_state:
        raise ValueError(f"unexpected PRODES state {state!r}; expected {expected_state!r}")

    try:
        area_m2 = float(properties["area_km"]) * 1_000_000
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid PRODES area {properties.get('area_km')!r}") from exc
    if not math.isfinite(area_m2) or area_m2 <= 0:
        raise ValueError(f"invalid PRODES area {area_m2}")

    image_date = _image_date(properties.get("image_date"))
    uuid = str(properties.get("uuid", "")).strip()
    if not uuid:
        raise ValueError("missing PRODES UUID")

    if geometry is None or geometry.is_empty:
        raise ValueError("PRODES feature has missing or empty geometry")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"unexpected PRODES geometry type {geometry.geom_type}")
    if not geometry.is_valid:
        original_area = geometry.area
        geometry = make_valid(geometry)
        if not math.isclose(geometry.area, original_area, rel_tol=1e-9, abs_tol=1e-15):
            raise ValueError("repair changed PRODES geometry area")
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("PRODES geometry could not be repaired")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"repaired PRODES geometry is {geometry.geom_type}")

    return ProdesFeature(
        geometry=geometry,
        year=year,
        image_date=image_date,
        state=state,
        area_m2=area_m2,
        uuid=uuid,
    )


def prodes_truth_mask(
    features: list[ProdesFeature],
    *,
    shape: tuple[int, int],
    transform: Affine,
    epsg: int,
) -> np.ndarray:
    """Rasterise validated PRODES polygons on the detector's pixel grid."""
    if not features:
        raise ValueError("no PRODES features intersect the benchmark window")
    project = Transformer.from_crs(PRODES_CRS_EPSG, epsg, always_xy=True).transform
    projected = [transform_geometry(project, feature.geometry) for feature in features]
    return rasterize(
        [(geometry, 1) for geometry in projected],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=False,
    ).astype(bool)


def _integer(value: object, label: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid PRODES {label} {value!r}") from exc
    return parsed


def _optional_integer(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _image_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"invalid PRODES image date {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid PRODES image date {value!r}") from exc
