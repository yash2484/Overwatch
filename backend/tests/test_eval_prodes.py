"""Strict validation and rasterisation of PRODES annual-increment truth."""

import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import shapefile
from affine import Affine
from shapely.geometry import Polygon

from overwatch.eval.prodes import (
    decode_feature,
    load_prodes_archive,
    load_prodes_shapefile,
    prodes_truth_mask,
)

SIRGAS_2000_WKT = (
    'GEOGCS["GCS_SIRGAS_2000",DATUM["D_SIRGAS_2000",'
    'SPHEROID["GRS_1980",6378137.0,298.257222101]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def _properties(**overrides: object) -> dict[str, object]:
    properties: dict[str, object] = {
        "fid": 42,
        "state": "PA",
        "path_row": "22462",
        "main_class": "DESMATAMENTO",
        "class_name": "d2024",
        "sub_class": "corte raso com vegetacao",
        "def_cloud": 0.0,
        "julian_day": 205,
        "image_date": "20240723",
        "year": 2024,
        "area_km": 0.01,
        "scene_id": 1502,
        "source": "Amazonia",
        "satellite": "Landsat",
        "sensor": "OLI",
        "uuid": "264b9a88-e718-4ddc-b732-0ff5371b699f",
    }
    properties.update(overrides)
    return properties


def _geometry() -> Polygon:
    return Polygon([(-50.0, -8.0), (-49.999, -8.0), (-49.999, -8.001), (-50.0, -8.001)])


def _archive(
    tmp_path: Path,
    records: list[tuple[dict[str, object], Polygon]],
    *,
    prj: str = SIRGAS_2000_WKT,
    omit_extension: str | None = None,
    encoding: str = "utf-8",
) -> Path:
    stem = tmp_path / "yearly_deforestation_biome_amazonia_v20260717"
    with shapefile.Writer(str(stem), shapeType=shapefile.POLYGON, encoding=encoding) as writer:
        writer.field("fid", "N", size=9)
        writer.field("state", "C", size=99)
        writer.field("path_row", "C", size=20)
        writer.field("main_class", "C", size=254)
        writer.field("class_name", "C", size=254)
        writer.field("sub_class", "C", size=254)
        writer.field("def_cloud", "N", size=24, decimal=15)
        writer.field("julian_day", "N", size=9)
        writer.field("image_date", "D")
        writer.field("year", "N", size=9)
        writer.field("area_km", "N", size=24, decimal=15)
        writer.field("scene_id", "N", size=9)
        writer.field("source", "C", size=50)
        writer.field("satellite", "C", size=50)
        writer.field("sensor", "C", size=50)
        writer.field("uuid", "C", size=80)
        for properties, geometry in records:
            writer.poly([list(geometry.exterior.coords)])
            writer.record(**properties)
    stem.with_suffix(".prj").write_text(prj, encoding="ascii")

    archive = tmp_path / "truth.zip"
    with zipfile.ZipFile(archive, "w") as target:
        for extension in (".shp", ".shx", ".dbf", ".prj"):
            if extension != omit_extension:
                path = stem.with_suffix(extension)
                target.write(path, path.name)
    return archive


def test_decodes_a_matching_amazon_increment_and_preserves_acquisition_date() -> None:
    feature = decode_feature(_properties(), _geometry(), expected_year=2024)

    assert feature.year == 2024
    assert feature.image_date == date(2024, 7, 23)
    assert feature.state == "PA"
    assert feature.area_m2 == pytest.approx(10_000.0)
    assert feature.geometry.equals(_geometry())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"main_class": "NUVEM"}, "main class"),
        ({"class_name": "d2023"}, "class name"),
        ({"year": 2023, "class_name": "d2023"}, "year"),
        ({"source": "Cerrado"}, "source"),
        ({"state": "MT"}, "state"),
        ({"area_km": 0.0}, "area"),
        ({"image_date": "20241340"}, "image date"),
        ({"uuid": ""}, "UUID"),
    ],
)
def test_rejects_truth_with_mismatched_identity(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        decode_feature(_properties(**overrides), _geometry(), expected_year=2024)


def test_rejects_missing_or_non_polygonal_geometry() -> None:
    with pytest.raises(ValueError, match="geometry"):
        decode_feature(_properties(), None, expected_year=2024)


def test_rasterises_truth_on_the_detector_grid() -> None:
    feature = decode_feature(
        _properties(area_km=0.000001),
        Polygon([(0, 0), (0.00001, 0), (0.00001, 0.00001), (0, 0.00001)]),
        expected_year=2024,
    )

    mask = prodes_truth_mask(
        [feature],
        shape=(1, 1),
        transform=Affine(2, 0, 0, 0, -2, 2),
        epsg=3857,
    )

    assert mask.dtype == np.bool_
    assert mask.tolist() == [[True]]


def test_truth_mask_rejects_an_empty_feature_set() -> None:
    with pytest.raises(ValueError, match="no PRODES features"):
        prodes_truth_mask([], shape=(1, 1), transform=Affine.identity(), epsg=3857)


def test_loads_only_matching_year_features_that_intersect_the_window(tmp_path: Path) -> None:
    inside = _geometry()
    outside = Polygon([(-55, -4), (-54.9, -4), (-54.9, -4.1), (-55, -4.1)])
    archive = _archive(
        tmp_path,
        [
            (_properties(), inside),
            (_properties(fid=43, uuid="outside", image_date="20240724"), outside),
            (_properties(fid=44, uuid="old", year=2023, class_name="d2023"), inside),
        ],
    )

    features = load_prodes_archive(
        archive,
        expected_year=2024,
        bbox=(-50.01, -8.01, -49.99, -7.99),
    )

    assert [feature.uuid for feature in features] == ["264b9a88-e718-4ddc-b732-0ff5371b699f"]


def test_archive_rejects_missing_shapefile_component(tmp_path: Path) -> None:
    archive = _archive(tmp_path, [(_properties(), _geometry())], omit_extension=".shx")

    with pytest.raises(ValueError, match="components"):
        load_prodes_archive(archive, expected_year=2024, bbox=(-51, -9, -49, -7))


def test_archive_rejects_non_sirgas_2000_projection(tmp_path: Path) -> None:
    archive = _archive(tmp_path, [(_properties(), _geometry())], prj='GEOGCS["WGS 84"]')

    with pytest.raises(ValueError, match="SIRGAS 2000"):
        load_prodes_archive(archive, expected_year=2024, bbox=(-51, -9, -49, -7))


def test_archive_rejects_duplicate_feature_uuid(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path,
        [
            (_properties(fid=1), _geometry()),
            (_properties(fid=2), _geometry()),
        ],
    )

    with pytest.raises(ValueError, match="duplicate PRODES UUID"):
        load_prodes_archive(archive, expected_year=2024, bbox=(-51, -9, -49, -7))


def test_archive_decodes_the_official_windows_1252_text(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path,
        [
            (
                _properties(sub_class="corte raso com vegetação"),
                _geometry(),
            )
        ],
        encoding="cp1252",
    )

    features = load_prodes_archive(
        archive,
        expected_year=2024,
        bbox=(-51, -9, -49, -7),
    )

    assert len(features) == 1


def test_loads_an_extracted_shapefile_with_the_same_identity_checks(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path,
        [
            (_properties(), _geometry()),
            (
                _properties(fid=43, uuid="old", year=2023, class_name="d2023"),
                _geometry(),
            ),
        ],
        encoding="cp1252",
    )
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as source:
        source.extractall(extract_dir)
    shapefile_path = next(extract_dir.glob("*.shp"))

    features = load_prodes_shapefile(
        shapefile_path,
        expected_year=2024,
        bbox=(-51, -9, -49, -7),
    )

    assert [feature.uuid for feature in features] == ["264b9a88-e718-4ddc-b732-0ff5371b699f"]


def test_extracted_shapefile_rejects_missing_component(tmp_path: Path) -> None:
    archive = _archive(tmp_path, [(_properties(), _geometry())])
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as source:
        source.extractall(extract_dir)
    shapefile_path = next(extract_dir.glob("*.shp"))
    shapefile_path.with_suffix(".shx").unlink()

    with pytest.raises(ValueError, match="components"):
        load_prodes_shapefile(
            shapefile_path,
            expected_year=2024,
            bbox=(-51, -9, -49, -7),
        )
