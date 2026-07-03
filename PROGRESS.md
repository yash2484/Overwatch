# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 1 — Imagery ingestion: **complete and verified** on branch `phase-1-imagery-ingestion`, awaiting user merge via GitHub PR (compare: https://github.com/yash2484/Overwatch/compare/main...phase-1-imagery-ingestion). Next: Phase 2 — Change Detection Engine (fresh session, write plan first per `plans/2026-07-03-mvp-roadmap.md`).

## Last verified working
Phase 1 pipeline end-to-end (2026-07-03, in-container): STAC search → SCL gate → windowed COG read → PNG → PostGIS upsert for all three showcase AOIs; 32 tests + lint green locally and in CI (run 28644701633 with postgis service). Stack: 6 services up after fresh `up -d --build`.

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
- [x] Phase 1 plan: `plans/2026-07-03-phase-1-imagery-ingestion.md` (13 tasks, all executed; spike findings + battery results appended).
- [x] **Phase 1 — Imagery ingestion.** *Verified 2026-07-03, all in-container, evidence in the plan's Verification Gate section:*
  1. `ImageryProvider` protocol + Earth Search implementation (pystac-client search, rasterio windowed COG reads over public HTTPS; **items carry `proj:code`, not `proj:epsg`** — spike-verified).
  2. SCL masking + usable-pixel gate (≥70%) + auto-widening (+15d/+60d): **negative test** logged 9 skips at usable 0.000–0.002 on a monsoon window, then widened and selected a 0.925 scene. Scene-level `eo:cloud_cover` proven unreliable both directions over small windows.
  3. `scenes` in PostGIS via alembic (unique `(stac_id, aoi_slug)`, GiST index); idempotent upsert proven by CI integration test + live re-run (count stayed 1, same row id).
  4. Eyeball gate: Vizhinjam 2021-02-12 vs 2025-02-11 PNGs show breakwater stub → completed port with terminal + berthed vessel.
  5. Three-AOI viability confirmed, no fallbacks: Novo Progresso 2023/2024 dry-season pair (usable 1.000, clearings visibly expanded), Porto Alegre 2024-04-18 vs 2024-05-21 (usable 1.000, delta submerged). 8 scene rows, no duplicates.
  6. 32 tests + ruff green in-container and in CI (postgis service added to backend job).

## In progress
- Nothing (Phase 1 branch awaiting user merge).

## Next up
- User: open/merge the Phase 1 PR (CI re-runs on the PR via `pull_request` trigger; verify green before merging).
- Phase 2 (fresh session): Change Detection Engine (TDD) — the pure deterministic core. Write the plan with `superpowers:writing-plans` per the roadmap; synthetic-raster fixtures first, then the real Vizhinjam pair from Phase 1 (`scenes` rows + `data/*.png` document the pair: 2021-02-12 vs 2025-02-11).

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Morphology kernel sizes and threshold tuning — Phase 2, empirical.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI not installed — PR flow runs via GitHub UI (user merges); CI status checked read-only via Actions API with the stored git credential. Consider installing `gh`.
- Direct push to main is denied by permission settings — every phase ends with a branch push + compare URL for the user to merge.
- 2026-07-03: accidental "revert PR" on GitHub was closed unmerged; leftover `revert-1-phase-0-scaffold` branch deleted from origin. Main history is clean.
- numpy 2.5 `DeprecationWarning` surfaces via `rasterio.windows` (harmless; will break on a future numpy — watch rasterio releases). rasterio also logs "boto3 not available, DummySession" INFO noise on HTTPS reads (cosmetic).
- Negative-test runs ingested two real monsoon scenes for vizhinjam (2021-06-17 usable 0.734, 2021-07-17 usable 0.925) alongside the demo pair — legitimate rows, kept.
