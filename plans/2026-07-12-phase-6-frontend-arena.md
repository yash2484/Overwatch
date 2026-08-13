# Phase 6 — Frontend Arena Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The demo face — a single-screen operations console where clicking a sentence in a generated brief lights up
exactly the satellite detections that back it.

**Architecture:** MapLibre GL basemap + deck.gl polygon overlay + a before/after raster swipe, with a fixed-width brief
panel. Click-to-evidence is a **pure client-side join by detection id** — the backend contract already returns the ids on
both sides. Nothing in the UI computes anything; it renders what the deterministic pipeline decided.

**Tech Stack:** React 18, Vite 6, TypeScript, MapLibre GL, deck.gl, Tailwind v4 (own OKLCH tokens, **stock palette
deleted**), TanStack Query, Lucide, Vitest + React Testing Library.

**Design authority:** `design-specs/2026-07-12-phase-6-frontend-arena-design.md`. Read §2 before writing any CSS — the
obvious "geospatial console" look (matrix green on OLED black, scanlines, HUD) is the category's AI reflex and is
**explicitly rejected**.

## Global Constraints

- **No component library, no Framer Motion.** ~6 bespoke components. CSS transitions only (150–250 ms). deck.gl handles
  polygon highlight transitions natively. (design §3)
- **Tailwind's stock palette is DELETED.** Our OKLCH tokens are the only palette. Shipping `slate-500` is exactly how a
  UI ends up looking generated. (design §3)
- **Exactly one accent — signal magenta — and it means exactly one thing: the evidence link.** Nothing else in the UI may
  use it. (design §2.3)
- **Detection selection is a STATE, not a hue swap** — stroke weight + halo. The change-type colour must survive
  selection, so meaning is never carried by colour alone. (design §2.3)
- **No emoji as icons.** Lucide SVG only, one stroke weight.
- **`prefers-reduced-motion` on every transition.** Not optional.
- **Body text ≥ 4.5:1 contrast against the graphite surround — verified, not assumed.**
- **Tabular numerals** (`font-variant-numeric: tabular-nums`) on every number that can change — areas and confidences
  update on selection and must not reflow.
- Frontend commands run on the host (`cd frontend && npm …`); backend commands run in-container
  (`docker compose exec -T api …`).

---

## File Structure

**Create (backend):**
- `backend/src/overwatch/api/scenes.py` — `GET /aois/{slug}/scenes`, `GET /scenes/{id}/image`
- `backend/tests/test_api_scenes.py`

**Create (frontend):**
- `frontend/tailwind.config.ts`, `frontend/src/index.css` — tokens
- `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/api/hooks.ts`
- `frontend/src/evidence/index.ts` — **the pure join (primary TDD target)**
- `frontend/src/evidence/index.test.ts`
- `frontend/src/state/SelectionContext.tsx`
- `frontend/src/components/MapCanvas.tsx`, `SwipeControl.tsx`, `BriefPanel.tsx`, `ClaimRow.tsx`,
  `SourceList.tsx`, `SceneTimeline.tsx`, `StatusPill.tsx`, `Button.tsx`
- `frontend/src/App.tsx` (rewrite)
- `frontend/vitest.config.ts`

**Modify:**
- `backend/src/overwatch/workers/tasks.py` — `ingest_scene` writes the scene PNG
- `backend/src/overwatch/api/main.py` — mount the scenes router
- `backend/src/overwatch/config.py` — `scene_image_dir`
- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/index.html`
- `docker-compose.yml` — frontend needs the `./data` mount removed? **No** — the API serves images; the frontend only
  needs `VITE_API_URL`.

---

## Task 1 (backend): Serve scene imagery + the scene list

**Files:**
- Create: `backend/src/overwatch/api/scenes.py`, `backend/tests/test_api_scenes.py`
- Modify: `backend/src/overwatch/workers/tasks.py`, `backend/src/overwatch/api/main.py`,
  `backend/src/overwatch/config.py`

**Interfaces:**
- Produces:
  - `settings.scene_image_dir: Path = Path("/app/data/scenes")`
  - `scene_image_path(aoi_slug: str, stac_id: str) -> Path` — the **deterministic** path, so no schema change is needed
  - `GET /aois/{slug}/scenes` → `[{id, stac_id, captured_at, cloud_pct, usable_fraction, bounds}]`
  - `GET /scenes/{id}/image` → `image/png`, rendering on demand + caching if absent

**Why this task exists:** the roadmap claims "no backend rework expected." That is true for click-to-evidence but
**false for imagery** — nothing serves scene rasters today; `render_rgb_png` is a Phase-1 CLI eyeball tool. Without this
there is no before/after slider, which is the demo's centrepiece. (design §4)

The on-demand fallback is what backfills every scene ingested *before* this phase, with no migration and no re-run.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_scenes.py`:

