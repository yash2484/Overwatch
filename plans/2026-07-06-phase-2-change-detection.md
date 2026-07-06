# Phase 2 — Change Detection Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure, deterministic change-detection core: two co-registered `AOIWindow`s in → typed `Detection` polygons out, via spectral-index deltas + SSIM → thresholds → morphology → polygonization. No I/O, no LLM, TDD throughout.

**Architecture:** A new `overwatch.detection` package of small pure modules (indices, differencing, presets, postprocess, polygonize) composed by `ClassicalChangeDetector` behind a `ChangeDetector` protocol (design spec §4). Synthetic-raster fixtures drive the TDD suite; a thin CLI (the only I/O) runs the engine on the real Phase-1 Vizhinjam pair for the eyeball gate. Per-vertical thresholds live in preset configs, never hardcoded (design spec §6).

**Tech Stack:** Python 3.12 (in-container), numpy, scipy.ndimage (morphology), scikit-image (SSIM), rasterio.features (polygonization), shapely, pydantic v2, pytest.

## Global Constraints

- **Everything Python runs in-container**: `docker compose exec api pytest -v`, `docker compose exec api ruff check .` — never on the Windows host (roadmap §"How to run a phase session"). Start Docker Desktop first; it does not auto-start.
- **Branch:** `phase-2-change-detection`. Commit per task. The user merges via GitHub PR (direct push to main is denied; no `gh` CLI). Compare URL: `https://github.com/yash2484/Overwatch/compare/main...phase-2-change-detection`.
- **TDD:** red → green per task. Negative tests are first-class (design spec §8).
- **The engine is pure**: `overwatch/detection/*` must not import `pystac`, `sqlalchemy`, or open files/sockets. Only `detection/cli.py` and `detection/overlay.py` touch I/O (CLI: network reads; overlay: PNG writes).
- **Preset numbers from design spec §6** (verbatim): min detection area port **1,500 m²** / forest **5,000 m²** / flood **10,000 m²**; morphology opening-then-closing with kernel sizes in preset config. Thresholds are tunable engineering defaults — record any empirical tuning in this plan and PROGRESS.md, never claim them as verified numbers.
- **Style:** ruff line-length 100, rules E,F,I,UP,B,SIM; full type hints, `X | None`, `list[str]`; pydantic v2 for config models, dataclasses for array/geometry carriers (matches Phase 1's `AOIWindow`).
- Tests live flat in `backend/tests/` (existing convention). Shared synthetic-fixture helpers go in `backend/tests/synthetic.py` (importable from tests because pytest adds the test dir to `sys.path` — same mechanism the existing suite relies on).
- Existing Phase 1 interfaces consumed here (do not modify except where Task 9 says so):
  - `overwatch.imagery.models.AOIWindow` — `bands: dict[str, np.ndarray]`, `scl: np.ndarray`, `transform: Affine`, `epsg: int`.
  - `overwatch.imagery.masking.usable_mask(scl) -> np.ndarray[bool]`, `apply_mask(band, mask) -> float32 with NaN`.
  - `overwatch.imagery.render.stretch_to_uint8(band, low_pct=2.0, high_pct=98.0) -> uint8`.
  - `overwatch.imagery.earth_search.EarthSearchProvider.search_scenes(geometry, start, end, *, max_cloud_pct)` / `.read_window(scene, geometry, bands)`.
  - `overwatch.aois.SHOWCASE_AOIS: dict[str, AOI]` — AOI has `.slug`, `.vertical` (`"port" | "forest" | "flood"`), `.geometry()`.

---

### Task 1: Dependencies + detection package scaffold

scikit-image (SSIM) and scipy (morphology, labeling) enter the project here. scipy is a transitive dep of scikit-image but we import it directly, so declare it.

**Files:**
- Modify: `backend/pyproject.toml` (dependencies list)
- Create: `backend/src/overwatch/detection/__init__.py` (empty)

**Interfaces:**
- Consumes: nothing.
- Produces: importable `overwatch.detection` package; `skimage` + `scipy` available in the api/worker image.

- [ ] **Step 1: Add dependencies**

In `backend/pyproject.toml`, extend `[project].dependencies` (after `"alembic>=1.14",`):

```toml
    "scipy>=1.14",
    "scikit-image>=0.24",
```

- [ ] **Step 2: Create the package**

Create empty `backend/src/overwatch/detection/__init__.py`.

- [ ] **Step 3: Rebuild the backend image and restart**

Run: `docker compose up -d --build api worker beat`
Expected: services recreate cleanly (`Started`/`Running` for api, worker, beat).

- [ ] **Step 4: Verify the imports in-container**

Run: `docker compose exec api python -c "import scipy, skimage; from skimage.metrics import structural_similarity; from overwatch import detection; print(scipy.__version__, skimage.__version__)"`
Expected: two version strings printed, no traceback.

- [ ] **Step 5: Verify the existing suite still passes**

Run: `docker compose exec api pytest -q`
Expected: `32 passed` (Phase 1 baseline; DB tests need the postgis service, which compose provides).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/src/overwatch/detection/__init__.py
git commit -m "chore(phase-2): add scipy/scikit-image, detection package scaffold"
```

---

### Task 2: Spectral indices

Pure NaN-aware index functions over an `AOIWindow.bands`-shaped dict. NaN inputs (from `apply_mask`) and zero denominators must yield NaN, never raise or warn-spam.

**Files:**
- Create: `backend/src/overwatch/detection/indices.py`
- Test: `backend/tests/test_indices.py`

**Interfaces:**
- Consumes: nothing (numpy only).
- Produces: `ndvi(bands: dict[str, np.ndarray]) -> np.ndarray` (float32, needs `nir`+`red`), `ndwi(bands) -> np.ndarray` (needs `green`+`nir`), `nbr(bands) -> np.ndarray` (needs `nir`+`swir22`). Used by Task 8's detector.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for spectral index functions."""

import numpy as np
import pytest

from overwatch.detection.indices import ndvi, ndwi, nbr


def test_ndvi_known_value() -> None:
    bands = {"nir": np.array([[3000]], dtype=np.uint16), "red": np.array([[1000]], dtype=np.uint16)}
    assert ndvi(bands)[0, 0] == pytest.approx(0.5)


def test_ndwi_known_value() -> None:
    bands = {"green": np.array([[600]], dtype=np.uint16), "nir": np.array([[3400]], dtype=np.uint16)}
    assert ndwi(bands)[0, 0] == pytest.approx(-0.7)


def test_nbr_known_value() -> None:
    bands = {"nir": np.array([[3000]], dtype=np.uint16), "swir22": np.array([[1000]], dtype=np.uint16)}
    assert nbr(bands)[0, 0] == pytest.approx(0.5)


def test_zero_denominator_is_nan_not_error() -> None:
    bands = {"nir": np.zeros((2, 2), dtype=np.uint16), "red": np.zeros((2, 2), dtype=np.uint16)}
    assert np.isnan(ndvi(bands)).all()


def test_nan_input_propagates() -> None:
    nir = np.array([[np.nan, 3000.0]], dtype=np.float32)
    red = np.array([[1000.0, 1000.0]], dtype=np.float32)
    out = ndvi({"nir": nir, "red": red})
    assert np.isnan(out[0, 0]) and out[0, 1] == pytest.approx(0.5)


def test_output_is_float32_and_uint16_safe() -> None:
    # uint16 sums overflow if not upcast first: 40000 + 40000 > 65535.
    bands = {
        "nir": np.full((2, 2), 40_000, dtype=np.uint16),
        "red": np.full((2, 2), 40_000, dtype=np.uint16),
    }
    out = ndvi(bands)
    assert out.dtype == np.float32
    assert out[0, 0] == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_indices.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.indices'`

- [ ] **Step 3: Write the implementation**

```python
"""Spectral indices as pure NaN-aware functions (design spec §6)."""

import numpy as np


def _normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) as float32; NaN where the denominator is 0 or an input is NaN."""
    a32 = a.astype(np.float32)
    b32 = b.astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a32 - b32) / (a32 + b32)
    return out.astype(np.float32)


def ndvi(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Vegetation: (nir - red) / (nir + red)."""
    return _normalized_difference(bands["nir"], bands["red"])


def ndwi(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Open water (McFeeters): (green - nir) / (green + nir)."""
    return _normalized_difference(bands["green"], bands["nir"])


def nbr(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Burn ratio: (nir - swir22) / (nir + swir22)."""
    return _normalized_difference(bands["nir"], bands["swir22"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_indices.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/detection/indices.py backend/tests/test_indices.py
git commit -m "feat(phase-2): spectral index functions ndvi/ndwi/nbr (TDD)"
```

---

### Task 3: Synthetic AOIWindow fixture generator

The TDD backbone (design spec §8): build before/after window pairs with plausible Sentinel-2 L2A DN profiles and a known injected change rectangle. Deterministic (seeded rng); noise makes SSIM behave realistically (identical noise fields would give SSIM ≡ 1.0).

**Files:**
- Create: `backend/tests/synthetic.py`
- Test: `backend/tests/test_synthetic.py`

**Interfaces:**
- Consumes: `AOIWindow` from `overwatch.imagery.models`.
- Produces (imported by later test files as `from synthetic import ...`):
  - Profiles: `FOREST`, `BARE`, `WATER`, `BUILT` (`dict[str, int]` of band DNs), `TRANSFORM_10M: Affine`, `EPSG: int`, `SCL_VEGETATION = 4`, `SCL_CLOUD_HIGH = 9`.
  - `flat_window(profile, shape=(120, 120), *, scl_class=4, noise=40.0, seed=7) -> AOIWindow`
  - `inject_rect(window, profile, rect, *, scl_class=None, noise=40.0, seed=11) -> tuple[int, int, int, int]` — rect is `(row0, row1, col0, col1)`, mutates `window` in place.
  - `rect_geometry(rect) -> shapely.Polygon` — the rect's footprint in `TRANSFORM_10M`/UTM coords, for IoU assertions.

- [ ] **Step 1: Write the generator**

```python
"""Synthetic AOIWindow pairs with a known injected change (design spec §8).

DN profiles approximate Sentinel-2 L2A surface reflectance * 10000.
"""

import numpy as np
from affine import Affine
from shapely.geometry import Polygon, box

from overwatch.imagery.models import AOIWindow

FOREST = {"red": 400, "green": 600, "blue": 300, "nir": 3500}
BARE = {"red": 2200, "green": 1900, "blue": 1500, "nir": 2600}
WATER = {"red": 300, "green": 500, "blue": 600, "nir": 150}
BUILT = {"red": 2600, "green": 2400, "blue": 2200, "nir": 2300}

TRANSFORM_10M = Affine(10.0, 0.0, 500_000.0, 0.0, -10.0, 1_000_000.0)
EPSG = 32643  # UTM 43N (Vizhinjam's zone); any projected CRS works
SCL_VEGETATION = 4
SCL_CLOUD_HIGH = 9


def flat_window(
    profile: dict[str, int],
    shape: tuple[int, int] = (120, 120),
    *,
    scl_class: int = SCL_VEGETATION,
    noise: float = 40.0,
    seed: int = 7,
) -> AOIWindow:
    """Uniform landcover + deterministic Gaussian noise on the 10 m grid."""
    rng = np.random.default_rng(seed)
    bands = {
        name: np.clip(rng.normal(dn, noise, shape), 0, 10_000).astype(np.uint16)
        for name, dn in profile.items()
    }
    scl = np.full(shape, scl_class, dtype=np.uint8)
    return AOIWindow(bands=bands, scl=scl, transform=TRANSFORM_10M, epsg=EPSG)


def inject_rect(
    window: AOIWindow,
    profile: dict[str, int],
    rect: tuple[int, int, int, int],
    *,
    scl_class: int | None = None,
    noise: float = 40.0,
    seed: int = 11,
) -> tuple[int, int, int, int]:
    """Overwrite rows r0:r1, cols c0:c1 with another landcover. Mutates window in place."""
    r0, r1, c0, c1 = rect
    rng = np.random.default_rng(seed)
    for name, dn in profile.items():
        patch = np.clip(rng.normal(dn, noise, (r1 - r0, c1 - c0)), 0, 10_000)
        window.bands[name][r0:r1, c0:c1] = patch.astype(np.uint16)
    if scl_class is not None:
        window.scl[r0:r1, c0:c1] = scl_class
    return rect


def rect_geometry(rect: tuple[int, int, int, int]) -> Polygon:
    """The injected rect's footprint in TRANSFORM_10M map coordinates."""
    r0, r1, c0, c1 = rect
    x0, y0 = TRANSFORM_10M * (c0, r0)  # upper-left corner
    x1, y1 = TRANSFORM_10M * (c1, r1)  # lower-right corner
    return box(x0, y1, x1, y0)
```

- [ ] **Step 2: Write tests pinning the generator's guarantees**

```python
"""The synthetic generator itself must be trustworthy — pin its spectral guarantees."""

import numpy as np

from overwatch.detection.indices import ndvi, ndwi
from synthetic import (
    BARE,
    FOREST,
    SCL_CLOUD_HIGH,
    WATER,
    flat_window,
    inject_rect,
    rect_geometry,
)


def test_profiles_have_expected_index_signatures() -> None:
    forest = flat_window(FOREST, seed=1)
    bare = flat_window(BARE, seed=2)
    water = flat_window(WATER, seed=3)
    assert np.nanmean(ndvi(forest.bands)) > 0.6
    assert np.nanmean(ndvi(bare.bands)) < 0.2
    assert np.nanmean(ndwi(water.bands)) > 0.4
    assert np.nanmean(ndwi(bare.bands)) < 0.0


def test_flat_window_is_deterministic() -> None:
    a = flat_window(FOREST, seed=5)
    b = flat_window(FOREST, seed=5)
    assert all(np.array_equal(a.bands[k], b.bands[k]) for k in a.bands)


def test_inject_rect_changes_only_the_rect() -> None:
    window = flat_window(FOREST, seed=1)
    pristine = {k: v.copy() for k, v in window.bands.items()}
    inject_rect(window, BARE, (40, 50, 30, 50))
    outside = np.ones((120, 120), dtype=bool)
    outside[40:50, 30:50] = False
    for k in window.bands:
        assert np.array_equal(window.bands[k][outside], pristine[k][outside])
        assert not np.array_equal(window.bands[k][40:50, 30:50], pristine[k][40:50, 30:50])


def test_inject_rect_can_set_scl() -> None:
    window = flat_window(FOREST, seed=1)
    inject_rect(window, BARE, (40, 50, 30, 50), scl_class=SCL_CLOUD_HIGH)
    assert (window.scl[40:50, 30:50] == SCL_CLOUD_HIGH).all()
    assert (window.scl[0:40, :] != SCL_CLOUD_HIGH).all()


def test_rect_geometry_maps_pixels_to_utm() -> None:
    geom = rect_geometry((40, 50, 30, 50))
    assert geom.bounds == (500_300.0, 999_500.0, 500_500.0, 999_600.0)
    assert geom.area == 200 * 100.0  # 200 px * 100 m² each
```

- [ ] **Step 3: Run the tests**

Run: `docker compose exec api pytest tests/test_synthetic.py -q`
Expected: `5 passed`

- [ ] **Step 4: Commit**

```bash
git add backend/tests/synthetic.py backend/tests/test_synthetic.py
git commit -m "test(phase-2): synthetic AOIWindow fixture generator"
```

---

### Task 4: Index deltas + SSIM dissimilarity map

**Files:**
- Create: `backend/src/overwatch/detection/differencing.py`
- Test: `backend/tests/test_differencing.py`

**Interfaces:**
- Consumes: numpy, `skimage.metrics.structural_similarity`.
- Produces: `index_delta(before: np.ndarray, after: np.ndarray) -> np.ndarray` (float32, after − before, NaN-propagating) and `ssim_dissimilarity(before, after, *, data_range=10_000.0) -> np.ndarray` (float32 in [0, 2]; NaNs zero-filled before SSIM — callers must mask unusable pixels downstream). Used by Task 8.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for change maps: index deltas and SSIM dissimilarity."""

import numpy as np
import pytest

from overwatch.detection.differencing import index_delta, ssim_dissimilarity
from synthetic import BUILT, FOREST, flat_window, inject_rect


def test_index_delta_is_after_minus_before() -> None:
    before = np.array([[0.8, 0.2]], dtype=np.float32)
    after = np.array([[0.1, np.nan]], dtype=np.float32)
    out = index_delta(before, after)
    assert out[0, 0] == pytest.approx(-0.7)
    assert np.isnan(out[0, 1])
    assert out.dtype == np.float32


def test_ssim_dissimilarity_low_for_same_landcover() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)  # different noise, same landcover
    dissim = ssim_dissimilarity(before.bands["red"], after.bands["red"])
    assert dissim.shape == before.bands["red"].shape
    assert float(np.mean(dissim)) < 0.2


def test_ssim_dissimilarity_high_inside_changed_patch() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    inject_rect(after, BUILT, (40, 50, 30, 50))
    dissim = ssim_dissimilarity(before.bands["red"], after.bands["red"])
    inside = float(np.mean(dissim[42:48, 33:47]))  # patch interior, clear of the 7px window edge
    outside = float(np.mean(dissim[0:30, 0:30]))
    assert inside > 0.35
    assert outside < 0.2


def test_ssim_dissimilarity_tolerates_nan() -> None:
    before = flat_window(FOREST, seed=1).bands["red"].astype(np.float32)
    after = flat_window(FOREST, seed=2).bands["red"].astype(np.float32)
    before[0:10, 0:10] = np.nan
    out = ssim_dissimilarity(before, after)
    assert np.isfinite(out).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_differencing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.differencing'`

- [ ] **Step 3: Write the implementation**

```python
"""Change maps between two co-registered windows (design spec §6)."""

import numpy as np
from skimage.metrics import structural_similarity


def index_delta(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """after - before as float32. NaN wherever either side is NaN."""
    return (after.astype(np.float32) - before.astype(np.float32)).astype(np.float32)


def ssim_dissimilarity(
    before: np.ndarray, after: np.ndarray, *, data_range: float = 10_000.0
) -> np.ndarray:
    """1 - local SSIM, in [0, 2]. NaNs are zero-filled first; mask their pixels downstream."""
    b = np.nan_to_num(before.astype(np.float32), nan=0.0)
    a = np.nan_to_num(after.astype(np.float32), nan=0.0)
    _, ssim_map = structural_similarity(b, a, data_range=data_range, full=True)
    return (1.0 - ssim_map).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_differencing.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/detection/differencing.py backend/tests/test_differencing.py
git commit -m "feat(phase-2): index deltas + SSIM dissimilarity map (TDD)"
```

---

### Task 5: Detection model + per-vertical presets

The typed output object and the tunable config that keeps every threshold out of the code (design spec §6).

**Files:**
- Create: `backend/src/overwatch/detection/models.py`
- Create: `backend/src/overwatch/detection/presets.py`
- Test: `backend/tests/test_presets.py`

**Interfaces:**
- Consumes: `ChangeType` ↔ shapely `Polygon`.
- Produces (used by Tasks 6–10):
  - `models.ChangeType` — StrEnum: `CONSTRUCTION = "construction"`, `VEGETATION_LOSS = "vegetation_loss"`, `FLOODING = "flooding"`.
  - `models.Detection` — dataclass: `geometry: Polygon` (window's projected CRS), `epsg: int`, `area_m2: float`, `change_type: ChangeType`, `magnitude: float`, `confidence: float`, `contributing_indices: dict[str, float]`.
  - `presets.ThresholdRule` — pydantic: `map: Literal["ndvi", "ndwi", "nbr", "ssim_dissim"]`, `direction: Literal["decrease", "increase"]`, `threshold: float > 0`.
  - `presets.DetectionPreset` — pydantic: `vertical: str`, `change_type: ChangeType`, `rules: list[ThresholdRule]` (min 1, AND semantics), `primary_map` (must appear in rules — validated), `min_area_m2: float > 0`, `morph_open_px: int = 3`, `morph_close_px: int = 3`, `ssim_band: str = "red"`.
  - `presets.VERTICAL_PRESETS: dict[str, DetectionPreset]` with keys `"port"`, `"forest"`, `"flood"`.

- [ ] **Step 1: Write the failing tests**

```python
"""Preset configs carry every tunable number; the spec's floor values are pinned here."""

import pytest
from pydantic import ValidationError

from overwatch.aois import SHOWCASE_AOIS
from overwatch.detection.models import ChangeType
from overwatch.detection.presets import VERTICAL_PRESETS, DetectionPreset, ThresholdRule


def test_spec_minimum_areas() -> None:
    assert VERTICAL_PRESETS["port"].min_area_m2 == 1_500.0
    assert VERTICAL_PRESETS["forest"].min_area_m2 == 5_000.0
    assert VERTICAL_PRESETS["flood"].min_area_m2 == 10_000.0


def test_change_types_per_vertical() -> None:
    assert VERTICAL_PRESETS["port"].change_type is ChangeType.CONSTRUCTION
    assert VERTICAL_PRESETS["forest"].change_type is ChangeType.VEGETATION_LOSS
    assert VERTICAL_PRESETS["flood"].change_type is ChangeType.FLOODING


def test_every_showcase_vertical_has_a_preset() -> None:
    assert {a.vertical for a in SHOWCASE_AOIS.values()} <= set(VERTICAL_PRESETS)


def test_primary_map_must_have_a_rule() -> None:
    with pytest.raises(ValidationError):
        DetectionPreset(
            vertical="x",
            change_type=ChangeType.FLOODING,
            rules=[ThresholdRule(map="ndwi", direction="increase", threshold=0.2)],
            primary_map="ndvi",
            min_area_m2=1.0,
        )


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ThresholdRule(map="ndvi", direction="decrease", threshold=0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_presets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.models'`

- [ ] **Step 3: Write `models.py`**

```python
"""Typed detection outputs (design spec §4)."""

from dataclasses import dataclass
from enum import StrEnum

from shapely.geometry import Polygon


class ChangeType(StrEnum):
    CONSTRUCTION = "construction"
    VEGETATION_LOSS = "vegetation_loss"
    FLOODING = "flooding"


@dataclass
class Detection:
    """One change-event polygon, in the source window's projected CRS."""

    geometry: Polygon
    epsg: int
    area_m2: float
    change_type: ChangeType
    magnitude: float  # mean |primary-map delta| over the polygon's pixels
    confidence: float  # fraction of polygon pixels exceeding the primary threshold, [0, 1]
    contributing_indices: dict[str, float]  # change-map name -> mean value over the polygon
```

- [ ] **Step 4: Write `presets.py`**

```python
"""Per-vertical detection presets (design spec §6) — tunable defaults, never hardcoded."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from overwatch.detection.models import ChangeType

MapName = Literal["ndvi", "ndwi", "nbr", "ssim_dissim"]


class ThresholdRule(BaseModel):
    """One gate on a change map; a preset's rules are AND-ed (conservative by construction)."""

    map: MapName
    direction: Literal["decrease", "increase"]
    threshold: float = Field(gt=0)


class DetectionPreset(BaseModel):
    vertical: str
    change_type: ChangeType
    rules: list[ThresholdRule] = Field(min_length=1)
    primary_map: MapName  # magnitude/confidence are computed from this map
    min_area_m2: float = Field(gt=0)
    morph_open_px: int = 3
    morph_close_px: int = 3
    ssim_band: str = "red"  # band the ssim_dissim map is computed from

    @model_validator(mode="after")
    def _primary_map_has_rule(self) -> "DetectionPreset":
        if self.primary_map not in {rule.map for rule in self.rules}:
            raise ValueError(f"primary_map {self.primary_map!r} has no ThresholdRule")
        return self


VERTICAL_PRESETS: dict[str, DetectionPreset] = {
    "port": DetectionPreset(
        vertical="port",
        change_type=ChangeType.CONSTRUCTION,
        rules=[
            ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.35),
            ThresholdRule(map="ndvi", direction="decrease", threshold=0.10),
        ],
        primary_map="ssim_dissim",
        min_area_m2=1_500.0,
    ),
    "forest": DetectionPreset(
        vertical="forest",
        change_type=ChangeType.VEGETATION_LOSS,
        rules=[ThresholdRule(map="ndvi", direction="decrease", threshold=0.20)],
        primary_map="ndvi",
        min_area_m2=5_000.0,
    ),
    "flood": DetectionPreset(
        vertical="flood",
        change_type=ChangeType.FLOODING,
        rules=[ThresholdRule(map="ndwi", direction="increase", threshold=0.20)],
        primary_map="ndwi",
        min_area_m2=10_000.0,
    ),
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_presets.py -q`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/detection/models.py backend/src/overwatch/detection/presets.py backend/tests/test_presets.py
git commit -m "feat(phase-2): Detection model + per-vertical preset configs"
```

---

### Task 6: Threshold rules + morphological cleanup

Raw boolean change mask: AND of every rule, AND usable pixels (NaN comparisons are False, so masked pixels fail rules naturally — the explicit `usable` AND makes the intent auditable). Then opening (drop speckle) → closing (fill pinholes), per design spec §6 order.

**Files:**
- Create: `backend/src/overwatch/detection/postprocess.py`
- Test: `backend/tests/test_postprocess.py`

**Interfaces:**
- Consumes: `ThresholdRule` from Task 5.
- Produces: `rule_mask(maps: dict[str, np.ndarray], rules: list[ThresholdRule], usable: np.ndarray) -> np.ndarray[bool]` and `clean_mask(mask, *, open_px: int, close_px: int) -> np.ndarray[bool]`. Used by Task 8.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for thresholding and morphological cleanup."""

import numpy as np

from overwatch.detection.postprocess import clean_mask, rule_mask
from overwatch.detection.presets import ThresholdRule


def _maps(shape: tuple[int, int] = (20, 20)) -> dict[str, np.ndarray]:
    ndvi = np.zeros(shape, dtype=np.float32)
    ndvi[5:10, 5:10] = -0.5
    dissim = np.zeros(shape, dtype=np.float32)
    dissim[5:10, 5:12] = 0.8
    return {"ndvi": ndvi, "ssim_dissim": dissim}


def test_single_decrease_rule() -> None:
    rules = [ThresholdRule(map="ndvi", direction="decrease", threshold=0.2)]
    out = rule_mask(_maps(), rules, usable=np.ones((20, 20), dtype=bool))
    assert out[7, 7] and not out[0, 0]
    assert np.count_nonzero(out) == 25


def test_rules_are_anded() -> None:
    rules = [
        ThresholdRule(map="ndvi", direction="decrease", threshold=0.2),
        ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.35),
    ]
    out = rule_mask(_maps(), rules, usable=np.ones((20, 20), dtype=bool))
    assert np.count_nonzero(out) == 25  # ndvi box is the intersection
    assert not out[7, 11]  # dissim-only column fails the ndvi rule


def test_unusable_and_nan_pixels_never_pass() -> None:
    maps = _maps()
    maps["ndvi"][5, 5] = np.nan
    usable = np.ones((20, 20), dtype=bool)
    usable[6, 6] = False
    rules = [ThresholdRule(map="ndvi", direction="decrease", threshold=0.2)]
    out = rule_mask(maps, rules, usable)
    assert not out[5, 5] and not out[6, 6] and out[7, 7]


def test_opening_removes_speckle() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[3, 3] = True  # single-pixel noise
    mask[10:16, 10:16] = True  # real region
    out = clean_mask(mask, open_px=3, close_px=3)
    assert not out[3, 3]
    assert out[12, 12]


def test_closing_fills_pinhole() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True
    mask[9, 9] = False  # pinhole
    out = clean_mask(mask, open_px=3, close_px=3)
    assert out[9, 9]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_postprocess.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.postprocess'`

- [ ] **Step 3: Write the implementation**

```python
"""Threshold -> morphology: the raw-mask stage before polygonization (design spec §6)."""

import numpy as np
from scipy import ndimage

from overwatch.detection.presets import ThresholdRule


def rule_mask(
    maps: dict[str, np.ndarray], rules: list[ThresholdRule], usable: np.ndarray
) -> np.ndarray:
    """AND of every rule, restricted to usable pixels. NaN map values never pass."""
    out = usable.astype(bool).copy()
    for rule in rules:
        values = maps[rule.map]
        if rule.direction == "decrease":
            out &= values <= -rule.threshold
        else:
            out &= values >= rule.threshold
    return out


def clean_mask(mask: np.ndarray, *, open_px: int, close_px: int) -> np.ndarray:
    """Binary opening (drop speckle) then closing (fill pinholes), square structuring elements."""
    out = mask
    if open_px > 1:
        out = ndimage.binary_opening(out, structure=np.ones((open_px, open_px)))
    if close_px > 1:
        out = ndimage.binary_closing(out, structure=np.ones((close_px, close_px)))
    return out.astype(bool)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_postprocess.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/detection/postprocess.py backend/tests/test_postprocess.py
git commit -m "feat(phase-2): threshold rules + morphological open/close (TDD)"
```

---

### Task 7: Polygonization into typed Detections

Connected regions of the cleaned mask → shapely polygons in the window's CRS, with per-region stats. `scipy.ndimage.label` and `rasterio.features.shapes` both default to 4-connectivity, so one label yields one polygon (possibly with holes).

**Files:**
- Create: `backend/src/overwatch/detection/polygonize.py`
- Test: `backend/tests/test_polygonize.py`

**Interfaces:**
- Consumes: `Detection`, `ChangeType` (Task 5 models), `DetectionPreset` (Task 5), numpy/scipy/rasterio/shapely.
- Produces: `polygonize_mask(mask: np.ndarray[bool], maps: dict[str, np.ndarray], preset: DetectionPreset, transform: Affine, epsg: int) -> list[Detection]`. Used by Task 8.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for mask -> Detection polygonization."""

import numpy as np
import pytest

from overwatch.detection.models import ChangeType
from overwatch.detection.polygonize import polygonize_mask
from overwatch.detection.presets import VERTICAL_PRESETS
from synthetic import EPSG, TRANSFORM_10M

FOREST_PRESET = VERTICAL_PRESETS["forest"]  # ndvi decrease 0.20, min area 5,000 m²


def _mask_and_maps(
    regions: list[tuple[int, int, int, int]], delta: float = -0.5
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    mask = np.zeros((30, 30), dtype=bool)
    ndvi = np.zeros((30, 30), dtype=np.float32)
    for r0, r1, c0, c1 in regions:
        mask[r0:r1, c0:c1] = True
        ndvi[r0:r1, c0:c1] = delta
    return mask, {"ndvi": ndvi}


def test_single_region_geometry_area_and_stats() -> None:
    mask, maps = _mask_and_maps([(5, 15, 5, 15)])  # 100 px = 10,000 m²
    [det] = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert det.change_type is ChangeType.VEGETATION_LOSS
    assert det.epsg == EPSG
    assert det.area_m2 == pytest.approx(10_000.0)
    assert det.geometry.bounds == (500_050.0, 999_850.0, 500_150.0, 999_950.0)
    assert det.magnitude == pytest.approx(0.5)
    assert det.confidence == pytest.approx(1.0)  # every pixel exceeds the 0.2 threshold
    assert det.contributing_indices["ndvi"] == pytest.approx(-0.5)


def test_region_below_min_area_is_dropped() -> None:
    mask, maps = _mask_and_maps([(5, 10, 5, 12)])  # 35 px = 3,500 m² < 5,000
    assert polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG) == []


def test_disjoint_regions_yield_separate_detections() -> None:
    mask, maps = _mask_and_maps([(2, 12, 2, 12), (18, 28, 18, 28)])
    dets = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert len(dets) == 2


def test_empty_mask_yields_no_detections() -> None:
    mask, maps = _mask_and_maps([])
    assert polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG) == []


def test_confidence_counts_only_pixels_over_threshold() -> None:
    mask, maps = _mask_and_maps([(5, 15, 5, 15)], delta=-0.5)
    maps["ndvi"][5:10, 5:15] = -0.1  # half the region below the 0.2 threshold
    [det] = polygonize_mask(mask, maps, FOREST_PRESET, TRANSFORM_10M, EPSG)
    assert det.confidence == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_polygonize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.polygonize'`

- [ ] **Step 3: Write the implementation**

```python
"""Connected change regions -> typed Detection polygons."""

import numpy as np
from affine import Affine
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from overwatch.detection.models import Detection
from overwatch.detection.presets import DetectionPreset


def polygonize_mask(
    mask: np.ndarray,
    maps: dict[str, np.ndarray],
    preset: DetectionPreset,
    transform: Affine,
    epsg: int,
) -> list[Detection]:
    """One Detection per connected region, dropping regions under preset.min_area_m2."""
    pixel_area = abs(transform.a * transform.e)
    labels, n_regions = ndimage.label(mask)
    if n_regions == 0:
        return []
    primary = maps[preset.primary_map]
    primary_rule = next(r for r in preset.rules if r.map == preset.primary_map)
    detections: list[Detection] = []
    for region_id in range(1, n_regions + 1):
        region = labels == region_id
        area_m2 = float(np.count_nonzero(region) * pixel_area)
        if area_m2 < preset.min_area_m2:
            continue
        geometry = unary_union(
            [
                shape(geom)
                for geom, _ in features.shapes(
                    region.astype(np.uint8), mask=region, transform=transform
                )
            ]
        )
        values = primary[region]
        finite = values[np.isfinite(values)]
        magnitude = float(np.mean(np.abs(finite))) if finite.size else 0.0
        if primary_rule.direction == "decrease":
            exceeding = int(np.count_nonzero(finite <= -primary_rule.threshold))
        else:
            exceeding = int(np.count_nonzero(finite >= primary_rule.threshold))
        confidence = float(exceeding / finite.size) if finite.size else 0.0
        contributing = {
            name: (float(np.mean(vals[np.isfinite(vals)])) if np.isfinite(vals).any() else 0.0)
            for name, m in maps.items()
            for vals in [m[region]]
        }
        detections.append(
            Detection(
                geometry=geometry,
                epsg=epsg,
                area_m2=area_m2,
                change_type=preset.change_type,
                magnitude=magnitude,
                confidence=confidence,
                contributing_indices=contributing,
            )
        )
    return detections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_polygonize.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/detection/polygonize.py backend/tests/test_polygonize.py
git commit -m "feat(phase-2): polygonization into typed Detections (TDD)"
```

---

### Task 8: ChangeDetector protocol + ClassicalChangeDetector

The composition layer and the phase's headline test suite: inject a known synthetic change, assert the polygon (design spec §8). Index maps are computed from `apply_mask`-ed bands (unusable → NaN); the SSIM map is computed on raw bands (NaN would poison its 7-px window) and relies on the usable-mask AND in `rule_mask` — a cloud-edge halo of spurious dissimilarity can therefore survive only if it also passes every other rule. Documented limitation, acceptable for ~1.0-usable demo scenes.

**Files:**
- Create: `backend/src/overwatch/detection/detector.py`
- Test: `backend/tests/test_detector.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7 plus `usable_mask`/`apply_mask` (`overwatch.imagery.masking`) and `AOIWindow`.
- Produces:
  - `ChangeDetector` — Protocol with `detect(self, before: AOIWindow, after: AOIWindow, preset: DetectionPreset) -> list[Detection]`.
  - `ClassicalChangeDetector` — the implementation; raises `ValueError` on shape/transform/CRS mismatch. Consumed by Task 10's CLI and by Phase 3.

- [ ] **Step 1: Write the failing tests**

```python
"""End-to-end engine tests on synthetic pairs: inject a known change, assert the polygon."""

import numpy as np
import pytest
from shapely.geometry import Polygon

from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.models import ChangeType
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.models import AOIWindow
from synthetic import (
    BARE,
    BUILT,
    FOREST,
    SCL_CLOUD_HIGH,
    WATER,
    flat_window,
    inject_rect,
    rect_geometry,
)

RECT = (40, 50, 30, 50)  # 10 x 20 px = 200 px = 20,000 m² — clears every min-area floor
DETECTOR = ClassicalChangeDetector()


def _pair(
    background: dict[str, int], change: dict[str, int], **inject_kwargs
) -> tuple[AOIWindow, AOIWindow]:
    before = flat_window(background, seed=1)
    after = flat_window(background, seed=2)
    inject_rect(after, change, RECT, **inject_kwargs)
    return before, after


def _iou(a: Polygon, b: Polygon) -> float:
    return a.intersection(b).area / a.union(b).area


def test_forest_clearing_detected() -> None:
    before, after = _pair(FOREST, BARE)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
    assert det.change_type is ChangeType.VEGETATION_LOSS
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5
    assert det.magnitude > 0.4
    assert 0.0 < det.confidence <= 1.0
    assert det.contributing_indices["ndvi"] < -0.3


def test_flood_inundation_detected() -> None:
    before, after = _pair(BARE, WATER)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["flood"])
    assert det.change_type is ChangeType.FLOODING
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5
    assert det.contributing_indices["ndwi"] > 0.3


def test_port_construction_detected() -> None:
    before, after = _pair(FOREST, BUILT)
    [det] = DETECTOR.detect(before, after, VERTICAL_PRESETS["port"])
    assert det.change_type is ChangeType.CONSTRUCTION
    assert _iou(det.geometry, rect_geometry(RECT)) > 0.5


def test_no_change_yields_no_detections() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    for preset in VERTICAL_PRESETS.values():
        assert DETECTOR.detect(before, after, preset) == []


def test_sub_min_area_change_is_dropped() -> None:
    before = flat_window(FOREST, seed=1)
    after = flat_window(FOREST, seed=2)
    inject_rect(after, BARE, (40, 43, 30, 34))  # 12 px = 1,200 m² < forest's 5,000 m²
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_change_under_cloud_is_not_detected() -> None:
    before, after = _pair(FOREST, BARE, scl_class=SCL_CLOUD_HIGH)
    assert DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"]) == []


def test_mismatched_windows_raise() -> None:
    before = flat_window(FOREST, seed=1, shape=(120, 120))
    after = flat_window(FOREST, seed=2, shape=(100, 100))
    with pytest.raises(ValueError, match="shape"):
        DETECTOR.detect(before, after, VERTICAL_PRESETS["forest"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_detector.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.detector'`

- [ ] **Step 3: Write the implementation**

```python
"""ChangeDetector protocol + the classical implementation (design spec §4, §6).

Pure module: no I/O, no LLM. The deterministic pipeline decides; downstream layers narrate.
"""

from typing import Protocol

import numpy as np

from overwatch.detection.differencing import index_delta, ssim_dissimilarity
from overwatch.detection.indices import nbr, ndvi, ndwi
from overwatch.detection.models import Detection
from overwatch.detection.polygonize import polygonize_mask
from overwatch.detection.postprocess import clean_mask, rule_mask
from overwatch.detection.presets import DetectionPreset
from overwatch.imagery.masking import apply_mask, usable_mask
from overwatch.imagery.models import AOIWindow

_INDEX_FNS = {"ndvi": ndvi, "ndwi": ndwi, "nbr": nbr}


class ChangeDetector(Protocol):
    def detect(
        self, before: AOIWindow, after: AOIWindow, preset: DetectionPreset
    ) -> list[Detection]:
        """Change polygons between two co-registered windows of the same AOI."""
        ...


class ClassicalChangeDetector:
    """Index deltas + SSIM -> AND-ed thresholds -> morphology -> polygons."""

    def detect(
        self, before: AOIWindow, after: AOIWindow, preset: DetectionPreset
    ) -> list[Detection]:
        _check_coregistered(before, after)
        usable = usable_mask(before.scl) & usable_mask(after.scl)
        maps = _change_maps(before, after, preset, usable)
        mask = clean_mask(
            rule_mask(maps, preset.rules, usable),
            open_px=preset.morph_open_px,
            close_px=preset.morph_close_px,
        )
        return polygonize_mask(mask, maps, preset, before.transform, before.epsg)


def _check_coregistered(before: AOIWindow, after: AOIWindow) -> None:
    if before.epsg != after.epsg:
        raise ValueError(f"CRS mismatch: {before.epsg} != {after.epsg}")
    if before.scl.shape != after.scl.shape:
        raise ValueError(f"shape mismatch: {before.scl.shape} != {after.scl.shape}")
    if before.transform != after.transform:
        raise ValueError("window transforms differ — windows are not co-registered")


def _change_maps(
    before: AOIWindow, after: AOIWindow, preset: DetectionPreset, usable: np.ndarray
) -> dict[str, np.ndarray]:
    """Delta maps for every rule's map name. Index maps see NaN-masked bands; SSIM sees raw."""
    needed = {rule.map for rule in preset.rules}
    masked_before = {k: apply_mask(v, usable) for k, v in before.bands.items()}
    masked_after = {k: apply_mask(v, usable) for k, v in after.bands.items()}
    maps: dict[str, np.ndarray] = {}
    for name in needed & _INDEX_FNS.keys():
        fn = _INDEX_FNS[name]
        maps[name] = index_delta(fn(masked_before), fn(masked_after))
    if "ssim_dissim" in needed:
        maps["ssim_dissim"] = ssim_dissimilarity(
            before.bands[preset.ssim_band], after.bands[preset.ssim_band]
        )
    return maps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_detector.py -q`
Expected: `7 passed`. If `test_port_construction_detected` fails on IoU, the SSIM window blurs patch edges — do not chase it by hand-tuning in the test; adjust the port preset's `ssim_dissim` threshold in `presets.py` (0.30–0.40 range), rerun, and record the final value in the Verification Gate notes.

- [ ] **Step 5: Run the full suite**

Run: `docker compose exec api pytest -q`
Expected: all tests pass (32 Phase-1 + 32 new so far = `64 passed`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/detection/detector.py backend/tests/test_detector.py
git commit -m "feat(phase-2): ClassicalChangeDetector end-to-end on synthetic pairs (TDD)"
```

---

### Task 9: Sentinel-2 BOA-offset harmonization

**Why:** processing baseline ≥ 04.00 (early 2022 onward) added a +1000 DN offset to L2A products. A 2021-vs-2025 pair mixes baselines; uncorrected, every index delta acquires a systematic false component that can swamp real change. Earth Search items carry `s2:processing_baseline` and `earthsearch:boa_offset_applied` (true when Element84's pipeline already removed the offset). `read_window` returns raw DNs, so the correction must ride on `SceneMeta`.

**Files:**
- Modify: `backend/src/overwatch/imagery/models.py` (add one field to `SceneMeta`)
- Modify: `backend/src/overwatch/imagery/earth_search.py` (populate it)
- Test: `backend/tests/test_earth_search.py` (extend)

**Interfaces:**
- Consumes: existing `scene_meta_from_item(item: pystac.Item) -> SceneMeta` and the fixture `backend/tests/fixtures/earth_search_item.json`.
- Produces: `SceneMeta.dn_offset: int` (default `0`; `-1000` when the scene's DNs still carry the baseline-04 offset) and `earth_search.boa_dn_offset(props: dict) -> int`. Task 10's CLI adds `dn_offset` to band values before detection.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_earth_search.py`, reusing that file's existing fixture-loading helper if one exists; otherwise load via `json.loads` + `pystac.Item.from_dict` as the file already does for other tests)

```python
def test_boa_dn_offset_rules() -> None:
    from overwatch.imagery.earth_search import boa_dn_offset

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


def test_scene_meta_carries_dn_offset(earth_search_item) -> None:
    # earth_search_item: however this file already builds the fixture pystac.Item
    item = earth_search_item
    item.properties["s2:processing_baseline"] = "05.11"
    item.properties["earthsearch:boa_offset_applied"] = False
    assert scene_meta_from_item(item).dn_offset == -1000
    item.properties["earthsearch:boa_offset_applied"] = True
    assert scene_meta_from_item(item).dn_offset == 0
```

(Adapt the fixture plumbing to the file's existing pattern — the test intent is fixed: both branches of `dn_offset` via `scene_meta_from_item`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_earth_search.py -q`
Expected: FAIL — `ImportError: cannot import name 'boa_dn_offset'`

- [ ] **Step 3: Implement**

In `backend/src/overwatch/imagery/models.py`, add to `SceneMeta` (after `assets`):

```python
    dn_offset: int = 0  # add to DNs before index math (baseline >= 04.00 BOA offset)
```

In `backend/src/overwatch/imagery/earth_search.py`, add after `_epsg_from_props`:

```python
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
```

and in `scene_meta_from_item`, add to the `SceneMeta(...)` call:

```python
        dn_offset=boa_dn_offset(item.properties),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_earth_search.py -q`
Expected: all pass (existing earth-search tests + the 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/imagery/models.py backend/src/overwatch/imagery/earth_search.py backend/tests/test_earth_search.py
git commit -m "fix(phase-2): harmonize Sentinel-2 BOA offset across processing baselines"
```

---

### Task 10: Overlay rendering + detection CLI + real Vizhinjam pair

The phase's eyeball gate: run the engine on the Phase-1 Vizhinjam pair (2021-02-12 vs 2025-02-11, rows already in `scenes` and PNGs in `data/`), draw detection outlines over the after-image, and verify the polygons sit on the real port construction.

**Files:**
- Create: `backend/src/overwatch/detection/overlay.py`
- Create: `backend/src/overwatch/detection/cli.py`
- Test: `backend/tests/test_overlay.py`

**Interfaces:**
- Consumes: `ClassicalChangeDetector` (Task 8), `VERTICAL_PRESETS` (Task 5), `SceneMeta.dn_offset` (Task 9), `EarthSearchProvider`, `SHOWCASE_AOIS`, `stretch_to_uint8`.
- Produces: `render_detections_png(window: AOIWindow, detections: list[Detection], out_path: Path) -> Path` and `python -m overwatch.detection.cli --aoi <slug> --before <date> --after <date>`.

- [ ] **Step 1: Write the failing overlay test**

```python
"""Overlay PNG: detection outlines drawn over the true-colour after-image."""

import numpy as np
from PIL import Image
from shapely.geometry import box

from overwatch.detection.models import ChangeType, Detection
from overwatch.detection.overlay import render_detections_png
from synthetic import EPSG, FOREST, flat_window


def test_overlay_draws_red_outline(tmp_path) -> None:
    window = flat_window(FOREST, seed=1)
    det = Detection(
        geometry=box(500_300.0, 999_500.0, 500_500.0, 999_600.0),  # rows 40..60, cols 30..50
        epsg=EPSG,
        area_m2=20_000.0,
        change_type=ChangeType.VEGETATION_LOSS,
        magnitude=0.5,
        confidence=0.9,
        contributing_indices={"ndvi": -0.5},
    )
    path = render_detections_png(window, [det], tmp_path / "overlay.png")
    img = np.asarray(Image.open(path))
    assert img.shape == (120, 120, 3)
    top_edge = img[38:43, 31:49]  # tolerate line width around row 40
    assert ((top_edge[..., 0] == 255) & (top_edge[..., 1] == 40)).any()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec api pytest tests/test_overlay.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.detection.overlay'`

- [ ] **Step 3: Write `overlay.py`**

```python
"""Detection overlay PNGs for eyeball verification (Phase 2 gate)."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from overwatch.detection.models import Detection
from overwatch.imagery.models import AOIWindow
from overwatch.imagery.render import stretch_to_uint8

_OUTLINE = (255, 40, 40)


def render_detections_png(
    window: AOIWindow, detections: list[Detection], out_path: Path
) -> Path:
    """True-colour after-image with detection boundaries outlined in red."""
    rgb = np.dstack(
        [stretch_to_uint8(window.bands[b].astype(np.float32)) for b in ("red", "green", "blue")]
    )
    img = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(img)
    to_px = ~window.transform
    for det in detections:
        for ring in [det.geometry.exterior, *det.geometry.interiors]:
            draw.line([to_px * (x, y) for x, y in ring.coords], fill=_OUTLINE, width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
```

- [ ] **Step 4: Run the overlay test to verify it passes**

Run: `docker compose exec api pytest tests/test_overlay.py -q`
Expected: `1 passed`

- [ ] **Step 5: Write `cli.py`** (I/O glue — exercised live in Step 6, not unit-tested)

```python
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

from overwatch.aois import SHOWCASE_AOIS, AOI
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
```

- [ ] **Step 6: Run on the real Vizhinjam pair (the eyeball gate)**

Run: `docker compose exec api python -m overwatch.detection.cli --aoi vizhinjam --before 2021-02-12 --after 2025-02-11`
Expected: both scene ids + their baseline offsets logged (the 2025 scene is baseline ≥ 05; whether its offset is 0 or −1000 depends on `earthsearch:boa_offset_applied` — **record what it actually says**); ≥ 1 construction detection whose largest polygon sits over the breakwater/terminal area; overlay PNG written to `data/`.

- [ ] **Step 7: Eyeball the overlay**

Open `data/vizhinjam_2021-02-12_2025-02-11_detections.png` next to the Phase-1 PNGs. The red outlines must trace the new port works (breakwater, terminal, reclaimed backyard), not open ocean or unchanged town. Expect some coastline/surf-zone noise — the AND-ed NDVI rule should suppress most of it. **If output is empty or garbage:** tune `VERTICAL_PRESETS["port"]` thresholds (ssim 0.30–0.45, ndvi 0.05–0.15) and/or `morph_open_px`, rerun, and record the final numbers + reasoning in this plan's Verification Gate section. Re-run the synthetic suite after any preset change (`docker compose exec api pytest tests/test_detector.py -q`) — both must stay green with the same numbers.

- [ ] **Step 8: Sanity-run a second vertical on real data**

Run: `docker compose exec api python -m overwatch.detection.cli --aoi novo-progresso --before 2023-07-19 --after 2024-07-23`
(Those are the Phase-1 dry-season pair dates; if the exact days miss, check `scenes` rows: `docker compose exec postgis psql -U overwatch -c "select stac_id, captured_at, aoi_slug from scenes order by aoi_slug, captured_at;"` and use the listed dates.)
Expected: ≥ 1 vegetation_loss detection over the expanded clearings; overlay PNG eyeballed.

- [ ] **Step 9: Commit**

```bash
git add backend/src/overwatch/detection/overlay.py backend/src/overwatch/detection/cli.py backend/tests/test_overlay.py
git commit -m "feat(phase-2): overlay rendering + detection CLI; verified on real Vizhinjam pair"
```

---

### Task 11: Verification gate + PROGRESS + push

**Files:**
- Modify: `PROGRESS.md`
- Modify: `plans/2026-07-06-phase-2-change-detection.md` (append Verification Gate evidence)

- [ ] **Step 1: Full suite + lint in-container**

Run: `docker compose exec api pytest -q && docker compose exec api ruff check . && docker compose exec api ruff format --check .`
Expected: ~67 passed (32 Phase-1 + ~35 new), ruff clean. Paste actual counts into the evidence section.

- [ ] **Step 2: Append a "Verification Gate" section to this plan** with: test count + ruff output, the CLI stdout for both real-pair runs, the recorded `dn_offset` values per scene, any preset tuning done (before/after numbers + why), and the overlay-PNG eyeball verdicts.

- [ ] **Step 3: Update PROGRESS.md** — move Phase 2 into "Built & verified" with the verification note, set "Next up" to Phase 3 (Detection persistence + API + jobs, fresh session, plan first), keep the preset-tuning numbers listed as engineering defaults (not resume claims).

- [ ] **Step 4: Commit and push**

```bash
git add PROGRESS.md plans/2026-07-06-phase-2-change-detection.md
git commit -m "docs(phase-2): verification evidence, PROGRESS update"
git push -u origin phase-2-change-detection
```

- [ ] **Step 5: Confirm CI green on the PR, then hand off**

Give the user the compare URL: `https://github.com/yash2484/Overwatch/compare/main...phase-2-change-detection`. CI runs on the PR via the `pull_request` trigger; verify green (Actions API, read-only) before asking for merge. The user merges.

---

## Self-review notes

- **Spec coverage:** NDVI/NDWI/NBR deltas (T2/T4/T8), image differencing + SSIM (T4), threshold → open→close morphology (T6), polygonization into typed Detections with geometry/change type/magnitude/confidence/contributing indices (T5/T7), per-vertical presets with spec min-areas (T5), synthetic-first then real Vizhinjam pair (T3/T8/T10), thresholds in presets not hardcoded (T5, enforced by T10 tuning protocol). NBR is implemented and tested but no preset uses it — kept because the roadmap names it and Phase-2+ presets may adopt it; it needs a `swir22` band the CLI doesn't read (YAGNI on the read, not on the pure function).
- **Known limitations (documented, accepted):** SSIM cloud-edge halo (T8 note); SSIM map computed per-preset band (`ssim_band="red"`); `unary_union` assumes 4-connectivity consistency between `ndimage.label` and `features.shapes` (both default to 4-connectivity).
- **Type consistency check:** `rule.map` names match `_change_maps` keys and `MapName` literal; `Detection` fields match between T5 definition and T7 constructor; `rect_geometry` bounds match `TRANSFORM_10M` math (500_000 + col·10, 1_000_000 − row·10).
