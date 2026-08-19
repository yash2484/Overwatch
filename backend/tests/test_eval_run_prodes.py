"""Forest benchmark identity, scene loading, and scoring behavior."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

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
    _candidate_metadata,
    _diagnose_detections,
    _extract_verified_archive,
    _forest_preset,
    _load_exact_window,
    _load_windows,
    _run_is_candidate,
    _score_detections,
    _validate_candidate_output,
    _validate_truth_dates,
    _window_spec_dict,
    _write_diagnostics,
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


def test_load_windows_reads_predeclared_holdout_spec(tmp_path) -> None:
    spec = [
        {
            "slug": "holdout-low",
            "bbox": [-56.0, -3.7, -55.9, -3.6],
            "truth_year": 2024,
            "before_stac_id": "S2A_21MXS_20230827_0_L2A",
            "after_stac_id": "S2B_21MXS_20240826_0_L2A",
        }
    ]
    path = tmp_path / "holdout.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    windows = _load_windows(path)

    assert [window.slug for window in windows] == ["holdout-low"]
    assert windows[0].bbox == (-56.0, -3.7, -55.9, -3.6)
    assert windows[0].truth_year == 2024
    assert windows[0].before_stac_id == "S2A_21MXS_20230827_0_L2A"
    assert windows[0].after_stac_id == "S2B_21MXS_20240826_0_L2A"
    assert windows[0].before_date == date(2023, 8, 27)
    assert windows[0].after_date == date(2024, 8, 26)


@pytest.mark.parametrize(
    "spec",
    [
        [],
        "not-a-list",
        [{"bbox": [-56.0, -3.7, -55.9, -3.6], "truth_year": 2024}],
        [{"slug": "x", "bbox": [-56.0, -3.7, -55.9], "truth_year": 2024}],
        [{"slug": "x", "bbox": [-56.0, -3.7, -55.9, -3.6], "truth_year": 2024}],
        [
            {
                "slug": "x",
                "bbox": [-56.0, -3.7, -55.9, -3.6],
                "truth_year": 2024,
                "before_stac_id": "A",
            }
        ],
        [
            {
                "slug": "x",
                "bbox": [-56.0, -3.7, -55.9, -3.6],
                "truth_year": "2024",
                "before_stac_id": "A",
                "after_stac_id": "B",
            }
        ],
        [
            {
                "slug": "x",
                "bbox": [-56.0, -3.7, -55.9, -3.6],
                "truth_year": 2024,
                "before_stac_id": "",
                "after_stac_id": "B",
            }
        ],
    ],
)
def test_load_windows_rejects_malformed_spec(tmp_path, spec) -> None:
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ValueError):
        _load_windows(path)


def test_holdout_run_is_candidate_even_with_shipped_preset() -> None:
    assert _run_is_candidate(preset_modified=True, holdout=False)
    assert _run_is_candidate(preset_modified=False, holdout=True)
    assert _run_is_candidate(preset_modified=True, holdout=True)
    assert not _run_is_candidate(preset_modified=False, holdout=False)


def test_window_spec_dict_round_trips_a_predeclared_window() -> None:
    window = BENCHMARK_WINDOWS[0]

    assert _window_spec_dict(window) == {
        "slug": "novo-progresso",
        "bbox": [-55.5, -7.2, -55.4, -7.1],
        "truth_year": 2024,
        "before_stac_id": "S2A_21MXN_20230804_0_L2A",
        "after_stac_id": "S2B_21MXN_20240803_0_L2A",
    }


def test_forest_candidate_preset_changes_only_requested_absolute_floor() -> None:
    candidate = _forest_preset(ndvi_before_floor=0.60)

    assert {(rule.map, rule.direction, rule.threshold) for rule in candidate.rules} == {
        ("ndvi", "decrease", 0.15),
        ("ndvi_before", "increase", 0.60),
    }
    assert candidate.min_area_m2 == 3_000.0


def test_candidate_run_rejects_the_baseline_output_directory() -> None:
    with pytest.raises(ValueError, match="separate --output-dir"):
        _validate_candidate_output(
            output_dir=Path("/app/data/benchmarks/prodes/results"),
            candidate=True,
        )


def test_candidate_metadata_records_effective_preset_and_revision() -> None:
    metadata = _candidate_metadata(
        _forest_preset(ndvi_before_floor=0.65),
        detector_revision="d3d3375+working-tree",
    )

    assert metadata == {
        "detector_revision": "d3d3375+working-tree",
        "rules": [
            {"map": "ndvi", "direction": "decrease", "threshold": 0.15},
            {"map": "ndvi_before", "direction": "increase", "threshold": 0.65},
        ],
        "primary_map": "ndvi",
        "min_area_m2": 3_000.0,
    }


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


def test_diagnose_detections_classifies_false_positive_and_preserves_metadata() -> None:
    detection = Detection(
        geometry=Polygon([(2, 2), (4, 2), (4, 0), (2, 0)]),
        epsg=32721,
        area_m2=4.0,
        change_type=ChangeType.VEGETATION_LOSS,
        magnitude=0.42,
        confidence=0.75,
        contributing_indices={"ndvi": -0.3},
    )
    truth = np.zeros((2, 4), dtype=bool)
    valid = np.ones((2, 4), dtype=bool)
    before = _window(np.full((2, 4), 4, dtype=np.uint8))

    diagnostics = _diagnose_detections(
        [detection],
        truth=truth,
        valid=valid,
        shape=truth.shape,
        transform=before.transform,
    )

    assert diagnostics == [
        {
            "index": 0,
            "classification": "zero_truth_overlap",
            "area_m2": 4.0,
            "valid_pixels": 4,
            "truth_pixels": 0,
            "intersection_pixels": 0,
            "change_type": "vegetation_loss",
            "magnitude": 0.42,
            "confidence": 0.75,
            "contributing_indices": {"ndvi": -0.3},
        }
    ]


@pytest.mark.parametrize(
    ("truth", "valid", "expected"),
    [
        (
            np.array([[False, False, True, False], [False, False, False, False]]),
            np.ones((2, 4), dtype=bool),
            "partial_truth_overlap",
        ),
        (
            np.array([[False, False, True, True], [False, False, True, True]]),
            np.ones((2, 4), dtype=bool),
            "full_truth_overlap",
        ),
        (
            np.zeros((2, 4), dtype=bool),
            np.zeros((2, 4), dtype=bool),
            "no_valid_pixels",
        ),
    ],
)
def test_diagnose_detections_distinguishes_overlap_categories(
    truth: np.ndarray,
    valid: np.ndarray,
    expected: str,
) -> None:
    detection = Detection(
        geometry=Polygon([(2, 2), (4, 2), (4, 0), (2, 0)]),
        epsg=32721,
        area_m2=4.0,
        change_type=ChangeType.VEGETATION_LOSS,
        magnitude=0.42,
        confidence=0.75,
        contributing_indices={"ndvi": -0.3},
    )
    before = _window(np.full((2, 4), 4, dtype=np.uint8))

    diagnostics = _diagnose_detections(
        [detection],
        truth=truth,
        valid=valid,
        shape=truth.shape,
        transform=before.transform,
    )

    assert diagnostics[0]["classification"] == expected


def test_write_diagnostics_creates_separate_artifact_without_changing_summary(tmp_path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text('{"baseline": true}', encoding="utf-8")
    diagnostics = [{"slug": "novo-progresso", "detections": []}]

    _write_diagnostics(tmp_path, diagnostics)

    assert summary.read_text(encoding="utf-8") == '{"baseline": true}'
    assert json.loads((tmp_path / "diagnostics.json").read_text(encoding="utf-8")) == {
        "windows": diagnostics
    }


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
