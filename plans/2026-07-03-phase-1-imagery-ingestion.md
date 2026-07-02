# Phase 1 — Imagery Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a hardcoded AOI + date range, find Sentinel-2 L2A scenes via Earth Search STAC, read only the AOI's pixel window from COGs, cloud-mask via SCL, persist scene metadata to PostGIS, render PNGs for eyeball verification, and confirm all three showcase AOIs are viable.

**Architecture:** An `ImageryProvider` protocol with an Earth Search implementation (pystac-client for search, rasterio windowed reads over HTTPS COGs). Pure, TDD'd modules for SCL masking, search-window widening, and scene gating (fake provider in tests). A minimal `scenes` table (SQLAlchemy 2 + GeoAlchemy2 + psycopg3 + alembic) with idempotent upserts on `(stac_id, aoi_slug)`. A CLI wires it end-to-end; live runs are manual verification, never CI.

**Tech Stack:** Python 3.12 · pystac-client · rasterio · shapely/pyproj · Pillow · SQLAlchemy 2 / GeoAlchemy2 / psycopg3 / alembic · PostGIS 3.4 · Docker Compose.

## Global Constraints

- **All Python runs in-container**: `docker compose exec api <cmd>`. Never install project deps on the Windows host.
- **Branch:** `phase-1-imagery-ingestion` off synced `main`. User merges via GitHub PR; never push main.
- **Before every commit:** `docker compose exec api sh -c "ruff check --fix . && ruff format ."` then re-run affected tests. Line length 100.
- **Design-spec numbers (§6, verbatim):** usable-pixel fraction ≥ **70%** after SCL masking; auto-widen search window in **+15-day steps capped at +60 days**; masked SCL classes **{0,1,3,8,9,10,11}**; usable **{2,4,5,6,7}**; AOI size cap **500 km²**.
- **Live-API calls are manual verification steps, not CI** (design spec §8). CI tests use fixtures + the CI postgis service only.
- **Additive changes only** — no renaming existing columns/constants/env vars.
- **No secrets** printed, logged, or committed. Earth Search needs no auth.
- AOI seed boxes are **unverified** — refine during eyeballing, record final boxes in this file's Spike Findings appendix.

---

### Task 1: Branch, dependencies, dev mounts

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: importable `pystac_client`, `sqlalchemy`, `geoalchemy2`, `psycopg`, `alembic`, `pyproj`, `shapely`, `PIL`, `affine` in the api container; `./data` ⇄ `/app/data` mount; live-editable `src`/`tests`.

- [x] **Step 1: Create the branch**

```bash
git checkout main && git pull --ff-only && git checkout -b phase-1-imagery-ingestion
```

- [x] **Step 2: Add dependencies to `backend/pyproject.toml`**

Replace the `dependencies` list with:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "celery[redis]>=5.4",
    "rasterio>=1.4",
    "numpy>=2.0",
    "affine>=2.4",
    "shapely>=2.0",
    "pyproj>=3.7",
    "pystac-client>=0.8",
    "pillow>=11.0",
    "sqlalchemy>=2.0",
    "geoalchemy2>=0.16",
    "psycopg[binary]>=3.2",
    "alembic>=1.14",
]
```

- [x] **Step 3: Add dev bind mounts + data mount to `docker-compose.yml` api service**

Rationale: the Dockerfile installs deps and code in one layer, so every `src` edit re-installs all deps on rebuild. Bind mounts make code edits live (restart, not rebuild). Worker/beat keep baked-in code until Phase 3 gives them tasks.

In the `api` service, after `ports:`, add:

```yaml
    volumes:
      - ./backend/src:/app/src
      - ./backend/tests:/app/tests
      - ./data:/app/data
```

- [x] **Step 4: Gitignore run artifacts and the serena cache**

Append to `.gitignore`:

```
data/
.serena/
```

- [x] **Step 5: Rebuild and verify imports in-container**

```bash
mkdir -p data
docker compose up -d --build
docker compose exec api python -c "import pystac_client, sqlalchemy, geoalchemy2, psycopg, alembic, pyproj, shapely, PIL, affine; print('deps ok')"
```

Expected: `deps ok`. Also `docker compose exec api pytest -v` → existing 2 tests pass.

- [x] **Step 6: Commit**

```bash
git add plans/2026-07-03-phase-1-imagery-ingestion.md backend/pyproject.toml docker-compose.yml .gitignore
git commit -m "chore(phase-1): add imagery+db deps, dev bind mounts, data dir"
```

---

### Task 2: Earth Search STAC spike (verify reality before coding)

**Files:**
- Modify: `plans/2026-07-03-phase-1-imagery-ingestion.md` (append Spike Findings)
- Create: `backend/tests/fixtures/earth_search_item.json` (committed in Task 7)

**Interfaces:**
- Produces: verified asset keys, EPSG property name (`proj:epsg` vs `proj:code`), href scheme; one real item JSON saved as a test fixture.

- [x] **Step 1: Run the spike in-container**

```bash
docker compose exec -T api python - <<'PY'
import json
from pystac_client import Client

client = Client.open("https://earth-search.aws.element84.com/v1")
search = client.search(
    collections=["sentinel-2-l2a"],
    intersects={"type": "Point", "coordinates": [76.985, 8.375]},  # Vizhinjam
    datetime="2021-01-01/2021-03-31",
    query={"eo:cloud_cover": {"lt": 20}},
    max_items=5,
)
items = list(search.items())
print(f"found {len(items)} items")
it = items[0]
print("id:", it.id)
print("datetime:", it.datetime)
print("cloud:", it.properties.get("eo:cloud_cover"))
print("proj keys:", {k: v for k, v in it.properties.items() if k.startswith("proj:")})
print("asset keys:", sorted(it.assets))
for k in ("red", "green", "blue", "nir", "scl"):
    a = it.assets.get(k)
    print(k, "->", a.href if a else "MISSING")
with open("/app/data/spike_item.json", "w") as f:
    json.dump(it.to_dict(), f, indent=2)
