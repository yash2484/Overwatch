"""Score the shipped flood detector on date-matched EMSN194 Porto Alegre truth.

The live demo remains untouched. This runner reads Earth Search COG windows directly,
uses the fixed 2024-04-18 -> 2024-05-08 scene pair, rasterises EMSN194 P04 FLDEL02
observed-flood polygons, and scores the polygons the detector emits.

    docker compose run --rm --no-deps api \
        python -m overwatch.eval.run_emsn194
"""

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform as transform_geometry

from overwatch.aois import AOI
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.indices import ndwi
from overwatch.detection.models import Detection
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.eval.emsn194 import flood_truth_mask
from overwatch.eval.metrics import PixelScore, score_masks
from overwatch.eval.rasterize import mask_from_geometries
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.masking import usable_fraction, usable_mask
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.imagery.render import render_rgb_png, stretch_to_uint8

DATA_DIR = Path("/app/data/benchmarks/emsn194")
ARCHIVE = DATA_DIR / "EMSN194_GeospatialData.zip"
OUTPUT_DIR = DATA_DIR / "results"
FLOOD_EXTENT_MEMBER = (
    "GeospatialData/Geojson/P04/EMSN194_STD_AOI01_P04FLDEL02_FloodExtent_v01.geojson"
)
BEFORE_DATE = date(2024, 4, 18)
AFTER_DATE = date(2024, 5, 8)
BEFORE_STAC_ID = "S2A_22JDM_20240418_0_L2A"
AFTER_STAC_ID = "S2A_22JDM_20240508_0_L2A"
BENCHMARK_BBOX = (-51.300, -30.080, -51.180, -29.980)
EXPECTED_ARCHIVE_SHA256 = "7d61dc66b3440db52ae89a33b415ac2273078278792636a11a37873573db8877"
BANDS = ("red", "green", "blue", "nir")
MIN_USABLE = 0.7


@dataclass(frozen=True)
class BenchmarkEvaluation:
    predicted: np.ndarray
    valid: np.ndarray
    score: PixelScore


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
    window = provider.read_window(scene, aoi.geometry(), BANDS)
    fraction = usable_fraction(window.scl)
    if fraction < MIN_USABLE:
        raise RuntimeError(
            f"scene {scene.stac_id} has {fraction:.1%} usable pixels; requires {MIN_USABLE:.0%}"
        )
    return scene, harmonize_window(window, scene), fraction


def _read_truth(archive: Path) -> bytes:
    if not archive.exists():
        raise FileNotFoundError(f"missing official EMSN194 archive: {archive}")
    with zipfile.ZipFile(archive) as source:
        return source.read(FLOOD_EXTENT_MEMBER)


def _write_mask(path: Path, mask: np.ndarray, window: AOIWindow) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=mask.shape[1],
        height=mask.shape[0],
        count=1,
        dtype="uint8",
        crs=f"EPSG:{window.epsg}",
        transform=window.transform,
        compress="deflate",
    ) as target:
        target.write(mask.astype(np.uint8), 1)


def _render_comparison(
    window: AOIWindow,
    predicted: np.ndarray,
    truth: np.ndarray,
    valid: np.ndarray,
    path: Path,
) -> None:
    rgb = np.dstack(
        [
            stretch_to_uint8(window.bands[band].astype(np.float32), gamma=0.75, fixed_max=3000)
            for band in ("red", "green", "blue")
        ]
    )
    overlays = (
        (truth & predicted & valid, np.array([30, 220, 80], dtype=np.float32)),
        (truth & ~predicted & valid, np.array([0, 220, 255], dtype=np.float32)),
        (predicted & ~truth & valid, np.array([255, 45, 45], dtype=np.float32)),
    )
    rendered = rgb.astype(np.float32)
    rendered[~valid] *= 0.35
    for mask, colour in overlays:
        rendered[mask] = rendered[mask] * 0.35 + colour * 0.65
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rendered.astype(np.uint8), mode="RGB").save(path)


def _write_predictions(path: Path, detections: list[Detection], epsg: int) -> None:
    project = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    features = []
    for detection in detections:
        geometry = transform_geometry(project, detection.geometry)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {
                    "change_type": detection.change_type,
                    "area_m2": detection.area_m2,
                    "magnitude": detection.magnitude,
                    "confidence": detection.confidence,
                },
            }
        )
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
        encoding="utf-8",
    )


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