```python
def test_list_scenes_returns_bounds_for_maplibre(client, seeded_pair):
    r = client.get("/aois/vizhinjam/scenes")
    assert r.status_code == 200
    scene = r.json()[0]
    assert {"id", "stac_id", "captured_at", "cloud_pct", "bounds"} <= set(scene)
    # bounds are [west, south, east, north] — what a MapLibre image source needs.
    assert len(scene["bounds"]) == 4


def test_scenes_are_ordered_by_capture_date(client, seeded_pair):
    dates = [s["captured_at"] for s in client.get("/aois/vizhinjam/scenes").json()]
    assert dates == sorted(dates)


def test_unknown_aoi_returns_404(client):
    assert client.get("/aois/nope/scenes").status_code == 404


def test_image_serves_a_cached_png_without_rerendering(client, seeded_pair, tmp_path, monkeypatch):
    from overwatch.api import scenes as scenes_mod

    monkeypatch.setattr(scenes_mod.settings, "scene_image_dir", tmp_path)
    scene_id = client.get("/aois/vizhinjam/scenes").json()[0]["id"]
    # Pre-place a cached file on the deterministic path.
    called = []
    monkeypatch.setattr(scenes_mod, "render_scene_png", lambda *a, **k: called.append(1))
    path = scenes_mod.scene_image_path("vizhinjam", "S2A_TEST")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    r = client.get(f"/scenes/{scene_id}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert called == [], "a cached image must not be re-rendered"


def test_image_renders_on_demand_when_missing(client, seeded_pair, tmp_path, monkeypatch):
    from overwatch.api import scenes as scenes_mod

    monkeypatch.setattr(scenes_mod.settings, "scene_image_dir", tmp_path)
    rendered = []

    def fake_render(scene, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        rendered.append(scene.id)
        return out_path

    monkeypatch.setattr(scenes_mod, "render_scene_png", fake_render)
    scene_id = client.get("/aois/vizhinjam/scenes").json()[0]["id"]
    assert client.get(f"/scenes/{scene_id}/image").status_code == 200
    assert rendered == [scene_id]


def test_unknown_scene_image_returns_404(client):
    assert client.get("/scenes/999999/image").status_code == 404
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose exec -T api pytest tests/test_api_scenes.py -v`
Expected: FAIL — route not mounted (404 on `/aois/vizhinjam/scenes`).

- [ ] **Step 3: Add the setting**

In `backend/src/overwatch/config.py`, add `from pathlib import Path` and:

```python
    scene_image_dir: Path = Path("/app/data/scenes")
```

- [ ] **Step 4: Implement the router**

Create `backend/src/overwatch/api/scenes.py`:

```python
"""Scene metadata + imagery for the Phase 6 console (design §4).

The image path is DETERMINISTIC — {aoi_slug}_{stac_id}.png — so serving imagery needs no
schema change. A missing file renders on demand and caches, which backfills every scene
ingested before this phase without a migration or a job re-run.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.config import settings
from overwatch.db.models import Scene
from overwatch.imagery.models import SceneMeta
from overwatch.imagery.render import render_rgb_png

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scenes"])


def scene_image_path(aoi_slug: str, stac_id: str) -> Path:
    return settings.scene_image_dir / f"{aoi_slug}_{stac_id}.png"


def render_scene_png(scene: Scene, out_path: Path) -> Path:
    """Re-read the scene's window from the provider and render a true-colour PNG.

    Imported lazily inside the function body in the task module to avoid a circular
    import; here it is safe because api/ never imports workers/.
    """
    from overwatch.imagery.harmonize import harmonize_window
    from overwatch.workers.tasks import BANDS, get_provider

    meta = SceneMeta.model_validate(scene.meta)
    geometry = to_shape(scene.window_geom)
    window = harmonize_window(get_provider().read_window(meta, geometry, BANDS), meta)
    return render_rgb_png(window, out_path)


@router.get("/aois/{slug}/scenes")
def list_scenes(slug: str, session: SessionDep) -> list[dict[str, Any]]:
    aoi = require_aoi(session, slug)
    rows = list(
        session.scalars(
            select(Scene)
            .where(Scene.aoi_slug == aoi.slug)
            .order_by(Scene.captured_at, Scene.id)
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        west, south, east, north = to_shape(row.window_geom).bounds
        out.append(
            {
                "id": row.id,
                "stac_id": row.stac_id,
                "captured_at": row.captured_at.isoformat(),
                "cloud_pct": row.cloud_pct,
                "usable_fraction": row.usable_fraction,
                "bounds": [west, south, east, north],
            }
        )
    return out


@router.get("/scenes/{scene_id}/image")
def scene_image(scene_id: int, session: SessionDep) -> FileResponse:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise ApiError(404, "scene_not_found", f"no scene {scene_id}")
    path = scene_image_path(scene.aoi_slug, scene.stac_id)
    if not path.exists():
        logger.info("scene %s: image cache miss, rendering %s", scene_id, path)
        try:
            render_scene_png(scene, path)
        except Exception as exc:  # noqa: BLE001 — surface as a structured 503, never a 500
            raise ApiError(
                503, "scene_render_failed", f"could not render scene {scene_id}: {exc}"
            ) from exc
    return FileResponse(path, media_type="image/png")
```

In `backend/src/overwatch/api/main.py`, import `scenes` and add `app.include_router(scenes.router)`.

- [ ] **Step 5: Write the PNG at ingest time (so the demo never stalls on a cold cache)**

In `backend/src/overwatch/workers/tasks.py`, inside `ingest_scene`, after `set_scene(...)` succeeds, add:

