import json
from pathlib import Path
from types import SimpleNamespace

import pystac
import pytest
from affine import Affine
from rasterio.windows import Window

from overwatch.imagery.earth_search import (
    _check_coverage,
    _epsg_from_props,
    boa_dn_offset,
    integer_window,
    scene_meta_from_item,
)
from overwatch.imagery.provider import SceneCoverageError

FIXTURE = Path(__file__).parent / "fixtures" / "earth_search_item.json"


def _item() -> pystac.Item:
    return pystac.Item.from_dict(json.loads(FIXTURE.read_text()))


def test_scene_meta_from_real_item() -> None:
    meta = scene_meta_from_item(_item())
    assert meta.stac_id and meta.collection == "sentinel-2-l2a"
    assert meta.captured_at.tzinfo is not None
    assert 0.0 <= meta.cloud_pct <= 100.0
    assert meta.epsg == 32643
    assert {"red", "green", "blue", "scl"} <= set(meta.assets)
    assert all(href.startswith("https://") for href in meta.assets.values())


def test_epsg_from_proj_epsg() -> None:
    assert _epsg_from_props({"proj:epsg": 32643}) == 32643


def test_epsg_from_proj_code() -> None:
    assert _epsg_from_props({"proj:code": "EPSG:32722"}) == 32722


def test_epsg_missing_raises() -> None:
    with pytest.raises(ValueError, match="proj"):
        _epsg_from_props({})


def test_integer_window_rounds_outward() -> None:
    # 10 m north-up UTM grid, origin (600000, 900000)
    transform = Affine(10.0, 0.0, 600000.0, 0.0, -10.0, 900000.0)
    win = integer_window((600005.0, 899975.0, 600035.0, 899995.0), transform)
    assert win == Window(0, 0, 4, 3)


def test_check_coverage_rejects_out_of_bounds() -> None:
    src = SimpleNamespace(width=100, height=100)
    with pytest.raises(SceneCoverageError):
        _check_coverage(Window(-1, 0, 50, 50), src)
    with pytest.raises(SceneCoverageError):
        _check_coverage(Window(60, 60, 50, 50), src)
    _check_coverage(Window(0, 0, 100, 100), src)  # exact fit passes


def test_boa_dn_offset_rules() -> None:
    # pre-04 baseline: no offset in the data
    assert boa_dn_offset({"s2:processing_baseline": "03.01"}) == 0
    # post-04 baseline, offset already removed by Earth Search reprocessing
    assert (
        boa_dn_offset({"s2:processing_baseline": "05.11", "earthsearch:boa_offset_applied": True})
        == 0
    )
    # post-04 baseline, offset still in the DNs -> subtract 1000
    assert (
        boa_dn_offset({"s2:processing_baseline": "05.11", "earthsearch:boa_offset_applied": False})
        == -1000
    )
    # missing metadata: assume no offset, log-worthy but non-fatal
    assert boa_dn_offset({}) == 0


def test_scene_meta_carries_dn_offset() -> None:
    item = _item()
    item.properties["s2:processing_baseline"] = "05.11"
    item.properties["earthsearch:boa_offset_applied"] = False
    assert scene_meta_from_item(item).dn_offset == -1000
    item.properties["earthsearch:boa_offset_applied"] = True
    assert scene_meta_from_item(item).dn_offset == 0
