"""Phase 2 detection CLI: two dated scenes -> detections + overlay PNG.

Run in-container:
    docker compose exec api python -m overwatch.detection.cli \
        --aoi vizhinjam --before 2021-02-12 --after 2025-02-11
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from overwatch.aois import AOI, SHOWCASE_AOIS
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.overlay import render_detections_png
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.models import AOIWindow, SceneMeta

BANDS = ("red", "green", "blue", "nir")


def _load_window(
    provider: EarthSearchProvider, aoi: AOI, day: date
) -> tuple[SceneMeta, AOIWindow]:
    scenes = provider.search_scenes(
        aoi.geometry(), day, day + timedelta(days=1), max_cloud_pct=100.0
    )
    if not scenes:
        raise SystemExit(f"no scene for {aoi.slug} on {day}")
    scene = scenes[0]
    window = provider.read_window(scene, aoi.geometry(), BANDS)
    if scene.dn_offset:
        window = AOIWindow(
            bands={
                k: np.clip(v.astype(np.float32) + scene.dn_offset, 0, None)
                for k, v in window.bands.items()
            },
            scl=window.scl,
            transform=window.transform,
            epsg=window.epsg,
        )
    return scene, window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Overwatch Phase 2 change detection")
    parser.add_argument("--aoi", required=True, choices=sorted(SHOWCASE_AOIS))
    parser.add_argument("--before", required=True, type=date.fromisoformat)
    parser.add_argument("--after", required=True, type=date.fromisoformat)
    parser.add_argument("--out-dir", type=Path, default=Path("/app/data"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    aoi = SHOWCASE_AOIS[args.aoi]
    provider = EarthSearchProvider()
    before_scene, before = _load_window(provider, aoi, args.before)
    after_scene, after = _load_window(provider, aoi, args.after)
    print(
        f"before={before_scene.stac_id} (baseline offset {before_scene.dn_offset}) "
        f"after={after_scene.stac_id} (baseline offset {after_scene.dn_offset})"
    )

    preset = VERTICAL_PRESETS[aoi.vertical]
    detections = ClassicalChangeDetector().detect(before, after, preset)
    png = render_detections_png(
        after,
        detections,
        args.out_dir / f"{aoi.slug}_{args.before}_{args.after}_detections.png",
    )
    for det in sorted(detections, key=lambda d: d.area_m2, reverse=True):
        centroid = det.geometry.centroid
        print(
            f"type={det.change_type} area_m2={det.area_m2:.0f} "
            f"magnitude={det.magnitude:.3f} confidence={det.confidence:.2f} "
            f"centroid=({centroid.x:.0f}, {centroid.y:.0f})"
        )
    print(f"detections={len(detections)} png={png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