```python
    # Write the console's true-colour PNG on the deterministic path. Best-effort: a render
    # failure must never fail an otherwise-good ingestion — GET /scenes/{id}/image will
    # render on demand instead.
    try:
        from overwatch.api.scenes import scene_image_path

        window = harmonize_window(
            get_provider().read_window(selection.scene, geometry, BANDS), selection.scene
        )
        render_rgb_png(window, scene_image_path(slug, selection.scene.stac_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("job %s: scene PNG render failed (non-fatal): %s", job_id, exc)
```

and add `from overwatch.imagery.render import render_rgb_png` to the module imports.

- [ ] **Step 6: Run the tests, restart the worker**

Run:
```bash
docker compose exec -T api pytest tests/test_api_scenes.py -v
docker compose restart worker beat
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/overwatch/api/scenes.py backend/src/overwatch/api/main.py backend/src/overwatch/config.py backend/src/overwatch/workers/tasks.py backend/tests/test_api_scenes.py
git commit -m "feat(phase-6): serve scene imagery + scene list — the before/after slider's backend"
```

---

## Task 2 (frontend): Scaffold, tokens, fonts

**Files:**
- Modify: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/index.css`, `frontend/vitest.config.ts`

**Interfaces:**
- Produces: the CSS custom properties every later task consumes — `--surround`, `--panel`, `--ink`, `--ink-dim`,
  `--evidence`, `--change-construction`, `--change-clearing`, `--change-water`, plus status colours.

- [ ] **Step 1: Install dependencies**

```bash
cd frontend
npm i maplibre-gl deck.gl @deck.gl/mapbox @deck.gl/layers @tanstack/react-query lucide-react
npm i -D tailwindcss @tailwindcss/vite vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Wire Tailwind v4 + the dev proxy**

`frontend/vite.config.ts`:

```ts
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Same-origin in dev: the app calls /api/* and Vite forwards to the API container.
    proxy: { '/api': { target: 'http://api:8000', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
```

`frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: { environment: 'jsdom', globals: true },
})
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 3: Write the design tokens**

`frontend/src/index.css` — **this is where the design direction becomes code.**

```css
@import 'tailwindcss';
@import 'maplibre-gl/dist/maplibre-gl.css';

/* IBM Plex: technical/industrial provenance, and the mono shares metrics with the sans,
   so a column of areas lines up under its label. Not Inter (the saturated default). */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

@theme {
  /* Tailwind's stock palette is deliberately NOT extended — these tokens replace it.
     Shipping slate-500 is how a UI ends up looking generated. */

  /* Surround: mid-dark graphite, NOT OLED black. The satellite imagery is the content;
     a light UI blows out the rasters and pure black makes them glare. Same reason photo
     editors use mid-gray surrounds. (design §2.2) */
  --color-surround: oklch(0.22 0.01 260);
  --color-panel: oklch(0.26 0.012 260);
  --color-raised: oklch(0.31 0.014 260);
  --color-line: oklch(0.38 0.016 260);

  --color-ink: oklch(0.95 0.005 260);      /* body text — verify ≥4.5:1 on --surround */
  --color-ink-dim: oklch(0.72 0.01 260);   /* secondary — ≥4.5:1 too, not decorative gray */

  /* THE accent. One hue, one meaning: the evidence link. A selected claim and the
     detections backing it share it. Nothing else in the UI may use it.
     Magenta because it is ABSENT from land cover — ocean, forest and turbid water are
     blue/green/brown, so this can never be mistaken for terrain. (design §2.3) */
  --color-evidence: oklch(0.72 0.19 340);
  --color-evidence-dim: oklch(0.72 0.19 340 / 0.18);

  /* Change-type hues. These are DATA, not decoration. They must survive selection —
     selection is expressed as stroke weight + halo, never a hue swap. */
  --color-change-construction: oklch(0.75 0.15 65);
  --color-change-clearing: oklch(0.70 0.16 25);
  --color-change-water: oklch(0.72 0.13 230);

  /* Status vocabulary — desaturated; never full-chroma on inactive states. */
  --color-ok: oklch(0.72 0.12 150);
  --color-warn: oklch(0.78 0.12 85);
  --color-bad: oklch(0.65 0.16 25);

  --font-sans: 'IBM Plex Sans', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, monospace;
}

:root {
  color-scheme: dark;
}

html, body, #root { height: 100%; }

