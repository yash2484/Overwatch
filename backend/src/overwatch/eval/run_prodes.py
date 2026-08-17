"""Score the unchanged forest detector against five fixed PRODES 2024 windows.

The windows are stratified by PRODES clearing density and pinned before detector
scoring. Exact Sentinel-2 scenes bracket each window's PRODES acquisition dates.
"""

import argparse
import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from shapely.geometry import box

from overwatch.aois import AOI
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.models import Detection
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.eval.metrics import PixelScore, aggregate, score_masks
from overwatch.eval.prodes import (
    ProdesFeature,
    load_prodes_shapefile,
    prodes_truth_mask,
)
from overwatch.eval.rasterize import mask_from_geometries
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.masking import usable_fraction, usable_mask
from overwatch.imagery.models import AOIWindow, SceneMeta

DATA_DIR = Path("/app/data/benchmarks/prodes")
ARCHIVE = DATA_DIR / "yearly_deforestation_biome_amazonia_v20260717.zip"
SHAPEFILE = DATA_DIR / "yearly_deforestation_biome_amazonia_v20260717.shp"
OUTPUT_DIR = DATA_DIR / "results"
EXPECTED_ARCHIVE_SHA256 = "ffdf5e8f00cbc9f7f0ee9ed78ac2c7bbcc31c182c596205e353298b1cbf92fd4"
MIN_USABLE = 0.70
BANDS = ("red", "green", "blue", "nir")


@dataclass(frozen=True)
class BenchmarkWindow:
    slug: str
    bbox: tuple[float, float, float, float]
    truth_year: int
    before_stac_id: str
    after_stac_id: str

    @property
    def before_date(self) -> date:
        return _date_from_stac_id(self.before_stac_id)

    @property
    def after_date(self) -> date:
        return _date_from_stac_id(self.after_stac_id)


@dataclass(frozen=True)
class BenchmarkEvaluation:
    predicted: np.ndarray
    valid: np.ndarray
    score: PixelScore


BENCHMARK_WINDOWS = (
    BenchmarkWindow(
        slug="novo-progresso",
        bbox=(-55.5, -7.2, -55.4, -7.1),
        truth_year=2024,
        before_stac_id="S2A_21MXN_20230804_0_L2A",
        after_stac_id="S2B_21MXN_20240803_0_L2A",
    ),
    BenchmarkWindow(
        slug="low-medium",
        bbox=(-56.0, -3.7, -55.9, -3.6),
        truth_year=2024,
        before_stac_id="S2A_21MXS_20230827_0_L2A",
        after_stac_id="S2B_21MXS_20240826_0_L2A",
    ),
    BenchmarkWindow(
        slug="medium",
        bbox=(-54.2, -2.5, -54.1, -2.4),
        truth_year=2024,
        before_stac_id="S2A_21MZT_20230725_0_L2A",
        after_stac_id="S2B_21MZT_20240714_0_L2A",
    ),
    BenchmarkWindow(
        slug="high",
        bbox=(-55.8, -6.2, -55.7, -6.1),
        truth_year=2024,
        before_stac_id="S2B_21MXP_20230819_0_L2A",
        after_stac_id="S2A_21MXP_20240821_0_L2A",
    ),
    BenchmarkWindow(
        slug="very-high",
        bbox=(-54.8, -8.6, -54.7, -8.5),
        truth_year=2024,
        before_stac_id="S2A_21LYL_20230804_0_L2A",
        after_stac_id="S2B_21LYL_20240803_0_L2A",
    ),
)


def _date_from_stac_id(stac_id: str) -> date:
    try:
        value = stac_id.split("_")[2]
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid Sentinel-2 STAC id {stac_id!r}") from exc


