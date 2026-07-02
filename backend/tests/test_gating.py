import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np
from affine import Affine
from shapely.geometry import box

from overwatch.imagery.gating import find_usable_scene
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.imagery.provider import SceneCoverageError

GEOM = box(76.96, 8.355, 77.01, 8.395)


def _scene(stac_id: str, day: int, cloud: float, month: int = 1) -> SceneMeta:
    return SceneMeta(
        stac_id=stac_id,
        collection="sentinel-2-l2a",
        captured_at=datetime(2021, month, day, 5, 30, tzinfo=UTC),
        cloud_pct=cloud,
        epsg=32643,
        assets={"red": "https://example/B04.tif"},
    )


def _window(scl_class: int) -> AOIWindow:
    shape = (4, 4)
    return AOIWindow(
        bands={b: np.ones(shape, dtype=np.uint16) for b in ("red", "green", "blue")},
        scl=np.full(shape, scl_class, dtype=np.uint8),
        transform=Affine.identity(),
        epsg=32643,
    )


@dataclass
class FakeProvider:
    scenes: list[SceneMeta]
    windows: dict[str, AOIWindow | Exception]

    def __post_init__(self) -> None:
        self.read_calls: list[str] = []

    def search_scenes(self, geometry, start, end, *, max_cloud_pct):
        return [
            s
            for s in self.scenes
            if start <= s.captured_at.date() <= end and s.cloud_pct < max_cloud_pct
        ]

    def read_window(self, scene, geometry, bands):
        self.read_calls.append(scene.stac_id)
        result = self.windows[scene.stac_id]
        if isinstance(result, Exception):
            raise result
        return result


def test_clear_scene_in_original_window_selected() -> None:
    provider = FakeProvider(scenes=[_scene("a", 5, 10.0)], windows={"a": _window(4)})
    sel = find_usable_scene(provider, GEOM, date(2021, 1, 1), date(2021, 1, 31))
    assert sel is not None and sel.scene.stac_id == "a"
    assert sel.usable_fraction == 1.0


def test_scl_gate_skips_scene_that_metadata_calls_clear(caplog) -> None:
    # "b" claims 5% cloud but its SCL is all cloud; "c" is honest and clear.
    provider = FakeProvider(
        scenes=[_scene("b", 5, 5.0), _scene("c", 10, 20.0)],
        windows={"b": _window(9), "c": _window(4)},
    )
    with caplog.at_level(logging.INFO):
        sel = find_usable_scene(provider, GEOM, date(2021, 1, 1), date(2021, 1, 31))
    assert sel is not None and sel.scene.stac_id == "c"
    assert provider.read_calls == ["b", "c"]  # cloud-ascending order, gate did the work
    assert any("skipping b" in r.message for r in caplog.records)


def test_widening_finds_scene_outside_original_window() -> None:
    provider = FakeProvider(
        scenes=[_scene("late", 10, 5.0, month=2)],  # Feb 10, outside Jan window
        windows={"late": _window(4)},
    )
    sel = find_usable_scene(provider, GEOM, date(2021, 1, 1), date(2021, 1, 31))
    assert sel is not None and sel.scene.stac_id == "late"


def test_no_usable_scene_returns_none_and_reads_each_once() -> None:
    provider = FakeProvider(
        scenes=[_scene("x", 5, 10.0), _scene("y", 15, 20.0)],
        windows={"x": _window(9), "y": _window(8)},
    )
    sel = find_usable_scene(provider, GEOM, date(2021, 1, 1), date(2021, 1, 31))
    assert sel is None
    assert sorted(provider.read_calls) == ["x", "y"]  # seen-set prevents re-reads


def test_partial_coverage_scene_is_skipped() -> None:
    provider = FakeProvider(
        scenes=[_scene("edge", 5, 5.0), _scene("full", 10, 10.0)],
        windows={"edge": SceneCoverageError("window exceeds raster"), "full": _window(4)},
    )
    sel = find_usable_scene(provider, GEOM, date(2021, 1, 1), date(2021, 1, 31))
    assert sel is not None and sel.scene.stac_id == "full"
