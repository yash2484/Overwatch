"""Forest benchmark identity, scene loading, and scoring behavior."""

from datetime import UTC, date, datetime

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Polygon

from overwatch.aois import AOI
from overwatch.detection.models import ChangeType, Detection
from overwatch.eval.prodes import ProdesFeature
from overwatch.eval.run_prodes import (
    BENCHMARK_WINDOWS,
    EXPECTED_ARCHIVE_SHA256,
    MIN_USABLE,
    _extract_verified_archive,
    _load_exact_window,
    _score_detections,
    _validate_truth_dates,
)
from overwatch.imagery.models import AOIWindow, SceneMeta


class _ProviderStub:
    def __init__(self, scenes: list[SceneMeta], window: AOIWindow) -> None:
        self.scenes = scenes
        self.window = window
        self.read_ids: list[str] = []

    def search_scenes(self, geometry, start, end, *, max_cloud_pct):
        return self.scenes

    def read_window(self, scene, geometry, bands):
        self.read_ids.append(scene.stac_id)
        return self.window


def _scene(stac_id: str, captured: date) -> SceneMeta:
    return SceneMeta(
        stac_id=stac_id,
        collection="sentinel-2-l2a",
        captured_at=datetime(captured.year, captured.month, captured.day, tzinfo=UTC),
        cloud_pct=0.0,
        epsg=32721,
        assets={},
    )


def _window(scl: np.ndarray) -> AOIWindow:
    bands = {name: np.ones(scl.shape, dtype=np.uint16) for name in ("red", "green", "blue", "nir")}
    return AOIWindow(
        bands=bands,
        scl=scl,
        transform=Affine(1, 0, 0, 0, -1, scl.shape[0]),
        epsg=32721,
    )


def _truth(day: date) -> ProdesFeature:
    return ProdesFeature(
        geometry=Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        year=2024,
        image_date=day,
        state="PA",
        area_m2=1.0,
        uuid=f"truth-{day.isoformat()}",
    )


def test_benchmark_identity_is_fixed_before_detector_scoring() -> None:
    assert len(BENCHMARK_WINDOWS) == 5
    assert [window.slug for window in BENCHMARK_WINDOWS] == [
        "novo-progresso",
        "low-medium",
        "medium",
        "high",
        "very-high",
    ]
    assert BENCHMARK_WINDOWS[0].before_stac_id == "S2A_21MXN_20230804_0_L2A"
    assert BENCHMARK_WINDOWS[0].after_stac_id == "S2B_21MXN_20240803_0_L2A"
    assert all(window.truth_year == 2024 for window in BENCHMARK_WINDOWS)
    assert len(EXPECTED_ARCHIVE_SHA256) == 64


def test_load_exact_window_selects_pinned_scene() -> None:
    expected = _scene("expected", date(2024, 8, 3))
    provider = _ProviderStub(
        [_scene("other", date(2024, 8, 3)), expected],
        _window(np.full((2, 2), 4, dtype=np.uint8)),
    )
    aoi = AOI(slug="benchmark", name="benchmark", vertical="forest", bbox=(-56, -8, -55, -7))

    scene, loaded, usable = _load_exact_window(provider, aoi, date(2024, 8, 3), "expected")

    assert scene == expected
    assert loaded is provider.window
    assert usable == 1.0
    assert provider.read_ids == ["expected"]


def test_load_exact_window_rejects_unusable_scene() -> None:
    provider = _ProviderStub(
        [_scene("expected", date(2024, 8, 3))],
        _window(np.full((2, 2), 9, dtype=np.uint8)),
    )
    aoi = AOI(slug="benchmark", name="benchmark", vertical="forest", bbox=(-56, -8, -55, -7))

    with pytest.raises(RuntimeError, match=f"requires {MIN_USABLE:.0%}"):
        _load_exact_window(provider, aoi, date(2024, 8, 3), "expected")


def test_truth_acquisitions_must_be_bracketed_by_sentinel_pair() -> None:
    _validate_truth_dates(
        [_truth(date(2024, 7, 29)), _truth(date(2024, 8, 3))],
        before=date(2023, 8, 4),
        after=date(2024, 8, 3),
    )

    with pytest.raises(ValueError, match="outside Sentinel-2 interval"):
        _validate_truth_dates(
            [_truth(date(2024, 8, 4))],
            before=date(2023, 8, 4),
            after=date(2024, 8, 3),
        )


def test_scores_emitted_polygons_only_on_dual_scene_valid_pixels() -> None:
    before = _window(np.full((2, 2), 4, dtype=np.uint8))
    after = _window(np.array([[9, 4], [4, 4]], dtype=np.uint8))
    detection = Detection(
        geometry=Polygon([(0, 2), (2, 2), (2, 1), (0, 1)]),
        epsg=32721,
        area_m2=2.0,
        change_type=ChangeType.VEGETATION_LOSS,
        magnitude=0.5,
        confidence=1.0,
        contributing_indices={"ndvi": -0.5},
    )
    truth = np.array([[True, True], [False, False]])

    evaluation = _score_detections([detection], before, after, truth)

    assert evaluation.valid.tolist() == [[False, True], [True, True]]
    assert evaluation.score.tp == 1
    assert evaluation.score.fp == 0
    assert evaluation.score.fn == 0
    assert evaluation.score.tn == 2


def test_extraction_returns_components_from_the_verified_archive(tmp_path) -> None:
    archive = tmp_path / "truth.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w") as source:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            source.writestr(f"truth{suffix}", f"{suffix} bytes")

    extracted = _extract_verified_archive(archive, tmp_path / "extracted")

    assert extracted.name == "truth.shp"
    assert extracted.read_bytes() == b".shp bytes"
    assert extracted.with_suffix(".prj").read_bytes() == b".prj bytes"
