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


def test_offset_applied_and_clipped() -> None:
    window = flat_window(FOREST)
    out = harmonize_window(window, _meta(-1000))
    assert out is not window
    assert out.bands["red"].dtype == np.float32
    assert float(out.bands["red"].min()) >= 0.0
    np.testing.assert_allclose(
        out.bands["nir"], np.clip(window.bands["nir"].astype(np.float32) - 1000, 0, None)
    )
    assert out.transform == window.transform and out.epsg == window.epsg


def test_zero_offset_is_noop() -> None:
    window = flat_window(FOREST)
    assert harmonize_window(window, _meta(0)) is window