print("saved /app/data/spike_item.json")
PY
```

Expected: ≥1 item; asset keys include `red/green/blue/nir/scl`; hrefs are `https://sentinel-cogs.s3.us-west-2.amazonaws.com/...`; a `proj:` property carrying the UTM EPSG (~32643).

- [x] **Step 2: Verify a windowed read works (the whole phase hinges on this)**

```bash
docker compose exec -T api python - <<'PY'
import json, math, rasterio
from pyproj import Transformer
from rasterio.windows import Window, from_bounds
from shapely.geometry import box
from shapely.ops import transform as shp_transform

item = json.load(open("/app/data/spike_item.json"))
props = item["properties"]
epsg = props.get("proj:epsg") or int(str(props.get("proj:code", "")).split(":")[-1])
href = item["assets"]["red"]["href"]
geom = box(76.960, 8.355, 77.010, 8.395)
tr = Transformer.from_crs(4326, epsg, always_xy=True)
bounds = shp_transform(tr.transform, geom).bounds
env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "VSI_CACHE": "TRUE"}
with rasterio.Env(**env), rasterio.open(href) as src:
    win = from_bounds(*bounds, transform=src.transform)
    col = math.floor(win.col_off); row = math.floor(win.row_off)
    w = math.ceil(win.col_off + win.width) - col; h = math.ceil(win.row_off + win.height) - row
    arr = src.read(1, window=Window(col, row, w, h))
    print("shape:", arr.shape, "dtype:", arr.dtype, "min/max:", arr.min(), arr.max())
PY
```

Expected: shape roughly (440, 550) for the seed box at 10 m; non-zero max. If this fails, STOP and diagnose before any implementation task.

- [x] **Step 3: Record findings**

Append a `## Spike Findings (2026-07-03)` section to this plan file: exact asset keys, EPSG property name and value, href host, item id used, read shape/dtype, and any surprises. Commit:

```bash
git add plans/2026-07-03-phase-1-imagery-ingestion.md
git commit -m "docs(phase-1): record Earth Search spike findings"
```

---

### Task 3: SCL masking (pure, TDD)

**Files:**
- Create: `backend/src/overwatch/imagery/__init__.py` (empty)
- Create: `backend/src/overwatch/imagery/masking.py`
- Test: `backend/tests/test_masking.py`

**Interfaces:**
- Produces: `MASKED_SCL_CLASSES: frozenset[int]`; `usable_mask(scl: np.ndarray) -> np.ndarray` (bool, True=usable); `usable_fraction(scl: np.ndarray) -> float`; `apply_mask(band: np.ndarray, mask: np.ndarray) -> np.ndarray` (float32, NaN where unusable).

- [x] **Step 1: Write the failing tests**

```python
import numpy as np

from overwatch.imagery.masking import (
    MASKED_SCL_CLASSES,
    apply_mask,
    usable_fraction,
    usable_mask,
)


def test_usable_mask_flags_cloud_and_nodata() -> None:
    scl = np.array([[4, 8], [0, 5]], dtype=np.uint8)
    expected = np.array([[True, False], [False, True]])
    assert (usable_mask(scl) == expected).all()


def test_every_masked_class_is_unusable() -> None:
    for cls in MASKED_SCL_CLASSES:
        assert usable_fraction(np.full((3, 3), cls, dtype=np.uint8)) == 0.0


def test_every_usable_class_is_usable() -> None:
    for cls in (2, 4, 5, 6, 7):
        assert usable_fraction(np.full((3, 3), cls, dtype=np.uint8)) == 1.0


def test_usable_fraction_counts_share() -> None:
    scl = np.array([[4, 9], [4, 4]], dtype=np.uint8)
    assert usable_fraction(scl) == 0.75


def test_usable_fraction_empty_is_zero() -> None:
    assert usable_fraction(np.array([], dtype=np.uint8)) == 0.0


def test_apply_mask_nans_unusable_and_leaves_input_untouched() -> None:
    band = np.array([[100, 200], [300, 400]], dtype=np.uint16)
    mask = np.array([[True, False], [False, True]])
    out = apply_mask(band, mask)
    assert out.dtype == np.float32
    assert np.isnan(out[0, 1]) and np.isnan(out[1, 0])
    assert out[0, 0] == 100.0 and out[1, 1] == 400.0
    assert band[0, 1] == 200  # input not mutated
```

- [x] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_masking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.imagery'`

- [x] **Step 3: Implement `masking.py`**

```python
"""SCL-based cloud masking (design spec §6).

Masked (unusable): 0 no-data, 1 saturated/defective, 3 cloud shadow,
8 cloud medium prob, 9 cloud high prob, 10 thin cirrus, 11 snow/ice.
Usable: 2 dark area, 4 vegetation, 5 not vegetated, 6 water, 7 unclassified.
"""

import numpy as np

MASKED_SCL_CLASSES: frozenset[int] = frozenset({0, 1, 3, 8, 9, 10, 11})


def usable_mask(scl: np.ndarray) -> np.ndarray:
    """Boolean array, True where the pixel is usable for analysis."""
    return ~np.isin(scl, list(MASKED_SCL_CLASSES))


def usable_fraction(scl: np.ndarray) -> float:
    """Fraction of usable pixels in [0.0, 1.0]. Empty input counts as fully unusable."""
    if scl.size == 0:
        return 0.0
    return float(np.count_nonzero(usable_mask(scl)) / scl.size)


def apply_mask(band: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return band as float32 with unusable pixels set to NaN. Does not mutate input."""
    out = band.astype(np.float32, copy=True)
    out[~mask] = np.nan
    return out
```

- [x] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_masking.py -v`
Expected: 6 passed

- [x] **Step 5: Lint and commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format ."
git add backend/src/overwatch/imagery/ backend/tests/test_masking.py
git commit -m "feat(phase-1): SCL cloud masking with usable-pixel fraction (TDD)"
```

---