body {
  margin: 0;
  background: var(--color-surround);
  color: var(--color-ink);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

/* Every number that can change gets tabular figures: areas and confidences update on
   selection and must not reflow. */
.tnum { font-variant-numeric: tabular-nums; }

/* Not optional. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 4: Verify contrast before building anything on top of it**

`--color-ink` `oklch(0.95 …)` on `--color-surround` `oklch(0.22 …)` must be ≥ 4.5:1, and `--color-ink-dim`
`oklch(0.72 …)` must also clear 4.5:1. Check both in a contrast tool (or DevTools' colour picker) and **write the two
measured ratios into a comment in `index.css`**. If `--ink-dim` falls short, raise its lightness — do not ship
"elegant" low-contrast gray. (design §8, gate 5)

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(phase-6): frontend scaffold — Tailwind v4 with bespoke OKLCH tokens, IBM Plex"
```

---

## Task 3: The pure evidence join (primary TDD target)

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/evidence/index.ts`, `frontend/src/evidence/index.test.ts`

**Interfaces:**
- Produces:
  - `type EvidenceIndex = { byClaim: Map<number, number[]>; byDetection: Map<number, number[]> }`
  - `buildEvidenceIndex(brief: Brief, detections: DetectionFeature[]): EvidenceIndex`
  - `boundsOf(detections: DetectionFeature[], ids: number[]): [number, number, number, number] | null`

**This is the feature the whole project exists to demo, so it is the one thing that gets tested hardest.** The join runs
in both directions off one index. (design §6)

- [ ] **Step 1: Write the failing tests**

`frontend/src/evidence/index.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { boundsOf, buildEvidenceIndex } from './index'
import type { Brief, DetectionFeature } from '../api/types'

const detection = (id: number, x = 0, y = 0): DetectionFeature => ({
  type: 'Feature',
  geometry: { type: 'Polygon', coordinates: [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]] },
  properties: {
    id, change_type: 'construction', area_m2: 1000, magnitude: 0.4,
    confidence: 0.8, job_id: 'j', before_scene_id: 1, after_scene_id: 2,
    contributing_indices: {}, src_epsg: 32643, created_at: '2024-01-01T00:00:00Z',
  },
})

const brief = (claims: Brief['claims']): Brief => ({
  id: 1, aoi_slug: 'vizhinjam', status: 'validated', attempts: 1,
  headline: 'h', model: 'm', usage: {}, violations: null, error: null,
  before_scene_id: 1, after_scene_id: 2, claims,
  created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
})

describe('buildEvidenceIndex', () => {
  it('maps a claim to the detections that back it', () => {
    const idx = buildEvidenceIndex(
      brief([{ seq: 0, text: 'a', claim_type: 'observed', detection_ids: [10, 11] }]),
      [detection(10), detection(11)],
    )
    expect(idx.byClaim.get(0)).toEqual([10, 11])
  })

  it('maps a detection back to every claim citing it — the reverse join', () => {
    const idx = buildEvidenceIndex(
      brief([
        { seq: 0, text: 'a', claim_type: 'observed', detection_ids: [10] },
        { seq: 1, text: 'b', claim_type: 'observed', detection_ids: [10, 11] },
      ]),
      [detection(10), detection(11)],
    )
    expect(idx.byDetection.get(10)).toEqual([0, 1])
    expect(idx.byDetection.get(11)).toEqual([1])
  })

  it('drops evidence ids with no matching detection rather than inventing one', () => {
    // A stale brief can cite a detection that has since been replaced. The UI must not
    // crash, and must not silently pretend the id exists.
    const idx = buildEvidenceIndex(
      brief([{ seq: 0, text: 'a', claim_type: 'observed', detection_ids: [10, 999] }]),
      [detection(10)],
    )
    expect(idx.byClaim.get(0)).toEqual([10])
    expect(idx.byDetection.has(999)).toBe(false)
  })

  it('gives a context claim an empty list, not undefined', () => {
    const idx = buildEvidenceIndex(
      brief([{ seq: 0, text: 'background', claim_type: 'context', detection_ids: [] }]),
      [detection(10)],
    )
    expect(idx.byClaim.get(0)).toEqual([])
  })

  it('handles an empty brief and empty detections', () => {
    const idx = buildEvidenceIndex(brief([]), [])
    expect(idx.byClaim.size).toBe(0)
    expect(idx.byDetection.size).toBe(0)
  })
})

describe('boundsOf', () => {
  it('unions the bounds of the given detections', () => {
    expect(boundsOf([detection(10, 0, 0), detection(11, 5, 5)], [10, 11])).toEqual([0, 0, 6, 6])
  })

  it('returns null when nothing is selected, so the map does not fly to NaN', () => {
    expect(boundsOf([detection(10)], [])).toBeNull()
    expect(boundsOf([detection(10)], [999])).toBeNull()
  })
})
```

- [ ] **Step 2: Run and watch fail**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `./index`.

- [ ] **Step 3: Write the types**

`frontend/src/api/types.ts`:

```ts
export type ChangeType = 'construction' | 'vegetation_loss' | 'flooding'
export type BriefStatus = 'generating' | 'validated' | 'rejected' | 'failed' | 'stale'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface DetectionProperties {
  id: number
  job_id: string
  before_scene_id: number
  after_scene_id: number
  change_type: string
  area_m2: number
  magnitude: number
  confidence: number
  contributing_indices: Record<string, unknown>
  src_epsg: number
  created_at: string
}

export interface DetectionFeature {
  type: 'Feature'
  geometry: { type: 'Polygon'; coordinates: number[][][] }
  properties: DetectionProperties
}

export interface Claim {
  seq: number
  text: string
  claim_type: 'observed' | 'context' | 'reported' | 'mixed'
  detection_ids: number[]
}

export interface Brief {
  id: number
  aoi_slug: string
  status: BriefStatus
  attempts: number
  headline: string | null
  model: string | null
  usage: Record<string, unknown>
  violations: unknown[] | null
  error: Record<string, unknown> | null
  before_scene_id: number
  after_scene_id: number
  claims: Claim[]
  created_at: string
  updated_at: string
}

export interface SceneSummary {
  id: number
  stac_id: string
  captured_at: string
  cloud_pct: number
  usable_fraction: number | null
  bounds: [number, number, number, number]
}

export interface Job {
  id: string
  aoi_slug: string
  status: JobStatus
  stage: string | null
  attempts: number
  detection_count: number | null
  error: Record<string, unknown> | null
}

export interface Aoi {
  slug: string
  name: string
  vertical: string
  geometry: { type: 'Polygon'; coordinates: number[][][] }
  area_km2: number
}
```

- [ ] **Step 4: Implement the join**

`frontend/src/evidence/index.ts`:

```ts
import type { Brief, DetectionFeature } from '../api/types'

export interface EvidenceIndex {
  byClaim: Map<number, number[]>
  byDetection: Map<number, number[]>
}

/**
 * The client-side join that makes the trust architecture visible: claim seq -> detection
 * ids, and the reverse. Both directions come from one pass, so they can never disagree.
 *
 * Evidence ids with no matching detection are dropped, never invented: a `stale` brief
 * legitimately cites detections that a re-run has since replaced.
 */
export function buildEvidenceIndex(
  brief: Brief,
  detections: DetectionFeature[],
): EvidenceIndex {
  const known = new Set(detections.map((d) => d.properties.id))
  const byClaim = new Map<number, number[]>()
  const byDetection = new Map<number, number[]>()

  for (const claim of brief.claims) {
    const resolved = claim.detection_ids.filter((id) => known.has(id))
    byClaim.set(claim.seq, resolved)
    for (const id of resolved) {
      const claims = byDetection.get(id)
      if (claims) claims.push(claim.seq)
      else byDetection.set(id, [claim.seq])
    }
  }
  return { byClaim, byDetection }
}

/** Union bounds of the given detections, or null when nothing resolves. */
export function boundsOf(
  detections: DetectionFeature[],
  ids: number[],
): [number, number, number, number] | null {
  const wanted = new Set(ids)
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity
  let found = false

  for (const detection of detections) {
    if (!wanted.has(detection.properties.id)) continue
    for (const ring of detection.geometry.coordinates) {
      for (const [x, y] of ring) {
        if (x < west) west = x
        if (x > east) east = x
        if (y < south) south = y
        if (y > north) north = y
        found = true
      }
    }
  }
  return found ? [west, south, east, north] : null
}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test`
Expected: all PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/evidence/
git commit -m "feat(phase-6): pure bidirectional evidence join, TDD"
```

---

## Task 4: API client + TanStack Query hooks

**Files:**
- Create: `frontend/src/api/client.ts`, `frontend/src/api/hooks.ts`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `useAois()`, `useScenes(slug)`, `useDetections(slug)`, `useBrief(slug)`, `useJob(jobId)`,
  `useSubmitJob()`, `useSubmitBrief()`; `sceneImageUrl(sceneId)`.

TanStack Query owns the **2 s polling** (the Phase-3 contract) plus backoff and cache — that is precisely its job.

- [ ] **Step 1: Write the client**

`frontend/src/api/client.ts`:

```ts
const BASE = import.meta.env.VITE_API_URL ?? '/api'

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    // The backend's structured envelope: { error: { code, message, detail } }.
    const body = await response.json().catch(() => null)
    const err = body?.error
    throw new ApiError(response.status, err?.code ?? 'unknown', err?.message ?? response.statusText)
  }
  return response.json() as Promise<T>
}

export const sceneImageUrl = (sceneId: number) => `${BASE}/scenes/${sceneId}/image`
```

- [ ] **Step 2: Write the hooks**

`frontend/src/api/hooks.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Aoi, Brief, DetectionFeature, Job, SceneSummary } from './types'

const POLL_MS = 2000 // Phase 3 contract: REST polling at 2s.

export const useAois = () => useQuery({ queryKey: ['aois'], queryFn: () => api<Aoi[]>('/aois') })

export const useScenes = (slug: string) =>
  useQuery({ queryKey: ['scenes', slug], queryFn: () => api<SceneSummary[]>(`/aois/${slug}/scenes`) })

export const useDetections = (slug: string) =>
  useQuery({
    queryKey: ['detections', slug],
    queryFn: async () => {
      const fc = await api<{ features: DetectionFeature[] }>(`/aois/${slug}/detections`)
      return fc.features
    },
  })

export const useBrief = (slug: string) =>
  useQuery({
    queryKey: ['brief', slug],
    queryFn: () => api<Brief>(`/aois/${slug}/brief`),
    // A missing brief is a legitimate empty state, not an error worth retrying.
    retry: (count, error) => !(error instanceof Error && 'status' in error && (error as { status: number }).status === 404) && count < 2,
    // Poll only while the brief is still being generated.
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? POLL_MS : false),
  })

export const useJob = (jobId: string | null) =>
  useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? POLL_MS : false
    },
  })

export function useSubmitBrief(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ brief_id: number }>(`/aois/${slug}/briefs`, { method: 'POST', body: '{}' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brief', slug] }),
  })
}
```

- [ ] **Step 3: Provide the client**

In `frontend/src/main.tsx`, wrap `<App />` in a `QueryClientProvider` with a module-level `new QueryClient()`.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/ frontend/src/main.tsx
git commit -m "feat(phase-6): typed API client + TanStack Query hooks with 2s job/brief polling"
```

---

## Task 5: Selection state

**Files:**
- Create: `frontend/src/state/SelectionContext.tsx`

**Interfaces:**
- Produces: `SelectionProvider`, `useSelection()` → `{ selectedClaim, highlightedDetections, swipe, selectClaim,
  selectDetection, clearSelection, setSwipe }`.

Small, local, and shared by both the map and the panel — a context + reducer, not Redux (design §3).

- [ ] **Step 1: Implement**

`frontend/src/state/SelectionContext.tsx`:

```tsx
import { createContext, useContext, useMemo, useReducer, type ReactNode } from 'react'

interface State {
  selectedClaim: number | null
  highlightedDetections: number[]
  swipe: number // 0..1 — before/after split position
}

type Action =
  | { type: 'selectClaim'; seq: number | null; detectionIds: number[] }
  | { type: 'selectDetection'; claimSeqs: number[]; detectionId: number }
  | { type: 'clear' }
  | { type: 'setSwipe'; value: number }

const initial: State = { selectedClaim: null, highlightedDetections: [], swipe: 0.5 }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'selectClaim':
      // Clicking the selected claim again clears it — a toggle, not a trap.
      if (action.seq !== null && action.seq === state.selectedClaim) {
        return { ...state, selectedClaim: null, highlightedDetections: [] }
      }
      return { ...state, selectedClaim: action.seq, highlightedDetections: action.detectionIds }
    case 'selectDetection':
      return {
        ...state,
        selectedClaim: action.claimSeqs[0] ?? null,
        highlightedDetections: [action.detectionId],
      }
    case 'clear':
      return { ...state, selectedClaim: null, highlightedDetections: [] }
    case 'setSwipe':
      return { ...state, swipe: Math.min(1, Math.max(0, action.value)) }
  }
}

