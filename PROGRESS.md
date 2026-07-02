# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 1 — Imagery ingestion (next). Phase 0 complete and verified 2026-07-02.

## Last verified working
Full clean-slate stack: `docker compose down && docker compose up -d --build` → all 6 services up, all gates below pass (2026-07-02).

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
  8. CI: see note below — verified green on push to main.

## In progress
- Nothing.

## Next up
- Phase 1 plan (`superpowers:writing-plans`): STAC search for Vizhinjam AOI, windowed COG reads, SCL cloud masking, persist scene metadata; render two clear scenes spanning known change as PNGs and eyeball them. AOI viability check for all three showcase sites.

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Morphology kernel sizes and threshold tuning — Phase 2, empirical.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI not installed on this machine — PR-based flow unavailable; Phase 0 merged to main locally after clean-slate verification, CI verified via Actions API. Consider installing `gh` before Phase 1 review flows.