### Task 4: Search-window widening (pure, TDD)

**Files:**
- Create: `backend/src/overwatch/imagery/search_windows.py`
- Test: `backend/tests/test_search_windows.py`

**Interfaces:**
- Produces: `candidate_windows(start: date, end: date, *, step_days: int = 15, cap_days: int = 60) -> list[tuple[date, date]]` — original window first, then end-extended windows. Widening extends the **end** forward (engineering default; noted assumption — spec says "+15-day steps capped at +60 days" without direction).

- [x] **Step 1: Write the failing tests**

```python
from datetime import date

import pytest

from overwatch.imagery.search_windows import candidate_windows


def test_default_yields_original_plus_four_widened() -> None:
    wins = candidate_windows(date(2021, 1, 1), date(2021, 1, 31))
    assert wins == [
        (date(2021, 1, 1), date(2021, 1, 31)),
        (date(2021, 1, 1), date(2021, 2, 15)),
        (date(2021, 1, 1), date(2021, 3, 2)),
        (date(2021, 1, 1), date(2021, 3, 17)),
        (date(2021, 1, 1), date(2021, 4, 1)),
    ]


def test_custom_step_and_cap() -> None:
    wins = candidate_windows(date(2021, 1, 1), date(2021, 1, 10), step_days=10, cap_days=20)
    assert [w[1] for w in wins] == [date(2021, 1, 10), date(2021, 1, 20), date(2021, 1, 30)]


def test_end_before_start_raises() -> None:
    with pytest.raises(ValueError, match="before start"):
        candidate_windows(date(2021, 2, 1), date(2021, 1, 1))
```

- [x] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_search_windows.py -v`
Expected: FAIL — module not found

- [x] **Step 3: Implement `search_windows.py`**

```python
"""Auto-widening scene search windows (design spec §6: +15-day steps, +60-day cap)."""

from datetime import date, timedelta


def candidate_windows(
    start: date, end: date, *, step_days: int = 15, cap_days: int = 60
) -> list[tuple[date, date]]:
    """The original window plus end-extended windows in step_days increments up to cap_days."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [(start, end + timedelta(days=d)) for d in range(0, cap_days + 1, step_days)]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_search_windows.py -v`
Expected: 3 passed

- [x] **Step 5: Lint and commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format ."
git add backend/src/overwatch/imagery/search_windows.py backend/tests/test_search_windows.py
git commit -m "feat(phase-1): auto-widening search windows (TDD)"
```

---

### Task 5: Showcase AOI seeds (TDD)

**Files:**
- Create: `backend/src/overwatch/aois.py`
- Test: `backend/tests/test_aois.py`

**Interfaces:**
- Produces: `AOI` (pydantic: `slug/name/vertical/bbox`, method `geometry() -> shapely Polygon`); `SHOWCASE_AOIS: dict[str, AOI]` keyed by slug (`vizhinjam`, `novo-progresso`, `porto-alegre`). bbox order: `(west, south, east, north)` in EPSG:4326.

- [x] **Step 1: Write the failing tests**

```python
from pyproj import Geod

from overwatch.aois import SHOWCASE_AOIS


def test_three_showcase_aois_present() -> None:
    assert set(SHOWCASE_AOIS) == {"vizhinjam", "novo-progresso", "porto-alegre"}
    assert {a.vertical for a in SHOWCASE_AOIS.values()} == {"port", "forest", "flood"}


def test_bboxes_are_ordered() -> None:
    for aoi in SHOWCASE_AOIS.values():
        west, south, east, north = aoi.bbox
        assert west < east and south < north
        assert -180 <= west <= 180 and -90 <= south <= 90


def test_aoi_areas_between_1_and_500_km2() -> None:
    geod = Geod(ellps="WGS84")
    for aoi in SHOWCASE_AOIS.values():
        area_km2 = abs(geod.geometry_area_perimeter(aoi.geometry())[0]) / 1e6
        assert 1.0 < area_km2 < 500.0, f"{aoi.slug}: {area_km2:.1f} km2"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_aois.py -v`
Expected: FAIL — module not found

- [x] **Step 3: Implement `aois.py`**

```python
"""Hardcoded showcase AOIs (design spec §5). Seed boxes — refined during Phase 1 eyeballing."""

from pydantic import BaseModel
from shapely.geometry import Polygon, box


class AOI(BaseModel):
    slug: str
    name: str
    vertical: str  # "port" | "forest" | "flood"
    bbox: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)

    def geometry(self) -> Polygon:
        return box(*self.bbox)


SHOWCASE_AOIS: dict[str, AOI] = {
    aoi.slug: aoi
    for aoi in [
        AOI(
            slug="vizhinjam",
            name="Vizhinjam International Seaport, Kerala",
            vertical="port",
            bbox=(76.960, 8.355, 77.010, 8.395),
        ),
        AOI(
            slug="novo-progresso",
            name="Novo Progresso (BR-163), Para",
            vertical="forest",
            bbox=(-55.450, -7.150, -55.350, -7.050),
        ),
        AOI(
            slug="porto-alegre",
            name="Porto Alegre / Guaiba, Rio Grande do Sul",
            vertical="flood",
            bbox=(-51.300, -30.080, -51.180, -29.980),
        ),
    ]
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_aois.py -v`
Expected: 3 passed

- [x] **Step 5: Lint and commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format ."
git add backend/src/overwatch/aois.py backend/tests/test_aois.py
git commit -m "feat(phase-1): showcase AOI seed boxes (TDD)"
```

---

### Task 6: Provider types + usable-scene gating (TDD with fake provider)

**Files:**
- Create: `backend/src/overwatch/imagery/models.py`
- Create: `backend/src/overwatch/imagery/provider.py`
- Create: `backend/src/overwatch/imagery/gating.py`
- Test: `backend/tests/test_gating.py`

**Interfaces:**
- Produces:
  - `SceneMeta` (pydantic): `stac_id: str`, `collection: str`, `captured_at: datetime`, `cloud_pct: float`, `epsg: int`, `assets: dict[str, str]`.
  - `AOIWindow` (dataclass): `bands: dict[str, np.ndarray]`, `scl: np.ndarray`, `transform: Affine`, `epsg: int`.
  - `ImageryProvider` (Protocol): `search_scenes(geometry, start, end, *, max_cloud_pct) -> list[SceneMeta]`; `read_window(scene, geometry, bands) -> AOIWindow`.
  - `SceneCoverageError(Exception)`.
  - `find_usable_scene(provider, geometry, start, end, *, max_cloud_pct=60.0, min_usable=0.7, bands=("red","green","blue")) -> SceneSelection | None`; `SceneSelection` dataclass: `scene`, `window`, `usable_fraction`.

- [x] **Step 1: Write `models.py`**

```python
"""Typed imagery interfaces (design spec §4)."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from pydantic import BaseModel