def _verify_sha256(
    path: Path,
    *,
    expected: str = EXPECTED_ARCHIVE_SHA256,
    enforce: bool = True,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if enforce and actual != expected:
        raise ValueError(f"EMSN194 archive SHA-256 mismatch: expected {expected}, found {actual}")
    return actual


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    archive_sha256 = _verify_sha256(args.archive)
    aoi = AOI(
        slug="porto-alegre-emsn194-benchmark",
        name="Porto Alegre EMSN194 benchmark",
        vertical="flood",
        bbox=BENCHMARK_BBOX,
    )
    provider = EarthSearchProvider()
    before_meta, before, before_usable = _load_exact_window(
        provider, aoi, BEFORE_DATE, BEFORE_STAC_ID
    )
    after_meta, after, after_usable = _load_exact_window(provider, aoi, AFTER_DATE, AFTER_STAC_ID)

    detections = ClassicalChangeDetector().detect(before, after, VERTICAL_PRESETS["flood"])
    truth = flood_truth_mask(
        _read_truth(args.archive),
        shape=before.scl.shape,
        transform=before.transform,
        epsg=before.epsg,
    )
    evaluation = _score_detections(detections, before, after, truth)
    predicted, valid, headline = (
        evaluation.predicted,
        evaluation.valid,
        evaluation.score,
    )

    # P04 is already an event-flood layer. These two variants are sensitivity checks only,
    # included to show that residual overlap with before-scene water does not drive the score.
    before_ndwi_water = np.nan_to_num(ndwi(before.bands), nan=-1.0) > -0.05
    before_scl_water = before.scl == 6
    minus_ndwi = score_masks(predicted, truth & ~before_ndwi_water, valid)
    minus_scl = score_masks(predicted, truth & ~before_scl_water, valid)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    render_rgb_png(before, output / "before.png", gamma=0.75, fixed_max=3000)
    render_rgb_png(after, output / "after.png", gamma=0.75, fixed_max=3000)
    _render_comparison(after, predicted, truth, valid, output / "comparison.png")
    _write_mask(output / "truth.tif", truth, before)
    _write_mask(output / "predicted.tif", predicted, before)
    _write_mask(output / "valid.tif", valid, before)
    _write_predictions(output / "predictions.geojson", detections, before.epsg)

    valid_truth = truth & valid
    truth_pixels = int(np.count_nonzero(valid_truth))
    pixel_area_m2 = abs(before.transform.a * before.transform.e)
    summary = {
        "benchmark": "Copernicus EMSN194 AOI01 P04 FLDEL02",
        "truth_semantics": "Observed event flood extent; no permanent-water subtraction",
        "aoi": {"slug": aoi.slug, "bbox": list(aoi.bbox)},
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
        "grid": {
            "shape": list(truth.shape),
            "epsg": before.epsg,
            "transform": list(before.transform)[:6],
            "pixel_area_m2": pixel_area_m2,
        },
        "archive": {
            "path": str(args.archive),
            "member": FLOOD_EXTENT_MEMBER,
            "sha256": archive_sha256,
        },
        "detections": {
            "count": len(detections),
            "emitted_area_ha": sum(d.area_m2 for d in detections) / 10_000,
        },
        "truth_area_ha_on_valid_pixels": truth_pixels * pixel_area_m2 / 10_000,
        "valid_fraction": float(np.count_nonzero(valid) / valid.size),
        "headline": _score_dict(headline),
        "sensitivity": {
            "truth_overlap_before_ndwi_water_pct": (
                100 * np.count_nonzero(valid_truth & before_ndwi_water) / truth_pixels
            ),
            "minus_before_ndwi_water": _score_dict(minus_ndwi),
            "truth_overlap_before_scl_water_pct": (
                100 * np.count_nonzero(valid_truth & before_scl_water) / truth_pixels
            ),
            "minus_before_scl_water": _score_dict(minus_scl),
        },
        "comparison_legend": {
            "green": "truth and prediction",
            "cyan": "truth only (false negative)",
            "red": "prediction only (false positive)",
            "dimmed": "invalid due to cloud, shadow, snow, saturation, or no-data",
        },
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"EMSN194 Porto Alegre {BEFORE_DATE} -> {AFTER_DATE}: "
        f"precision={headline.precision:.3f} recall={headline.recall:.3f} "
        f"F1={headline.f1:.3f} IoU={headline.iou:.3f}"
    )
    print(
        f"detections={len(detections)} "
        f"emitted_area={summary['detections']['emitted_area_ha']:.1f} ha "
        f"truth_on_valid={summary['truth_area_ha_on_valid_pixels']:.1f} ha "
        f"valid={summary['valid_fraction']:.1%}"
    )
    print(f"artifacts={output}")


if __name__ == "__main__":
    main()