def _load_exact_window(
    provider: EarthSearchProvider,
    aoi: AOI,
    day: date,
    expected_stac_id: str,
) -> tuple[SceneMeta, AOIWindow, float]:
    scenes = provider.search_scenes(
        aoi.geometry(),
        day,
        day + timedelta(days=1),
        max_cloud_pct=100.0,
    )
    scene = next((candidate for candidate in scenes if candidate.stac_id == expected_stac_id), None)
    if scene is None:
        found = sorted(candidate.stac_id for candidate in scenes)
        raise RuntimeError(f"expected Earth Search scene {expected_stac_id}; found {found}")
    window = harmonize_window(provider.read_window(scene, aoi.geometry(), BANDS), scene)
    fraction = usable_fraction(window.scl)
    if fraction < MIN_USABLE:
        raise RuntimeError(
            f"scene {scene.stac_id} has {fraction:.1%} usable pixels; requires {MIN_USABLE:.0%}"
        )
    return scene, window, fraction


def _validate_truth_dates(
    features: list[ProdesFeature],
    *,
    before: date,
    after: date,
) -> None:
    if not features:
        raise ValueError("no PRODES features intersect the benchmark window")
    outside = sorted(
        {feature.image_date for feature in features if not before <= feature.image_date <= after}
    )
    if outside:
        raise ValueError(
            f"PRODES acquisition dates outside Sentinel-2 interval {before}..{after}: {outside}"
        )


def _score_detections(
    detections: list[Detection],
    before: AOIWindow,
    after: AOIWindow,
    truth: np.ndarray,
) -> BenchmarkEvaluation:
    valid = usable_mask(before.scl) & usable_mask(after.scl)
    predicted = mask_from_geometries(
        [detection.geometry for detection in detections],
        shape=truth.shape,
        transform=before.transform,
    )
    return BenchmarkEvaluation(
        predicted=predicted,
        valid=valid,
        score=score_masks(predicted, truth, valid),
    )


