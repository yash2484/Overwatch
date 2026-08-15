"""Strict decoding and rasterisation of EMSN194 P04 flood truth."""

import json
from datetime import date, datetime, timezone

import numpy as np
import pytest
from affine import Affine
from pyproj import Transformer
from shapely.geometry import Polygon

from overwatch.aois import AOI
from overwatch.detection.models import ChangeType, Detection
from overwatch.eval.emsn194 import decode_flood_extent, flood_truth_mask
from overwatch.eval.run_emsn194 import (
    AFTER_STAC_ID,
    BEFORE_STAC_ID,
    BENCHMARK_BBOX,
    EXPECTED_ARCHIVE_SHA256,
    MIN_USABLE,
    _load_exact_window,
    _score_detections,
    _verify_sha256,
)
from overwatch.imagery.models import AOIWindow, SceneMeta


class _ProviderStub:
    def __init__(self, scenes: list[SceneMeta], window: AOIWindow) -> None:
        self.scenes = scenes
        self.window = window
        self.search_calls: list[dict[str, object]] = []
        self.read_calls: list[tuple[str, tuple[str, ...]]] = []

    def search_scenes(self, geometry, start, end, *, max_cloud_pct):
        self.search_calls.append(
            {
                "geometry": geometry,
                "start": start,
                "end": end,
                "max_cloud_pct": max_cloud_pct,
            }
        )
        return self.scenes

    def read_window(self, scene, geometry, bands):
        self.read_calls.append((scene.stac_id, tuple(bands)))
        return self.window


def _scene(stac_id: str) -> SceneMeta:
    return SceneMeta(
        stac_id=stac_id,
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 5, 8, 13, 30, tzinfo=timezone.utc),
        cloud_pct=100.0,
        epsg=32622,
        assets={},
    )


def _window(scl: np.ndarray) -> AOIWindow:
    bands = {name: np.ones(scl.shape, dtype=np.uint16) for name in ("red", "green", "blue", "nir")}
    return AOIWindow(bands=bands, scl=scl, transform=Affine(1, 0, 0, 0, -1, scl.shape[0]), epsg=32622)


def _feature_collection(
    geometry: dict | None = None,
    **property_overrides: str,
) -> bytes:
    properties = {
        "aoi_id": "01",
        "source_dat": "08/05/2024",
        "det_method": "Semi-automatic extraction",
        "flood_type": "Inland flood",
        "notation": "Rain",
        "area_ha": "1.0",
    }
    properties.update(property_overrides)
    return json.dumps(
        {
            "type": "FeatureCollection",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": [
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": geometry
                    or {
                        "type": "MultiPolygon",
                        "coordinates": [[[[0, 2], [1, 2], [1, 1], [0, 1], [0, 2]]]],
                    },
                }
            ],
        }
    ).encode()


def test_decodes_date_matched_observed_flood_extent() -> None:
    geometries = decode_flood_extent(_feature_collection())

    assert len(geometries) == 1
    assert geometries[0].geom_type == "MultiPolygon"
    assert geometries[0].bounds == (0.0, 1.0, 1.0, 2.0)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"aoi_id": "02"}, "AOI"),
        ({"source_dat": "21/05/2024"}, "date"),
        ({"det_method": "Hydraulic model"}, "method"),
        ({"flood_type": "Maximum water extent"}, "flood type"),
    ],
)
def test_rejects_truth_with_mismatched_semantics(override: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        decode_flood_extent(_feature_collection(**override))


def test_rejects_a_non_feature_collection() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        decode_flood_extent(json.dumps({"type": "Feature"}).encode())


def test_rejects_truth_without_the_exact_crs84_declaration() -> None:
    document = json.loads(_feature_collection())
    document["crs"]["properties"]["name"] = "EPSG:3857"

    with pytest.raises(ValueError, match="CRS84"):
        decode_flood_extent(json.dumps(document).encode())


def test_repairs_a_polygonal_ring_self_intersection() -> None:
    invalid_self_intersection = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [0, 2], [0, 0]]],
    }

    geometries = decode_flood_extent(_feature_collection(invalid_self_intersection))

    assert len(geometries) == 1
    assert geometries[0].is_valid
    assert geometries[0].geom_type == "MultiPolygon"


def test_rasterises_truth_on_the_detector_grid() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.00001, 0], [0.00001, 0.00001], [0, 0.00001], [0, 0]]],
    }
    project = Transformer.from_crs(4326, 3857, always_xy=True)
    left, bottom = project.transform(0, 0)
    right, top = project.transform(0.00001, 0.00001)
    area_ha = ((right - left) * (top - bottom)) / 10_000
    mask = flood_truth_mask(
        _feature_collection(geometry, area_ha=str(area_ha)),
        shape=(1, 1),
        transform=Affine(right - left, 0, left, 0, -(top - bottom), top),
        epsg=3857,
    )

    assert mask.dtype == np.bool_
    assert mask.tolist() == [[True]]


