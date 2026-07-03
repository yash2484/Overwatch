"""Phase 1 ingestion CLI: search -> gate -> mask -> PNG -> persist.

Run in-container:
    docker compose exec api python -m overwatch.imagery.cli \
        --aoi vizhinjam --start 2021-01-01 --end 2021-03-31
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from overwatch.aois import SHOWCASE_AOIS
from overwatch.db.engine import session_scope
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.gating import find_usable_scene
from overwatch.imagery.render import render_rgb_png


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Overwatch Phase 1 imagery ingestion")
    parser.add_argument("--aoi", required=True, choices=sorted(SHOWCASE_AOIS))
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--max-cloud", type=float, default=60.0)
    parser.add_argument("--min-usable", type=float, default=0.7)
    parser.add_argument("--out-dir", type=Path, default=Path("/app/data"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    aoi = SHOWCASE_AOIS[args.aoi]
    geometry = aoi.geometry()

    selection = find_usable_scene(
        EarthSearchProvider(),
        geometry,
        args.start,
        args.end,
        max_cloud_pct=args.max_cloud,
        min_usable=args.min_usable,
    )
    if selection is None:
        print(
            f"NO USABLE SCENE for {aoi.slug} {args.start}..{args.end} "
            f"(widened +60d, min usable {args.min_usable:.0%})"
        )
        return 1

    scene = selection.scene
    png = render_rgb_png(
        selection.window,
        args.out_dir / f"{aoi.slug}_{scene.captured_at:%Y%m%d}_{scene.stac_id}.png",
    )
    with session_scope() as session:
        row_id = upsert_scene(
            session,
            scene,
            aoi.slug,
            geometry,
            usable_fraction=selection.usable_fraction,
            meta={
                "assets": scene.assets,
                "window_shape": list(selection.window.bands["red"].shape),
            },
        )
    print(
        f"scene={scene.stac_id} captured={scene.captured_at:%Y-%m-%d} "
        f"cloud={scene.cloud_pct:.1f}% usable={selection.usable_fraction:.1%} "
        f"row_id={row_id} png={png}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