def _verify_sha256(path: Path, *, expected: str = EXPECTED_ARCHIVE_SHA256) -> str:
    if not path.exists():
        raise FileNotFoundError(f"missing official PRODES archive: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"PRODES archive SHA-256 mismatch: expected {expected}, found {actual}")
    return actual


def _score_dict(score: PixelScore) -> dict[str, int | float]:
    return {
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
        "iou": score.iou,
        "tp": score.tp,
        "fp": score.fp,
        "fn": score.fn,
        "tn": score.tn,
    }


def _assert_unchanged_forest_preset() -> None:
    preset = VERTICAL_PRESETS["forest"]
    rules = {(rule.map, rule.direction, rule.threshold) for rule in preset.rules}
    expected = {
        ("ndvi", "decrease", 0.15),
        ("ndvi_before", "increase", 0.50),
    }
    if rules != expected or preset.primary_map != "ndvi" or preset.min_area_m2 != 3_000.0:
        raise RuntimeError(
            "forest preset differs from the benchmark's pinned shipped configuration"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    archive_sha256 = _verify_sha256(args.archive)
    _assert_unchanged_forest_preset()
    combined_bbox = (
        min(window.bbox[0] for window in BENCHMARK_WINDOWS),
        min(window.bbox[1] for window in BENCHMARK_WINDOWS),
        max(window.bbox[2] for window in BENCHMARK_WINDOWS),
        max(window.bbox[3] for window in BENCHMARK_WINDOWS),
    )
    with tempfile.TemporaryDirectory(prefix="prodes-verified-") as extracted_dir:
        shapefile_path = _extract_verified_archive(args.archive, Path(extracted_dir))
        all_features = load_prodes_shapefile(
            shapefile_path,
            expected_year=2024,
            bbox=combined_bbox,
        )

        provider = EarthSearchProvider()
        scores: list[PixelScore] = []
        summaries: list[dict[str, object]] = []
        for specification in BENCHMARK_WINDOWS:
            footprint = box(*specification.bbox)
            features = [
                feature for feature in all_features if feature.geometry.intersects(footprint)
            ]
            _validate_truth_dates(
                features,
                before=specification.before_date,
                after=specification.after_date,
            )
            aoi = AOI(
                slug=f"prodes-{specification.slug}",
                name=f"PRODES benchmark {specification.slug}",
                vertical="forest",
                bbox=specification.bbox,
            )
            before_meta, before, before_usable = _load_exact_window(
                provider,
                aoi,
                specification.before_date,
                specification.before_stac_id,
            )
            after_meta, after, after_usable = _load_exact_window(
                provider,
                aoi,
                specification.after_date,
                specification.after_stac_id,
            )
            truth = prodes_truth_mask(
                features,
                shape=before.scl.shape,
                transform=before.transform,
                epsg=before.epsg,
            )
            detections = ClassicalChangeDetector().detect(
                before,
                after,
                VERTICAL_PRESETS["forest"],
            )
            evaluation = _score_detections(detections, before, after, truth)
            scores.append(evaluation.score)
            valid_truth = truth & evaluation.valid
            pixel_area_m2 = abs(before.transform.a * before.transform.e)
            summaries.append(
                {
                    "slug": specification.slug,
                    "bbox": list(specification.bbox),
                    "truth_year": specification.truth_year,
                    "truth_features": len(features),
                    "truth_acquisition_dates": sorted(
                        {feature.image_date.isoformat() for feature in features}
                    ),
                    "truth_area_ha_on_valid_pixels": (
                        np.count_nonzero(valid_truth) * pixel_area_m2 / 10_000
                    ),
                    "before": {
                        "stac_id": before_meta.stac_id,
                        "captured_at": before_meta.captured_at.isoformat(),
                        "usable_fraction": before_usable,
                    },
                    "after": {
                        "stac_id": after_meta.stac_id,
                        "captured_at": after_meta.captured_at.isoformat(),
                        "usable_fraction": after_usable,
                    },
                    "valid_fraction": float(
                        np.count_nonzero(evaluation.valid) / evaluation.valid.size
                    ),
                    "detections": len(detections),
                    "emitted_area_ha": sum(detection.area_m2 for detection in detections) / 10_000,
                    "score": _score_dict(evaluation.score),
                }
            )
            print(
                f"{specification.slug}: precision={evaluation.score.precision:.3f} "
                f"recall={evaluation.score.recall:.3f} F1={evaluation.score.f1:.3f} "
                f"IoU={evaluation.score.iou:.3f}"
            )

    micro = aggregate(scores)
    summary = {
        "benchmark": "INPE TerraBrasilis PRODES Amazon annual increments",
        "archive_sha256": archive_sha256,
        "truth_year": 2024,
        "windows": summaries,
        "micro_average": _score_dict(micro),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(
        f"MICRO over {len(scores)} windows: precision={micro.precision:.3f} "
        f"recall={micro.recall:.3f} F1={micro.f1:.3f} IoU={micro.iou:.3f}"
    )
    print(f"artifacts={args.output_dir}")


def _extract_verified_archive(archive: Path, destination: Path) -> Path:
    """Extract only the single verified Shapefile product named by the archive."""
    with zipfile.ZipFile(archive) as source:
        members = [Path(info.filename) for info in source.infolist() if not info.is_dir()]
        components = [
            member
            for member in members
            if member.suffix.lower() in {".shp", ".shx", ".dbf", ".prj"}
        ]
        if len(components) != 4 or {member.suffix.lower() for member in components} != {
            ".shp",
            ".shx",
            ".dbf",
            ".prj",
        }:
            raise ValueError("verified PRODES archive must contain exactly one complete Shapefile")
        if len({member.stem for member in components}) != 1:
            raise ValueError("verified PRODES archive components do not share one basename")
        for member in components:
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"unsafe PRODES archive member {member}")
        source.extractall(destination)
        return destination / next(
            member for member in components if member.suffix.lower() == ".shp"
        )


if __name__ == "__main__":
    main()