class SceneMeta(BaseModel):
    """STAC scene metadata, provider-agnostic."""

    stac_id: str
    collection: str
    captured_at: datetime
    cloud_pct: float
    epsg: int
    assets: dict[str, str]  # asset key -> href, only the bands we may read


@dataclass
class AOIWindow:
    """Windowed pixel data for one AOI within one scene, on the 10 m grid."""

    bands: dict[str, np.ndarray]  # all arrays share one shape
    scl: np.ndarray  # uint8, upsampled nearest to the same shape
    transform: Affine  # window transform in the scene's CRS
    epsg: int
```

- [x] **Step 2: Write `provider.py`**

```python
"""ImageryProvider protocol — Earth Search today, swappable later (design spec §4)."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from shapely.geometry import Polygon

from overwatch.imagery.models import AOIWindow, SceneMeta


class SceneCoverageError(Exception):
    """The scene raster does not fully cover the requested AOI window."""


class ImageryProvider(Protocol):
    def search_scenes(
        self, geometry: Polygon, start: date, end: date, *, max_cloud_pct: float
    ) -> list[SceneMeta]:
        """Scenes intersecting geometry (EPSG:4326) within [start, end], oldest first."""
        ...

    def read_window(
        self, scene: SceneMeta, geometry: Polygon, bands: Sequence[str]
    ) -> AOIWindow:
        """Windowed read of bands + SCL. Raises SceneCoverageError on partial coverage."""
        ...
```

- [x] **Step 3: Write the failing gating tests**

```python
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
```

- [x] **Step 4: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_gating.py -v`
Expected: FAIL — `overwatch.imagery.gating` not found

- [x] **Step 5: Implement `gating.py`**

```python
"""Usable-scene selection: SCL cloud gate + auto-widened search (design spec §6)."""

import logging
from dataclasses import dataclass
from datetime import date

from shapely.geometry import Polygon

from overwatch.imagery.masking import usable_fraction
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.imagery.provider import ImageryProvider, SceneCoverageError
from overwatch.imagery.search_windows import candidate_windows

logger = logging.getLogger(__name__)

MIN_USABLE_FRACTION = 0.7
DEFAULT_BANDS: tuple[str, ...] = ("red", "green", "blue")


@dataclass
class SceneSelection:
    scene: SceneMeta
    window: AOIWindow
    usable_fraction: float


def find_usable_scene(
    provider: ImageryProvider,
    geometry: Polygon,
    start: date,
    end: date,
    *,
    max_cloud_pct: float = 60.0,
    min_usable: float = MIN_USABLE_FRACTION,
    bands: tuple[str, ...] = DEFAULT_BANDS,
) -> SceneSelection | None:
    """First scene whose AOI window clears the usable-pixel gate; None if the cap exhausts.

    Scenes are tried clearest-first (scene-level cloud metadata), but the SCL gate on the
    actual AOI window decides — scene-level cloud % routinely lies about a small window.
    """
    seen: set[str] = set()
    for win_start, win_end in candidate_windows(start, end):
        scenes = provider.search_scenes(geometry, win_start, win_end, max_cloud_pct=max_cloud_pct)
        fresh = [s for s in scenes if s.stac_id not in seen]
        for scene in sorted(fresh, key=lambda s: s.cloud_pct):
            seen.add(scene.stac_id)
            try:
                window = provider.read_window(scene, geometry, bands)
            except SceneCoverageError as exc:
                logger.info("skipping %s: %s", scene.stac_id, exc)
                continue
            fraction = usable_fraction(window.scl)
            if fraction >= min_usable:
                logger.info(
                    "selected %s: usable=%.3f cloud=%.1f%%",
                    scene.stac_id,
                    fraction,
                    scene.cloud_pct,
                )
                return SceneSelection(scene=scene, window=window, usable_fraction=fraction)
            logger.info("skipping %s: usable=%.3f < %.3f", scene.stac_id, fraction, min_usable)
        if (win_start, win_end) != (start, end):
            logger.info("widened window to %s..%s exhausted", win_start, win_end)
    logger.warning("no usable scene for %s..%s after widening to +60d", start, end)
    return None
```

- [x] **Step 6: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_gating.py -v`
Expected: 5 passed

- [x] **Step 7: Lint, full suite, commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format . && pytest -q"
git add backend/src/overwatch/imagery/ backend/tests/test_gating.py
git commit -m "feat(phase-1): provider protocol + usable-scene gating (TDD)"
```

---

### Task 7: PNG rendering (TDD)

**Files:**
- Create: `backend/src/overwatch/imagery/render.py`
- Test: `backend/tests/test_render.py`

**Interfaces:**
- Consumes: `AOIWindow` from Task 6.
- Produces: `stretch_to_uint8(band: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray`; `render_rgb_png(window: AOIWindow, out_path: Path) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import numpy as np
from affine import Affine
from PIL import Image

from overwatch.imagery.models import AOIWindow
from overwatch.imagery.render import render_rgb_png, stretch_to_uint8


def test_stretch_maps_percentile_range_to_full_uint8() -> None:
    band = np.linspace(0.0, 1000.0, 10000, dtype=np.float32).reshape(100, 100)
    out = stretch_to_uint8(band)
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_stretch_constant_band_is_all_zero() -> None:
    assert stretch_to_uint8(np.full((4, 4), 500.0, dtype=np.float32)).max() == 0


def test_stretch_nan_pixels_become_zero() -> None:
    band = np.array([[np.nan, 100.0], [200.0, 300.0]], dtype=np.float32)
    assert stretch_to_uint8(band)[0, 0] == 0


def test_render_writes_rgb_png(tmp_path: Path) -> None:
    shape = (8, 8)
    rng = np.random.default_rng(42)
    window = AOIWindow(
        bands={b: rng.integers(0, 4000, shape).astype(np.uint16) for b in ("red", "green", "blue")},
        scl=np.full(shape, 4, dtype=np.uint8),
        transform=Affine.identity(),
        epsg=32643,
    )
    out = render_rgb_png(window, tmp_path / "sub" / "scene.png")
    with Image.open(out) as img:
        assert img.mode == "RGB" and img.size == (8, 8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_render.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `render.py`**

```python
"""RGB PNG rendering for eyeball verification (Phase 1 gate)."""

from pathlib import Path

import numpy as np
from PIL import Image

from overwatch.imagery.models import AOIWindow


def stretch_to_uint8(
    band: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0
) -> np.ndarray:
    """Percentile-stretch to 0..255 uint8. NaN-safe: NaN pixels render as 0 (black)."""
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return np.zeros(band.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        return np.zeros(band.shape, dtype=np.uint8)
    scaled = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
    return np.nan_to_num(scaled * 255.0).astype(np.uint8)


def render_rgb_png(window: AOIWindow, out_path: Path) -> Path:
    """True-colour PNG from the window's red/green/blue bands."""
    rgb = np.dstack(
        [stretch_to_uint8(window.bands[b].astype(np.float32)) for b in ("red", "green", "blue")]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_path)
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_render.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format ."
git add backend/src/overwatch/imagery/render.py backend/tests/test_render.py
git commit -m "feat(phase-1): percentile-stretched RGB PNG rendering (TDD)"
```

---

### Task 8: Earth Search provider (unit-TDD the pure parts; live reads verified manually)

**Files:**
- Create: `backend/src/overwatch/imagery/earth_search.py`
- Create: `backend/tests/fixtures/earth_search_item.json` (from the Task 2 spike)
- Test: `backend/tests/test_earth_search.py`
- Modify: `backend/src/overwatch/config.py`

**Interfaces:**
- Consumes: `SceneMeta`, `AOIWindow`, `SceneCoverageError` (Task 6); spike fixture.
- Produces: `EarthSearchProvider` (implements `ImageryProvider`); helpers `scene_meta_from_item(item: pystac.Item) -> SceneMeta`, `integer_window(bounds: tuple, transform: Affine) -> Window`, `_epsg_from_props(props: dict) -> int`; `settings.stac_api_url`.

- [ ] **Step 1: Add the STAC URL to `config.py`**

Add one field to `Settings` (additive):

```python
    stac_api_url: str = "https://earth-search.aws.element84.com/v1"