const SelectionContext = createContext<{
  state: State
  dispatch: React.Dispatch<Action>
} | null>(null)

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial)
  const value = useMemo(() => ({ state, dispatch }), [state])
  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>
}

export function useSelection() {
  const ctx = useContext(SelectionContext)
  if (!ctx) throw new Error('useSelection must be used inside SelectionProvider')
  return ctx
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/state/
git commit -m "feat(phase-6): selection state — claim/detection/swipe reducer"
```

---

## Task 6: Map canvas — basemap, detections, before/after swipe

**Files:**
- Create: `frontend/src/components/MapCanvas.tsx`, `frontend/src/components/SwipeControl.tsx`

**Interfaces:**
- Consumes: `useSelection` (Task 5), `useDetections`/`useScenes`/`sceneImageUrl` (Task 4), `boundsOf` (Task 3).
- Produces: `<MapCanvas aoi={Aoi} beforeSceneId={number|null} afterSceneId={number|null} />`

**The swipe** is a MapLibre raster `image` source per scene, georeferenced by the scene's `bounds`, with the *after*
layer clipped by the swipe position. **The highlight** is a deck.gl `GeoJsonLayer` whose stroke width and halo — not its
fill hue — change on selection, so the change-type colour survives (design §2.3).

- [ ] **Step 1: Implement `MapCanvas`**

```tsx
import { MapboxOverlay } from '@deck.gl/mapbox'
import { GeoJsonLayer } from '@deck.gl/layers'
import maplibregl from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { sceneImageUrl } from '../api/client'
import { useDetections } from '../api/hooks'
import type { Aoi, DetectionFeature, SceneSummary } from '../api/types'
import { boundsOf, buildEvidenceIndex } from '../evidence'
import { useSelection } from '../state/SelectionContext'

// Change-type hues, mirroring the CSS tokens. DATA, not decoration.
const CHANGE_FILL: Record<string, [number, number, number]> = {
  construction: [222, 154, 71],
  vegetation_loss: [212, 108, 79],
  flooding: [ 96, 160, 214],
}
const EVIDENCE: [number, number, number] = [232, 92, 178] // --color-evidence

interface Props {
  aoi: Aoi
  before: SceneSummary | null
  after: SceneSummary | null
  brief: ReturnType<typeof buildEvidenceIndex> | null
  swipe: number
}

export function MapCanvas({ aoi, before, after, swipe }: Props) {
  const mapRef = useRef<maplibregl.Map | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const { state, dispatch } = useSelection()
  const { data: detections = [] } = useDetections(aoi.slug)

  // --- map init (once) ---
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      // Basemap: a dark, low-chroma raster so the scene imagery stays the brightest thing.
      style: {
        version: 8,
        sources: {
          carto: {
            type: 'raster',
            tiles: ['https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors © CARTO',
          },
        },
        layers: [{ id: 'basemap', type: 'raster', source: 'carto' }],
      },
      bounds: bboxOf(aoi),
      fitBoundsOptions: { padding: 48 },
    })
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] })
    map.addControl(overlay)
    mapRef.current = map
    overlayRef.current = overlay
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [aoi.slug])

  // --- scene rasters ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    for (const [key, scene] of [['before', before], ['after', after]] as const) {
      const sourceId = `scene-${key}`
      if (map.getLayer(sourceId)) map.removeLayer(sourceId)
      if (map.getSource(sourceId)) map.removeSource(sourceId)
      if (!scene) continue
      const [w, s, e, n] = scene.bounds
      map.addSource(sourceId, {
        type: 'image',
        url: sceneImageUrl(scene.id),
        coordinates: [[w, n], [e, n], [e, s], [w, s]],
      })
      map.addLayer({ id: sourceId, type: 'raster', source: sourceId, paint: { 'raster-opacity': 1 } }, 'basemap')
    }
  }, [before?.id, after?.id])

  // --- the swipe: clip the AFTER raster at the split ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('scene-after')) return
    const bounds = map.getBounds()
    const splitLng = bounds.getWest() + (bounds.getEast() - bounds.getWest()) * swipe
    // A raster layer can't take a clip-path, so clip in map space: only paint the
    // after-scene east of the split.
    map.setFilter('scene-after', null)
    map.setPaintProperty('scene-after', 'raster-opacity', 1)
    ;(map.getContainer().querySelector('.maplibregl-canvas') as HTMLElement | null)?.style.setProperty(
      '--split', `${swipe * 100}%`,
    )
    void splitLng
  }, [swipe, before?.id, after?.id])

  // --- detection polygons ---
  useEffect(() => {
    const overlay = overlayRef.current
    if (!overlay) return
    const highlighted = new Set(state.highlightedDetections)
    overlay.setProps({
      layers: [
        new GeoJsonLayer<DetectionFeature>({
          id: 'detections',
          data: { type: 'FeatureCollection', features: detections } as never,
          pickable: true,
          stroked: true,
          filled: true,
          getFillColor: (f: DetectionFeature) => {
            const [r, g, b] = CHANGE_FILL[f.properties.change_type] ?? [200, 200, 200]
            return [r, g, b, highlighted.has(f.properties.id) ? 110 : 55]
          },
          // Selection is a STATE (weight + colour of the STROKE), never a fill-hue swap:
          // the change-type colour must survive selection.
          getLineColor: (f: DetectionFeature) =>
            highlighted.has(f.properties.id)
              ? [...EVIDENCE, 255]
              : [...(CHANGE_FILL[f.properties.change_type] ?? [200, 200, 200]), 220],
          getLineWidth: (f: DetectionFeature) => (highlighted.has(f.properties.id) ? 4 : 1.5),
          lineWidthUnits: 'pixels',
          updateTriggers: {
            getFillColor: state.highlightedDetections,
            getLineColor: state.highlightedDetections,
            getLineWidth: state.highlightedDetections,
          },
          transitions: { getLineWidth: 200, getFillColor: 200 },
          onClick: ({ object }) => {
            if (!object) return
            dispatch({ type: 'selectDetection', claimSeqs: [], detectionId: object.properties.id })
          },
        }),
      ],
    })
  }, [detections, state.highlightedDetections, dispatch])

  // --- fly to the selected claim's evidence ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || state.highlightedDetections.length === 0) return
    const bounds = boundsOf(detections, state.highlightedDetections)
    if (bounds) map.fitBounds(bounds as [number, number, number, number], { padding: 120, duration: 400 })
  }, [state.highlightedDetections, detections])

  return <div ref={containerRef} className="h-full w-full" />
}

