"""Score the shipped change detector against the OSCD benchmark.

Reads the two archives published with the dataset (images + labels) straight from disk,
runs `ClassicalChangeDetector` with a real preset, rasterises the polygons it emits, and
compares them to the hand-drawn change masks.

What this number is: the accuracy of the **construction** detector, end to end, including
morphology and the min-area floor — i.e. what a consumer of `/aois/{slug}/detections`
would actually get. What it is not: a measure of the vegetation or water presets. OSCD
labels urban change only.

    docker compose exec -T api python -m overwatch.eval.run_oscd --split test
"""

import argparse
import zipfile
from pathlib import Path

import numpy as np
import rasterio

from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.presets import VERTICAL_PRESETS, DetectionPreset
from overwatch.eval.metrics import PixelScore, aggregate, score_masks
from overwatch.eval.oscd import MSI_BAND_COUNT, MSI_BAND_INDEX, decode_cm, window_from_msi
from overwatch.eval.rasterize import mask_from_geometries

DATA_DIR = Path("/app/data/oscd")
IMAGES_ZIP = DATA_DIR / "Onera Satellite Change Detection dataset - Images.zip"
LABELS_ZIP = {
    "train": DATA_DIR / "Onera Satellite Change Detection dataset - Train Labels.zip",
    "test": DATA_DIR / "Onera Satellite Change Detection dataset - Test Labels.zip",
}
IMAGES_ROOT = "Onera Satellite Change Detection dataset - Images"
LABELS_ROOT = {
    "train": "Onera Satellite Change Detection dataset - Train Labels",
    "test": "Onera Satellite Change Detection dataset - Test Labels",
}

# The `_rect` folders hold the coregistered pair on a single grid. The raw imgs_1/imgs_2
# are at native per-band resolution and are NOT pixel-aligned, so they cannot be differenced.
_RECT = {1: "imgs_1_rect", 2: "imgs_2_rect"}


def _read_band(zf: zipfile.ZipFile, city: str, side: int, band: str) -> np.ndarray:
    raw = zf.read(f"{IMAGES_ROOT}/{city}/{_RECT[side]}/{band}.tif")
    with rasterio.MemoryFile(raw) as mem, mem.open() as ds:
        return ds.read(1)


# Written out rather than derived from the plane index: the "+1" rule that maps 1->B02
# holds only up to B08, because B8A sits between B08 and B09. An explicit map cannot drift.
BAND_FILE = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08"}


def load_window(zf: zipfile.ZipFile, city: str, side: int):
    """Build an AOIWindow for one side of a pair, reading only the bands presets use."""
    planes: dict[int, np.ndarray] = {}
    for name, idx in MSI_BAND_INDEX.items():
        planes[idx] = _read_band(zf, city, side, BAND_FILE[name])
    shape = next(iter(planes.values())).shape
    stack = np.zeros((MSI_BAND_COUNT, *shape), dtype=np.uint16)
    for idx, plane in planes.items():
        stack[idx] = plane
    return window_from_msi(stack)


def load_truth(split: str, city: str) -> np.ndarray:
    with zipfile.ZipFile(LABELS_ZIP[split]) as zf:
        raw = zf.read(f"{LABELS_ROOT[split]}/{city}/cm/{city}-cm.tif")
    with rasterio.MemoryFile(raw) as mem, mem.open() as ds:
        return decode_cm(ds.read(1))


def cities(split: str) -> list[str]:
    with zipfile.ZipFile(IMAGES_ZIP) as zf:
        listing = zf.read(f"{IMAGES_ROOT}/{split}.txt").decode()
    return [c for c in (s.strip() for s in listing.split(",")) if c]


def score_city(zf: zipfile.ZipFile, split: str, city: str, preset: DetectionPreset) -> PixelScore:
    before, after = load_window(zf, city, 1), load_window(zf, city, 2)
    truth = load_truth(split, city)
    detections = ClassicalChangeDetector().detect(before, after, preset)
    predicted = mask_from_geometries(
        [d.geometry for d in detections], shape=truth.shape, transform=before.transform
    )
    return score_masks(predicted, truth)


def _sweep(split: str, preset: DetectionPreset, thresholds: list[float]) -> None:
    """Re-score the split at several primary-map thresholds.

    A single operating point invites the question "was that value chosen to flatter the
    benchmark?". The shipped threshold was set on the Vizhinjam imagery months before this
    dataset was downloaded; the curve lets a reader confirm it is an ordinary point on it.
    """
    primary = preset.primary_map
    shipped = _primary_threshold(preset)
    print(f"OSCD {split} — sweeping '{primary}' threshold (shipped value: {shipped})")
    print(f"{'threshold':>10s} {'prec':>7s} {'recall':>7s} {'F1':>7s} {'IoU':>7s}")
    with zipfile.ZipFile(IMAGES_ZIP) as zf:
        for t in thresholds:
            tuned = preset.model_copy(
                update={
                    "rules": [
                        r.model_copy(update={"threshold": t}) if r.map == primary else r
                        for r in preset.rules
                    ]
                }
            )
            micro = aggregate([score_city(zf, split, c, tuned) for c in cities(split)])
            print(
                f"{t:10.2f} {micro.precision:7.3f} {micro.recall:7.3f} "
                f"{micro.f1:7.3f} {micro.iou:7.3f}"
            )


def _primary_threshold(preset: DetectionPreset) -> float:
    return next(r.threshold for r in preset.rules if r.map == preset.primary_map)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("train", "test"), default="test")
    parser.add_argument("--preset", default="port", choices=sorted(VERTICAL_PRESETS))
    parser.add_argument(
        "--sweep",
        nargs="*",
        type=float,
        help="also sweep the primary threshold, to show where the shipped value sits on "
        "the precision/recall curve rather than reporting a single point",
    )
    args = parser.parse_args()

    preset = VERTICAL_PRESETS[args.preset]
    if args.sweep is not None:
        _sweep(args.split, preset, args.sweep or [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70])
        return
    rule = ", ".join(f"{r.map} {r.direction} {r.threshold}" for r in preset.rules)
    print(
        f"OSCD {args.split} split — preset '{args.preset}' "
        f"({rule}; min_area {preset.min_area_m2:.0f} m2)"
    )
    print(f"{'city':16s} {'change%':>8s} {'prec':>7s} {'recall':>7s} {'F1':>7s} {'IoU':>7s}")

    scores: list[PixelScore] = []
    with zipfile.ZipFile(IMAGES_ZIP) as zf:
        for city in cities(args.split):
            s = score_city(zf, args.split, city, preset)
            scores.append(s)
            total = s.tp + s.fp + s.fn + s.tn
            pct = 100 * (s.tp + s.fn) / total if total else 0.0
            print(
                f"{city:16s} {pct:7.2f}% {s.precision:7.3f} {s.recall:7.3f} "
                f"{s.f1:7.3f} {s.iou:7.3f}"
            )

    micro = aggregate(scores)
    print(
        f"\nMICRO-AVERAGE over {len(scores)} scenes: "
        f"precision={micro.precision:.3f} recall={micro.recall:.3f} "
        f"F1={micro.f1:.3f} IoU={micro.iou:.3f}"
    )
    print(f"  pixels: tp={micro.tp:,} fp={micro.fp:,} fn={micro.fn:,} tn={micro.tn:,}")


if __name__ == "__main__":
    main()
