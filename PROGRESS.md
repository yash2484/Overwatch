# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 1 — Imagery ingestion (next). Phase 0 **merged to main** (PR #1, 2026-07-03, CI green on merge commit). Start here: `plans/2026-07-03-mvp-roadmap.md` (session handover + all-phase roadmap).

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
- Nothing.

## Next up
- Phase 1 (fresh session): follow `plans/2026-07-03-mvp-roadmap.md` — write the Phase 1 plan with `superpowers:writing-plans`, then execute on branch `phase-1-imagery-ingestion`. STAC search for Vizhinjam, windowed COG reads, SCL masking, scenes persistence, PNG eyeball gate, viability check on all three AOIs.

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Morphology kernel sizes and threshold tuning — Phase 2, empirical.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI not installed — PR flow runs via GitHub UI (user merges); CI status checked read-only via Actions API with the stored git credential. Consider installing `gh`.
- Direct push to main is denied by permission settings — every phase ends with a branch push + compare URL for the user to merge.
- 2026-07-03: accidental "revert PR" on GitHub was closed unmerged; leftover `revert-1-phase-0-scaffold` branch deleted from origin. Main history is clean.