```

- [ ] **Step 2: Create the fixture from the spike output**

Copy `data/spike_item.json` to `backend/tests/fixtures/earth_search_item.json`. Trim `assets` to only `red`, `green`, `blue`, `nir`, `scl`, `visual` entries (keep each entry's full dict) to keep the fixture small. Keep `properties`, `id`, `collection`, `geometry`, `bbox`, `stac_version`, `links` (links may be `[]`).

- [ ] **Step 3: Write the failing tests**

Adjust the EPSG assertion to the spike's real value if not 32643.

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `docker compose exec api pytest tests/test_earth_search.py -v`
Expected: FAIL — module not found

- [ ] **Step 5: Implement `earth_search.py`**

```python
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
            query={"eo:cloud_cover": {"lt": max_cloud_pct}},
            max_items=64,
        )
        metas = [scene_meta_from_item(item) for item in search.items()]
        return sorted(metas, key=lambda m: m.captured_at)

    def read_window(
        self, scene: SceneMeta, geometry: Polygon, bands: Sequence[str]
    ) -> AOIWindow:
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
                scl = src.read(
                    1, window=win, out_shape=shape, resampling=Resampling.nearest
                )
        assert ref_transform is not None  # bands is never empty
        return AOIWindow(bands=out, scl=scl, transform=ref_transform, epsg=scene.epsg)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec api pytest tests/test_earth_search.py -v`
Expected: 6 passed

- [ ] **Step 7: Live smoke check (manual, not CI): search + windowed read via the provider**

```bash
docker compose exec -T api python - <<'PY'
from datetime import date
from overwatch.aois import SHOWCASE_AOIS
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.masking import usable_fraction

p = EarthSearchProvider()
geom = SHOWCASE_AOIS["vizhinjam"].geometry()
scenes = p.search_scenes(geom, date(2021, 1, 1), date(2021, 3, 31), max_cloud_pct=20)
print(f"{len(scenes)} scenes; first: {scenes[0].stac_id} cloud={scenes[0].cloud_pct}")
w = p.read_window(scenes[0], geom, ("red", "green", "blue"))
print("shape:", w.bands["red"].shape, "scl:", w.scl.shape, "usable:", f"{usable_fraction(w.scl):.3f}")
PY
```

Expected: ≥1 scene; band and SCL shapes equal; usable fraction printed (likely > 0.9 for a clear-season scene).

- [ ] **Step 8: Lint, full suite, commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format . && pytest -q"
git add backend/src/overwatch/imagery/earth_search.py backend/src/overwatch/config.py backend/tests/test_earth_search.py backend/tests/fixtures/
git commit -m "feat(phase-1): Earth Search provider with windowed COG reads"
```

---

### Task 9: DB engine, Scene model, alembic migration