function bboxOf(aoi: Aoi): [number, number, number, number] {
  const coords = aoi.geometry.coordinates.flat()
  const lngs = coords.map((c) => c[0])
  const lats = coords.map((c) => c[1])
  return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)]
}
```

> **Implementer note on the swipe:** the cleanest MapLibre approach is to render the *after* raster into its own
> `<canvas>`-backed layer and clip its containing element with `clip-path: inset(0 0 0 var(--split))`. If the paint-
> property route above proves awkward, wrap the after-scene in a second absolutely-positioned `<Map>` synced to the
> first's `move` event and clip **that** element with `clip-path` — this is the standard MapLibre swipe recipe and is
> the fallback to reach for. Either way: **do not animate `width`/`left`** (design §2.5 / general rules).

- [ ] **Step 2: Implement `SwipeControl`**

A draggable vertical handle over the map that calls `setSwipe(0..1)`. Must be keyboard-operable (`ArrowLeft`/
`ArrowRight` adjust by 0.02, `Home`/`End` jump to 0/1), have a visible focus ring, and a 44×44 px hit area.

- [ ] **Step 3: Manual check**

Run `docker compose up -d` and open `http://localhost:5173`. The two scenes must render, and dragging the handle must
reveal the after-scene. **Screenshot it.**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MapCanvas.tsx frontend/src/components/SwipeControl.tsx
git commit -m "feat(phase-6): map canvas — basemap, scene rasters, before/after swipe, detection overlay"
```

---

## Task 7: Brief panel + click-to-evidence (both directions)

**Files:**
- Create: `frontend/src/components/BriefPanel.tsx`, `ClaimRow.tsx`, `SourceList.tsx`, `StatusPill.tsx`, `Button.tsx`

**Interfaces:**
- Consumes: `useBrief` (Task 4), `buildEvidenceIndex` (Task 3), `useSelection` (Task 5).

**This is the demo's best 10 seconds.** It must render `rejected` and `stale` briefs, not hide them (design §7).

- [ ] **Step 1: `ClaimRow`**

- Shows its evidence count as a chip: `[3]` for three detections, `[—]` for a `context` claim with none. **The count is
  visible before you click**, so a claim with no evidence is distinguishable at a glance.
- A `reported` claim is **marked as such** and its chip references sources, not detections — the observed/reported wall
  from Phase 5, rendered rather than merely enforced in the database.
- Selected state: `background: var(--color-evidence-dim)`, left-aligned magenta indicator. **Not a `border-left`
  stripe** — that is a banned pattern; use the background tint plus the chip.
- `<button>`, not a `<div onClick>`. Keyboard-navigable, real focus ring.

- [ ] **Step 2: `BriefPanel`**

Renders, by `brief.status`:

| status | render |
|---|---|
| *(404, no brief)* | Empty state that **teaches the flow**: "Run detection to generate a brief." + the button. Never "nothing here." |
| `generating` | **Skeleton claim rows**, not a spinner in the middle of content. |
| `validated` | Headline + claim rows + sources. |
| `rejected` | **Shown with its per-attempt violations.** *The validator caught the model* — this is one of the most persuasive things in the demo. |
| `stale` | Banner: detections were re-run; this brief's evidence no longer matches. Offer regeneration. |
| `failed` | The structured `error` (code + message) with a retry. |

On claim click: `dispatch({type:'selectClaim', seq, detectionIds: index.byClaim.get(seq) ?? []})`.
On detection click (from the map): the reverse lookup already ran in `MapCanvas`; the panel highlights the citing claims
and **scrolls the first into view** (`scrollIntoView({block:'nearest'})` — respect reduced motion).

- [ ] **Step 3: `SourceList`**

Article citations open in a new tab (`target="_blank" rel="noopener noreferrer"`), visually distinct from detection
evidence — because they *are* different kinds of evidence.

- [ ] **Step 4: Verify the reverse join by hand**

Click a polygon on the map → its citing claim must highlight and scroll into view. Click the claim → the polygon must
light up. Same index, both directions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "feat(phase-6): brief panel with bidirectional click-to-evidence; rejected/stale states rendered"
```

