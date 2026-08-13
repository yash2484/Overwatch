"""BOA offset harmonization shared by CLI and workers."""

from datetime import UTC, datetime

import numpy as np

from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.models import SceneMeta
from tests.synthetic import FOREST, flat_window


def _meta(dn_offset: int) -> SceneMeta:
    return SceneMeta(
        stac_id="t3-harm",
        collection="sentinel-2-l2a",
        captured_at=datetime(2025, 1, 1, tzinfo=UTC),
        cloud_pct=0.0,
        epsg=32643,
        assets={},
        dn_offset=dn_offset,
    )


def test_offset_removed_when_present() -> None:
    # DNs that actually carry the +1000 BOA offset (every band well above 1000). Harmonization
    # subtracts it, recovering reflectance-scale values.
    window = flat_window({name: dn + 1000 for name, dn in FOREST.items()})
    out = harmonize_window(window, _meta(-1000))
    assert out is not window
    assert out.bands["red"].dtype == np.float32
    assert float(out.bands["red"].min()) >= 0.0
    np.testing.assert_allclose(
        out.bands["nir"], np.clip(window.bands["nir"].astype(np.float32) - 1000, 0, None)
    )
    assert out.transform == window.transform and out.epsg == window.epsg


def test_offset_skipped_when_data_is_offset_free() -> None:
    # FOREST DNs are reflectance-scale (red ~400) — they do NOT carry a +1000 offset. A wrong
    # STAC flag (Sentinel-2C's earthsearch:boa_offset_applied=False) can still set
    # dn_offset=-1000; removing it would clip almost the whole scene to zero, so harmonization
    # must detect the data is already offset-free and skip it (return the window untouched).
    window = flat_window(FOREST)
    assert harmonize_window(window, _meta(-1000)) is window


def test_zero_offset_is_noop() -> None:
    window = flat_window(FOREST)
    assert harmonize_window(window, _meta(0)) is window
