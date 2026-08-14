"""Earth Search STAC provider (design spec §4). Asset keys verified in the Phase 1 spike."""

import math
from collections.abc import Sequence
from datetime import date

import numpy as np
import pystac
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

from overwatch.config import settings
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.imagery.provider import SceneCoverageError

COLLECTION = "sentinel-2-l2a"
SCL_ASSET = "scl"
_KEEP_ASSETS = ("red", "green", "blue", "nir", "scl")
_GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "5",
    "VSI_CACHE": "TRUE",
}


def _epsg_from_props(props: dict) -> int:
    """STAC proj extension: v1 uses proj:epsg (int), v2 uses proj:code ('EPSG:n')."""
    if props.get("proj:epsg"):
        return int(props["proj:epsg"])
    code = str(props.get("proj:code", ""))
    if code.startswith("EPSG:"):
        return int(code.removeprefix("EPSG:"))
    raise ValueError(f"item lacks proj:epsg/proj:code: {sorted(props)}")


def boa_dn_offset(props: dict) -> int:
    """-1000 when baseline >= 04.00 DNs still carry the BOA offset, else 0.

    Earth Search sets earthsearch:boa_offset_applied=True when its reprocessing
    already removed the offset; pre-04 baselines never had one.
    """
    try:
        baseline = float(props.get("s2:processing_baseline", "0"))
    except ValueError:
        baseline = 0.0
    if baseline >= 4.0 and not props.get("earthsearch:boa_offset_applied", False):
        return -1000
    return 0


def scene_meta_from_item(item: pystac.Item) -> SceneMeta:
    if item.datetime is None:
        raise ValueError(f"item {item.id} lacks a datetime")
    return SceneMeta(
        stac_id=item.id,
        collection=item.collection_id or COLLECTION,
        captured_at=item.datetime,
        cloud_pct=float(item.properties["eo:cloud_cover"]),
        epsg=_epsg_from_props(item.properties),
        assets={k: item.assets[k].href for k in _KEEP_ASSETS if k in item.assets},
        dn_offset=boa_dn_offset(item.properties),
    )


def integer_window(bounds: tuple[float, float, float, float], transform) -> Window:
    """from_bounds rounded outward to whole pixels — deterministic, fully covering reads."""
    win = from_bounds(*bounds, transform=transform)
    col_off = math.floor(win.col_off)
    row_off = math.floor(win.row_off)
    width = math.ceil(win.col_off + win.width) - col_off
    height = math.ceil(win.row_off + win.height) - row_off
    return Window(col_off, row_off, width, height)


def _check_coverage(win: Window, src) -> None:
    """Reject AOI windows that fall off the scene raster (partial tiles — PROJECT.md §6a)."""
    if (
        win.col_off < 0
        or win.row_off < 0
        or win.col_off + win.width > src.width
        or win.row_off + win.height > src.height
    ):
        raise SceneCoverageError(f"window {win} exceeds raster {src.width}x{src.height}")


class EarthSearchProvider:
    """ImageryProvider backed by Earth Search v1. No auth for search or COG reads."""

    def search_scenes(
        self, geometry: Polygon, start: date, end: date, *, max_cloud_pct: float
    ) -> list[SceneMeta]:
        client = Client.open(settings.stac_api_url)
        search = client.search(
            collections=[COLLECTION],
            intersects=geometry.__geo_interface__,
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            max_items=64,
            **(
                {"query": {"eo:cloud_cover": {"lt": max_cloud_pct}}}
                if max_cloud_pct < 100.0
                else {}
            ),
        )
        metas = [scene_meta_from_item(item) for item in search.items()]
        return sorted(metas, key=lambda m: m.captured_at)

    def read_window(self, scene: SceneMeta, geometry: Polygon, bands: Sequence[str]) -> AOIWindow:
        transformer = Transformer.from_crs(4326, scene.epsg, always_xy=True)
        bounds = shp_transform(transformer.transform, geometry).bounds
        out: dict[str, np.ndarray] = {}
        ref_transform = None
        shape: tuple[int, int] | None = None
        with rasterio.Env(**_GDAL_ENV):
            for band in bands:
                with rasterio.open(scene.assets[band]) as src:
                    win = integer_window(bounds, src.transform)
                    _check_coverage(win, src)
                    out[band] = src.read(1, window=win)
                    if ref_transform is None:
                        ref_transform = src.window_transform(win)
                        shape = out[band].shape
            with rasterio.open(scene.assets[SCL_ASSET]) as src:
                win = integer_window(bounds, src.transform)
                _check_coverage(win, src)
                scl = src.read(1, window=win, out_shape=shape, resampling=Resampling.nearest)
        assert ref_transform is not None  # bands is never empty
        return AOIWindow(bands=out, scl=scl, transform=ref_transform, epsg=scene.epsg)