**Files:**
- Create: `backend/src/overwatch/db/__init__.py` (empty)
- Create: `backend/src/overwatch/db/engine.py`
- Create: `backend/src/overwatch/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_create_scenes.py`
- Modify: `backend/Dockerfile`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_engine.py`

**Interfaces:**
- Produces: `sqlalchemy_url(url: str) -> str`; `get_engine() -> Engine`; `session_scope()` context manager yielding a committed/rolled-back `Session`; ORM `Scene` (table `scenes`, unique `(stac_id, aoi_slug)` named `uq_scenes_stac_id_aoi_slug`); alembic `upgrade head` creates the table + GiST index.

- [ ] **Step 1: Write the failing URL-normalization test**

```python
from overwatch.db.engine import sqlalchemy_url


def test_plain_postgresql_url_gets_psycopg_driver() -> None:
    assert (
        sqlalchemy_url("postgresql://u:p@postgis:5432/overwatch")
        == "postgresql+psycopg://u:p@postgis:5432/overwatch"
    )


def test_explicit_driver_urls_pass_through() -> None:
    url = "postgresql+psycopg://u:p@host/db"
    assert sqlalchemy_url(url) == url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api pytest tests/test_engine.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `db/engine.py`**

```python
"""SQLAlchemy engine/session plumbing. psycopg3 driver forced onto plain postgres URLs."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from overwatch.config import settings


def sqlalchemy_url(url: str) -> str:
    """Force the psycopg (v3) driver on plain postgresql:// URLs; leave others untouched."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(sqlalchemy_url(settings.database_url), pool_pre_ping=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session with commit-on-success, rollback-on-error semantics."""
    session = sessionmaker(bind=get_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec api pytest tests/test_engine.py -v`
Expected: 2 passed

- [ ] **Step 5: Implement `db/models.py`**