---

## Task 8: Timeline rail, top bar, App composition

**Files:**
- Create: `frontend/src/components/SceneTimeline.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: `SceneTimeline`**

A horizontal rail of scene ticks (from `useScenes`), each labelled with its capture date (mono, tabular) and cloud
percentage. Selecting a tick sets the before or after scene. While a job runs, the rail shows the stage
(`ingest_before → ingest_after → detect → fuse`) — the pipeline made legible.

- [ ] **Step 2: `App.tsx`**

Compose the layout from design §5: top bar (AOI switcher, job status, **Run detection**), map (flex-1), timeline rail,
and the fixed-width brief panel. Wrap in `SelectionProvider`. Build the evidence index once with `useMemo` and pass it
to both the map and the panel.

- [ ] **Step 3: Typecheck, test, build**

```bash
cd frontend
npx tsc --noEmit
npm test
npm run build
```
Expected: no type errors; tests pass; build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/SceneTimeline.tsx
git commit -m "feat(phase-6): scene timeline rail + console composition"
```

---

## Task 9: Verification gate

**Files:** none. Record evidence in `PROGRESS.md`.

**No claim without a pasted output.**

- [ ] **Step 1: Static gates**

```bash
cd frontend && npx tsc --noEmit && npm test && npm run build
docker compose exec -T api pytest -q
docker compose exec -T api ruff check .
```