def test_rejects_geometry_that_disagrees_with_the_official_area() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.00001, 0], [0.00001, 0.00001], [0, 0.00001], [0, 0]]],
    }

    with pytest.raises(ValueError, match="official area"):
        flood_truth_mask(
            _feature_collection(geometry, area_ha="10"),
            shape=(1, 1),
            transform=Affine(2, 0, 0, 0, -2, 2),
            epsg=3857,
        )


def test_expected_date_is_explicit() -> None:
    with pytest.raises(ValueError, match="date"):
        decode_flood_extent(_feature_collection(), expected_date=date(2024, 5, 6))


def test_benchmark_identity_is_fixed_independently_of_the_demo_configuration() -> None:
    assert BENCHMARK_BBOX == (-51.300, -30.080, -51.180, -29.980)
    assert BEFORE_STAC_ID == "S2A_22JDM_20240418_0_L2A"
    assert AFTER_STAC_ID == "S2A_22JDM_20240508_0_L2A"
    assert len(EXPECTED_ARCHIVE_SHA256) == 64


def test_load_exact_window_selects_pinned_scene_and_caps_catalog_cloud_filter() -> None:
    aoi = AOI(
        slug="benchmark",
        name="benchmark",
        vertical="flood",
        bbox=BENCHMARK_BBOX,
    )
    expected = _scene(AFTER_STAC_ID)
    provider = _ProviderStub(
        scenes=[_scene("other-scene"), expected],
        window=_window(np.full((2, 2), 4, dtype=np.uint8)),
    )

    scene, window, fraction = _load_exact_window(
        provider,
        aoi,
        date(2024, 5, 8),
        AFTER_STAC_ID,
    )

    assert scene == expected
    assert window is provider.window
    assert fraction == 1.0
    assert provider.search_calls[0]["start"] == date(2024, 5, 8)
    assert provider.search_calls[0]["end"] == date(2024, 5, 9)
    assert provider.search_calls[0]["max_cloud_pct"] == 100.0
    assert provider.read_calls == [(AFTER_STAC_ID, ("red", "green", "blue", "nir"))]


def test_load_exact_window_rejects_below_minimum_usable_fraction() -> None:
    aoi = AOI(slug="benchmark", name="benchmark", vertical="flood", bbox=BENCHMARK_BBOX)
    provider = _ProviderStub(
        scenes=[_scene(AFTER_STAC_ID)],
        window=_window(np.full((2, 2), 9, dtype=np.uint8)),
    )

    with pytest.raises(RuntimeError, match=f"requires {MIN_USABLE:.0%}"):
        _load_exact_window(provider, aoi, date(2024, 5, 8), AFTER_STAC_ID)

    assert provider.read_calls == [(AFTER_STAC_ID, ("red", "green", "blue", "nir"))]


@pytest.mark.parametrize("returned_id", ["wrong-scene", "another-scene"])
def test_load_exact_window_rejects_missing_pinned_scene(returned_id: str) -> None:
    aoi = AOI(slug="benchmark", name="benchmark", vertical="flood", bbox=BENCHMARK_BBOX)
    provider = _ProviderStub(
        scenes=[_scene(returned_id)],
        window=_window(np.full((2, 2), 4, dtype=np.uint8)),
    )

    with pytest.raises(RuntimeError, match=AFTER_STAC_ID):
        _load_exact_window(provider, aoi, date(2024, 5, 8), AFTER_STAC_ID)

    assert provider.read_calls == []


def test_archive_hash_must_match_before_scoring(tmp_path) -> None:
    archive = tmp_path / "truth.zip"
    archive.write_bytes(b"official bytes")

    digest = _verify_sha256(archive, expected=EXPECTED_ARCHIVE_SHA256, enforce=False)

    assert len(digest) == 64
    with pytest.raises(ValueError, match="SHA-256"):
        _verify_sha256(archive, expected=EXPECTED_ARCHIVE_SHA256, enforce=True)


def test_scores_emitted_polygons_only_where_both_scenes_are_valid() -> None:
    transform = Affine(1, 0, 0, 0, -1, 2)
    bands = {name: np.ones((2, 2), dtype=np.uint16) for name in ("red", "green", "blue", "nir")}
    before = AOIWindow(
        bands=bands,
        scl=np.full((2, 2), 4, dtype=np.uint8),
        transform=transform,
        epsg=32631,
    )
    after = AOIWindow(
        bands=bands,
        scl=np.array([[9, 4], [4, 4]], dtype=np.uint8),
        transform=transform,
        epsg=32631,
    )
    detection = Detection(
        geometry=Polygon([(0, 2), (2, 2), (2, 1), (0, 1), (0, 2)]),
        epsg=32631,
        area_m2=2.0,
        change_type=ChangeType.FLOODING,
        magnitude=0.5,
        confidence=1.0,
        contributing_indices={"ndwi": 0.5},
    )
    truth = np.array([[True, True], [False, False]])

    evaluation = _score_detections([detection], before, after, truth)

    assert evaluation.valid.tolist() == [[False, True], [True, True]]
    assert evaluation.predicted.tolist() == [[True, True], [False, False]]
    assert evaluation.score.tp == 1
    assert evaluation.score.fp == 0
    assert evaluation.score.fn == 0
    assert evaluation.score.tn == 2