```python
"""ORM models. scenes = Sentinel-2 scene metadata per AOI window (design spec §4)."""

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Scene(Base):
    """One Sentinel-2 scene's metadata for one AOI window.

    Natural key (stac_id, aoi_slug): usable fraction and window bounds are
    AOI-window-specific, so the same STAC scene may legitimately row once per AOI.
    """

    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("stac_id", "aoi_slug", name="uq_scenes_stac_id_aoi_slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stac_id: Mapped[str] = mapped_column(Text, nullable=False)
    aoi_slug: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_pct: Mapped[float] = mapped_column(Float, nullable=False)
    usable_fraction: Mapped[float | None] = mapped_column(Float)
    epsg: Mapped[int] = mapped_column(Integer, nullable=False)
    window_geom = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

(`spatial_index=False` because the migration creates the GiST index explicitly — avoids GeoAlchemy2's implicit-index DDL listeners firing unpredictably under alembic.)

- [ ] **Step 6: Create `backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 7: Create `backend/alembic/env.py`**

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from overwatch.config import settings
from overwatch.db.engine import sqlalchemy_url
from overwatch.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sqlalchemy_url(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sqlalchemy_url(settings.database_url), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 8: Create `backend/alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 9: Create `backend/alembic/versions/0001_create_scenes.py`**

```python
"""create scenes table

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "scenes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stac_id", sa.Text(), nullable=False),
        sa.Column("aoi_slug", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_pct", sa.Float(), nullable=False),
        sa.Column("usable_fraction", sa.Float(), nullable=True),
        sa.Column("epsg", sa.Integer(), nullable=False),
        sa.Column(
            "window_geom",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint("stac_id", "aoi_slug", name="uq_scenes_stac_id_aoi_slug"),
    )
    op.execute("CREATE INDEX ix_scenes_window_geom ON scenes USING gist (window_geom)")


def downgrade() -> None:
    op.drop_table("scenes")
```

- [ ] **Step 10: Ship alembic in the image + mount it for dev**

`backend/Dockerfile` — after `COPY tests ./tests` add:

```dockerfile
COPY alembic.ini ./
COPY alembic ./alembic
```

`docker-compose.yml` — add to the api service volumes:

```yaml
      - ./backend/alembic:/app/alembic
```

- [ ] **Step 11: Rebuild, migrate, verify schema**

```bash
docker compose up -d --build api
docker compose exec api alembic upgrade head
docker compose exec postgis psql -U overwatch -d overwatch -c "\d scenes"
docker compose exec postgis psql -U overwatch -d overwatch -c "SELECT indexname FROM pg_indexes WHERE tablename='scenes'"
```

Expected: table with all 11 columns, `window_geom` as `geometry(Polygon,4326)`; indexes include `uq_scenes_stac_id_aoi_slug` and `ix_scenes_window_geom` (gist). Exactly one gist index — if a second `idx_scenes_window_geom` appears, the GeoAlchemy2 listener fired despite `spatial_index=False`; drop the explicit `op.execute` index line instead and re-verify from a clean DB.

- [ ] **Step 12: Lint, full suite, commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format . && pytest -q"
git add backend/src/overwatch/db/ backend/alembic.ini backend/alembic/ backend/Dockerfile docker-compose.yml backend/tests/test_engine.py
git commit -m "feat(phase-1): scenes schema, engine plumbing, alembic baseline"
```

---

### Task 10: Idempotent scene upsert (integration-tested against PostGIS)

**Files:**
- Create: `backend/src/overwatch/db/scenes.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_scenes_db.py`

**Interfaces:**
- Consumes: `Scene`, `session_scope` (Task 9); `SceneMeta` (Task 6).
- Produces: `upsert_scene(session, scene: SceneMeta, aoi_slug: str, window_geometry: Polygon, usable_fraction: float | None, meta: dict | None = None) -> int` (row id, stable across re-runs).

- [ ] **Step 1: Create `tests/conftest.py` with a session-scoped migration fixture**

```python
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Bring the test database to head. Requires a reachable PostGIS (compose or CI service)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
```

- [ ] **Step 2: Write the failing idempotency test**

```python
import datetime as dt

import pytest
from shapely.geometry import box
from sqlalchemy import delete, select

from overwatch.db.engine import session_scope
from overwatch.db.models import Scene
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.models import SceneMeta

TEST_SLUG = "test-idempotency"


@pytest.fixture()
def clean_rows(migrated_db):
    yield
    with session_scope() as s:
        s.execute(delete(Scene).where(Scene.aoi_slug == TEST_SLUG))


def _meta() -> SceneMeta:
    return SceneMeta(
        stac_id="S2B_43PDP_20240101_0_L2A_TEST",
        collection="sentinel-2-l2a",
        captured_at=dt.datetime(2024, 1, 1, 5, 30, tzinfo=dt.UTC),
        cloud_pct=12.5,
        epsg=32643,
        assets={"red": "https://example.com/B04.tif"},
    )


def test_upsert_twice_yields_one_row_with_updated_fields(clean_rows) -> None:
    geom = box(76.96, 8.355, 77.01, 8.395)
    with session_scope() as s:
        first_id = upsert_scene(s, _meta(), TEST_SLUG, geom, usable_fraction=0.85)
    with session_scope() as s:
        second_id = upsert_scene(s, _meta(), TEST_SLUG, geom, usable_fraction=0.91)
    assert first_id == second_id
    with session_scope() as s:
        rows = s.execute(select(Scene).where(Scene.aoi_slug == TEST_SLUG)).scalars().all()
        assert len(rows) == 1
        assert rows[0].usable_fraction == pytest.approx(0.91)
        assert rows[0].stac_id == "S2B_43PDP_20240101_0_L2A_TEST"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec api pytest tests/test_scenes_db.py -v`
Expected: FAIL — `overwatch.db.scenes` not found

- [ ] **Step 4: Implement `db/scenes.py`**

```python
"""Scene persistence — idempotent upsert on the (stac_id, aoi_slug) natural key."""

from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from overwatch.db.models import Scene
from overwatch.imagery.models import SceneMeta


def upsert_scene(
    session: Session,
    scene: SceneMeta,
    aoi_slug: str,
    window_geometry: Polygon,
    usable_fraction: float | None,
    meta: dict[str, Any] | None = None,
) -> int:
    """Insert or update the row for (stac_id, aoi_slug); returns the stable row id."""
    values = {
        "stac_id": scene.stac_id,
        "aoi_slug": aoi_slug,
        "captured_at": scene.captured_at,
        "cloud_pct": scene.cloud_pct,
        "usable_fraction": usable_fraction,
        "epsg": scene.epsg,
        "window_geom": from_shape(window_geometry, srid=4326),
        "meta": meta or {},
    }
    update_cols = {k: v for k, v in values.items() if k not in ("stac_id", "aoi_slug")}
    update_cols["updated_at"] = func.now()
    stmt = (
        insert(Scene)
        .values(**values)
        .on_conflict_do_update(constraint="uq_scenes_stac_id_aoi_slug", set_=update_cols)
        .returning(Scene.id)
    )
    return session.execute(stmt).scalar_one()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec api pytest tests/test_scenes_db.py -v`
Expected: 1 passed

- [ ] **Step 6: Lint, full suite, commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format . && pytest -q"
git add backend/src/overwatch/db/scenes.py backend/tests/conftest.py backend/tests/test_scenes_db.py
git commit -m "feat(phase-1): idempotent scene upsert on (stac_id, aoi_slug)"
```

---

### Task 11: Ingestion CLI (wires search → gate → mask → PNG → persist)

**Files:**
- Create: `backend/src/overwatch/imagery/cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m overwatch.imagery.cli --aoi <slug> --start YYYY-MM-DD --end YYYY-MM-DD [--max-cloud 60] [--min-usable 0.7] [--out-dir /app/data]`. Exit 0 with a summary line on success; exit 1 with `NO USABLE SCENE ...` when the gate exhausts the widening cap.

- [ ] **Step 1: Implement `cli.py`**

```python
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
```

- [ ] **Step 2: First live run (Vizhinjam, clear season)**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi vizhinjam --start 2021-01-01 --end 2021-03-31
```

Expected: exit 0; summary line with usable ≥ 0.7; PNG at `data/vizhinjam_<date>_<id>.png` on the host.

- [ ] **Step 3: Eyeball the PNG**

Open `data/vizhinjam_*.png` (Read tool renders it). Expect coastline + port area, sensible colours, no black stripes. Refine the AOI bbox in `aois.py` if the framing is off, re-run, and note the final bbox in Spike Findings.

- [ ] **Step 4: Idempotency spot-check (live)**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi vizhinjam --start 2021-01-01 --end 2021-03-31
docker compose exec postgis psql -U overwatch -d overwatch -c "SELECT count(*), max(stac_id) FROM scenes WHERE aoi_slug='vizhinjam'"
```

Expected: second run selects the same scene; count stays 1.

- [ ] **Step 5: Lint, full suite, commit**

```bash
docker compose exec api sh -c "ruff check --fix . && ruff format . && pytest -q"
git add backend/src/overwatch/imagery/cli.py
git commit -m "feat(phase-1): ingestion CLI wiring search, gate, PNG, persistence"
```

---

### Task 12: CI — PostGIS service for the DB tests

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: green CI including `test_scenes_db.py` against a postgis service container.

- [ ] **Step 1: Add the service + env to the backend job**

The backend job becomes:

```yaml
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    services:
      postgis:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_USER: overwatch
          POSTGRES_PASSWORD: overwatch_dev
          POSTGRES_DB: overwatch
        ports:
          - "5432:5432"
        options: >-
          --health-cmd "pg_isready -U overwatch -d overwatch"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      OVERWATCH_DATABASE_URL: postgresql://overwatch:overwatch_dev@localhost:5432/overwatch
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check . && ruff format --check .
      - name: Test
        run: pytest -v
```

- [ ] **Step 2: Commit and push the branch**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(phase-1): postgis service for scene persistence tests"
git push -u origin phase-1-imagery-ingestion
```

- [ ] **Step 3: Verify CI green (Actions API, read-only)**

Wait ~3 min, then check the latest run for the branch via the Actions API using the stored git credential (never print the token). Expected: `conclusion: success` for both jobs. If red: read the failing step's log, fix, push, re-check.

---

### Task 13: Verification battery — pairs, negative test, 3-AOI viability, PROGRESS

**Files:**
- Modify: `plans/2026-07-03-phase-1-imagery-ingestion.md` (record results in Spike Findings appendix)
- Modify: `PROGRESS.md`

- [ ] **Step 1: Vizhinjam construction pair (the eyeball gate)**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi vizhinjam --start 2021-01-01 --end 2021-03-31
docker compose exec api python -m overwatch.imagery.cli --aoi vizhinjam --start 2025-01-01 --end 2025-03-31
```

Eyeball both PNGs side by side: the 2025 image must show the completed breakwater/terminal absent or partial in 2021. This is the phase's core gate.

- [ ] **Step 2: Negative test — monsoon window demonstrably skips cloudy scenes**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi vizhinjam --start 2021-06-15 --end 2021-07-15 --max-cloud 100
```

Expected evidence (either satisfies the gate): log lines `skipping <id>: usable=0.xxx < 0.700` proving the SCL gate rejected real cloudy scenes and the window widened; final outcome may be exit 1 (`NO USABLE SCENE`) or a late clear scene — capture the log either way.

- [ ] **Step 3: Novo Progresso viability (dry-season pair, consecutive years)**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi novo-progresso --start 2023-06-15 --end 2023-08-15
docker compose exec api python -m overwatch.imagery.cli --aoi novo-progresso --start 2024-06-15 --end 2024-08-15
```

Eyeball: forest matrix with clearings; year-2 shows more/larger clearings.

- [ ] **Step 4: Porto Alegre viability (pre-flood vs inundation)**

```bash
docker compose exec api python -m overwatch.imagery.cli --aoi porto-alegre --start 2024-04-01 --end 2024-04-30 --max-cloud 80
docker compose exec api python -m overwatch.imagery.cli --aoi porto-alegre --start 2024-05-04 --end 2024-05-31 --max-cloud 80
```

Eyeball: May image shows visibly expanded water vs April. Storm-season cloud may force the widen path — that is fine as long as a usable May-era scene lands. If no usable flood-window scene exists, record it and flag the Valencia DANA fallback (design spec §5) for a user decision — do not swap unilaterally.

- [ ] **Step 5: Confirm persisted rows for all three AOIs**

```bash
docker compose exec postgis psql -U overwatch -d overwatch -c "SELECT aoi_slug, stac_id, captured_at::date, round(cloud_pct::numeric,1) AS cloud, round(usable_fraction::numeric,3) AS usable FROM scenes ORDER BY aoi_slug, captured_at"
```

Expected: ≥2 rows for vizhinjam, ≥2 for novo-progresso, up to 2 for porto-alegre; no duplicates.

- [ ] **Step 6: Record results + update PROGRESS.md**

Append run results (scene ids, usable fractions, final bboxes, eyeball notes) to this plan's Spike Findings appendix. Update `PROGRESS.md`: move Phase 1 into **Built & verified** with the verification evidence, set **Next up** to Phase 2, note any deviations.

- [ ] **Step 7: Final gate — verification-before-completion**

Run the full suite + lint one last time; confirm CI green on the branch; then:

```bash
git add plans/2026-07-03-phase-1-imagery-ingestion.md PROGRESS.md
git commit -m "docs(phase-1): verification evidence and PROGRESS update"
git push
```

Give the user the compare URL: `https://github.com/yash2484/Overwatch/compare/main...phase-1-imagery-ingestion`

---

## Verification Gate (roadmap, verbatim — every item needs recorded evidence before "done")

- [ ] Two clear Vizhinjam scenes spanning known construction rendered as PNGs and eyeballed (Task 13, Step 1).
- [ ] Usable-pixel gate demonstrably skips a cloudy scene — negative test (Task 13, Step 2).
- [ ] Scene rows idempotent on re-run (Task 10 CI test + Task 11 Step 4 live check).
- [ ] Viability confirmed (or fallback flagged for user decision) for all three AOIs (Task 13, Steps 3–5).
- [ ] CI green on the branch.

---

## Spike Findings

### API surface (Task 2, run 2026-07-03 against live Earth Search v1)

- Endpoint `https://earth-search.aws.element84.com/v1`, collection `sentinel-2-l2a`: works, no auth. 5 items < 20% cloud for Vizhinjam Jan–Mar 2021.
- Spike item: `S2A_43PGK_20210304_2_L2A` (2021-03-04T05:26:32Z, cloud 10.5%). Vizhinjam sits on UTM tile **43PGK**.
- **EPSG lives in `proj:code` = `"EPSG:32643"` (STAC proj v2). There is NO `proj:epsg` on items** — the `_epsg_from_props` fallback chain is load-bearing, not defensive.
- **Asset keys confirmed:** `red` (B04), `green` (B03), `blue` (B02), `nir` (B08), `scl` (SCL) — plus `visual`, `nir08/09`, `swir16/22`, `rededge1-3`, `aot`, `wvp`, `coastal`, metadata assets, and `-jp2` variants of everything.
- **Hrefs:** public HTTPS on `https://sentinel-cogs.s3.us-west-2.amazonaws.com/...` — vsicurl reads need no credentials.
- **Windowed read verified:** seed bbox → window (col 1585, row 7148, 554×446) of a 10980×10980 raster; read shape (446, 554) uint16, min 110 / max 5464. Megabytes, not the ~1 GB scene.
- Gotcha: numpy 2.5 raises a `DeprecationWarning` ("Setting the shape on a NumPy array") inside `rasterio.windows` — harmless noise today; will break on a future numpy. Pin-watch rasterio releases.

*(Tasks 11/13 append: final bboxes, selected scene ids, usable fractions, eyeball notes.)*