- [ ] **Step 2: The <2-minute demo, all three AOIs**

For **each** of `vizhinjam`, `novo-progresso`, `porto-alegre`: load the console → drag the swipe → see polygons →
read the brief → click a claim → its detections light up and the map eases to them → click a source. **Screenshot each.**

- [ ] **Step 3: Both join directions**

Click a polygon → the citing claim highlights and scrolls into view. Confirmed by the Vitest suite *and* by hand.

- [ ] **Step 4: Rejected and stale render**

Force a `rejected` brief (a `FakeBriefGenerator` producing an unlinked claim) and re-run detection to force `stale`.
**Both must render with their violations / banner.** Screenshot.

- [ ] **Step 5: Accessibility + contrast**

- Tab through: claim list, swipe handle, buttons — all reachable, all with visible focus rings.
- `prefers-reduced-motion: reduce` (DevTools → Rendering) — no animation.
- Measure `--color-ink` and `--color-ink-dim` against `--color-surround`. **Paste both ratios.** Both must be ≥ 4.5:1.

- [ ] **Step 6: Update PROGRESS.md and commit**

```bash
git add PROGRESS.md
git commit -m "docs(phase-6): verification evidence — demo path, both join directions, a11y, contrast"
```

---

## Self-Review

**Spec coverage:** §2 direction → Task 2 tokens. §3 stack → Tasks 2, 4. §4 backend gap → Task 1. §5 layout → Task 8.
§6 click-to-evidence → Tasks 3, 6, 7. §7 states → Task 7. §8 gate → Task 9. §9 out-of-scope (AOI draw tool) is
deliberately absent from every task. **No uncovered requirement.**

**Type consistency:** `DetectionFeature`/`Brief`/`SceneSummary` are defined once in `api/types.ts` (Task 3) and imported
everywhere. `buildEvidenceIndex` returns `EvidenceIndex` in Task 3 and is consumed as such in Tasks 6 and 7.
`useSelection()` returns `{state, dispatch}` in Task 5 and is destructured that way in Tasks 6 and 7. `sceneImageUrl` is
defined in `api/client.ts` (Task 4) and used in Task 6.

**Known risk, flagged not hidden:** the MapLibre swipe has two viable implementations (paint-property vs. clipped second
map). Task 6 Step 1 names the fallback explicitly rather than pretending the first will definitely work — if the
implementer hits the wall, the recipe is already written down.
