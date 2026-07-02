# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 1 — Imagery ingestion, **Tasks 1–11 of 13 done** on branch `phase-1-imagery-ingestion` (plan: `plans/2026-07-03-phase-1-imagery-ingestion.md`, boxes ticked per task). Remaining: Task 12 (CI postgis service + push + green) and Task 13 (verification battery: Vizhinjam 2025 pair, monsoon negative test, Novo Progresso + Porto Alegre viability, PROGRESS final update, compare URL).

## Last verified working
Full clean-slate stack: `docker compose down && docker compose up -d --build` → all 6 services up, all gates below pass (2026-07-02). CI green on main after merge (verified via Actions API 2026-07-03).

## Built & verified
- [x] Brainstorm: all PROJECT.md `[BRAINSTORM]` tags resolved with user (fusion IN constrained; Vizhinjam / Novo Progresso / Porto Alegre AOIs; Earth Search; polling; no alerting; engineering defaults). *Verified: user approved design in-session 2026-07-02; PROJECT.md updated, grep confirms no unresolved tags.*
- [x] Design spec: `design-specs/2026-07-02-overwatch-mvp-design.md` (user-approved).
- [x] Phase 0 plan: `plans/2026-07-02-phase-0-scaffold.md` (all 8 tasks executed).
- [x] **Phase 0 — Scaffold.** *Verified 2026-07-02 on clean slate (`compose down` → `up -d --build`):*
  1. `GET /health` → `{"status":"ok"}`
  2. rasterio **1.5.0** (GDAL 3.12.1) imports in api container
  3. `pytest` in-container → **2 passed** (health + celery ping, both written TDD red→green)
  4. Celery worker `inspect ping` → 1 worker OK; beat starts clean
  5. PostGIS → `3.4 USE_GEOS=1 USE_PROJ=1 USE_STATS=1`
  6. Frontend serves `<title>Overwatch</title>` on :5173
  7. `ruff check` + `ruff format --check` → clean (9 files)
  8. CI: green on branch and on main merge commit (Actions API, 2026-07-03).

## In progress
- **Phase 1, Tasks 1–11 done & individually verified** (2026-07-03, all in-container, one commit per task on `phase-1-imagery-ingestion`):
  - Deps (pystac-client, sqlalchemy, geoalchemy2, psycopg3, alembic, pyproj, shapely, pillow) + dev bind mounts (`backend/src|tests|alembic`, `./data:/app/data`).
  - Spike verified Earth Search reality: **items carry `proj:code` ("EPSG:32643"), NOT `proj:epsg`**; asset keys `red/green/blue/nir/scl`; public HTTPS COGs; fixture at `backend/tests/fixtures/earth_search_item.json`. Findings appended to the phase plan.
  - TDD modules green (32 tests total): SCL masking, +15d/+60d window widening, AOI seeds, provider protocol + SCL gating (fake provider), PNG rendering, Earth Search provider (fixture-based), engine URL normalization, idempotent upsert (live PostGIS integration test).
  - `scenes` table via `alembic upgrade head`: unique `(stac_id, aoi_slug)`, single GiST index verified in psql.
  - CLI live-verified: Vizhinjam Jan–Mar 2021 → `S2A_43PGK_20210212_2_L2A`, 0.0% cloud, 99.9% usable, PNG eyeballed (breakwater under construction, framing good, bbox kept); re-run idempotent (count=1, same row id).
- Known minor: worker/beat containers still on pre-alembic image (harmless — fix with next `up -d --build`); rasterio DummySession INFO log noise; numpy 2.5 DeprecationWarning via rasterio (see plan Spike Findings).

## Next up
- Phase 1 Task 12: add postgis service to `.github/workflows/ci.yml` backend job (env `OVERWATCH_DATABASE_URL=postgresql://overwatch:overwatch_dev@localhost:5432/overwatch`), push, verify green via Actions API. Exact YAML is in the plan.
- Phase 1 Task 13: verification battery — Vizhinjam 2025-01..03 pair PNG + eyeball, monsoon negative test (2021-06-15..07-15 `--max-cloud 100`, expect logged skips), Novo Progresso dry-season pair (2023 vs 2024 Jun–Aug), Porto Alegre pre-flood Apr 2024 vs flood May 2024 (`--max-cloud 80`), psql row check, append results to plan Spike Findings, finish PROGRESS, push, give compare URL `https://github.com/yash2484/Overwatch/compare/main...phase-1-imagery-ingestion`.

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Morphology kernel sizes and threshold tuning — Phase 2, empirical.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI not installed — PR flow runs via GitHub UI (user merges); CI status checked read-only via Actions API with the stored git credential. Consider installing `gh`.
- Direct push to main is denied by permission settings — every phase ends with a branch push + compare URL for the user to merge.
- 2026-07-03: accidental "revert PR" on GitHub was closed unmerged; leftover `revert-1-phase-0-scaffold` branch deleted from origin. Main history is clean.
