# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 2 — Change Detection Engine: **merged to main** (PR #5). Follow-up hardening on branch `phase-2-forest-precondition` (was-forest precondition for the forest preset): complete and verified, awaiting user merge via GitHub PR (compare: https://github.com/yash2484/Overwatch/compare/main...phase-2-forest-precondition). Next: Phase 3 — Detection persistence + API + jobs (fresh session, write plan first per `plans/2026-07-03-mvp-roadmap.md`).

## Last verified working
Forest was-forest precondition (2026-07-07, in-container): forest preset now ANDs `ndvi_before ≥ 0.60` with the NDVI-decrease rule, so crop harvest no longer reads as deforestation. TDD: crop-harvest synthetic pair now yields 0 detections (was 1); genuine FOREST→BARE clearing still detected (regression guard). Real Novo Progresso pair dropped from **103 → 63** detections — removed polygons were cropland/pasture in fields already cleared by 2023; retained polygons sit on forest-edge transitions (eyeballed). 76 tests + ruff check + ruff format all green in-container.
Prior (PR #5, merged): Phase 2 engine end-to-end — Vizhinjam port pair → 9 construction polygons on the new terminal/breakwater; BOA-offset harmonization verified live on the mixed-baseline Vizhinjam pair (2025 scene offset −1000); 72 tests green.

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
- [x] Phase 2 plan: `plans/2026-07-06-phase-2-change-detection.md` (11 tasks, all executed; Verification Gate evidence appended).
- [x] **Phase 2 — Change Detection Engine (TDD).** *Verified 2026-07-07, all in-container; evidence in the plan's Verification Gate section:*
  1. Pure `overwatch.detection` package: `indices` (ndvi/ndwi/nbr, NaN-aware), `differencing` (index deltas + SSIM dissimilarity), `presets` (per-vertical pydantic configs — spec min-areas 1,500/5,000/10,000 m², thresholds never hardcoded), `postprocess` (AND-ed threshold rules ∩ usable mask → open→close morphology), `polygonize` (connected regions → typed `Detection` polygons with area/magnitude/confidence/contributing-indices), `detector` (`ChangeDetector` protocol + `ClassicalChangeDetector` composition; raises on shape/CRS/transform mismatch). No I/O, no LLM.
  2. Synthetic-injected-change TDD backbone (`tests/synthetic.py`): before/after `AOIWindow` pairs with a known rect; headline suite asserts polygon IoU > 0.5, change type, magnitude, confidence, and the negative cases (no-change, sub-min-area, under-cloud, mismatched-shape).
  3. Sentinel-2 BOA-offset harmonization: `SceneMeta.dn_offset` + `boa_dn_offset(props)` (−1000 for baseline ≥ 04.00 DNs still carrying the offset). Verified live on the mixed-baseline Vizhinjam pair (2021 = 0, 2025 = −1000).
  4. Eyeball gate: Vizhinjam 2021→2025 → 9 construction polygons tracing the completed terminal/reclaimed backyard/breakwater (largest 17,900 m²); Novo Progresso 2023→2024 → 103 vegetation-loss polygons on the BR-163 clearings. Overlay PNGs in `data/` (gitignored).
  5. 72 tests + `ruff check` + `ruff format --check` green in-container (40 new Phase-2 tests; no preset tuning needed — spec defaults held).

## In progress
- Nothing (Phase 2 branch awaiting user merge).

## Next up
- User: open/merge the Phase 2 PR (CI re-runs on the PR via `pull_request` trigger; verify green before merging).
- User: the Phase 1 PR (`phase-1-imagery-ingestion`) may still be open — merge order is Phase 1 then Phase 2, or rebase Phase 2 if Phase 1 lands first.
- Phase 3 (fresh session): Detection persistence + API + jobs. Write the plan with `superpowers:writing-plans` per the roadmap; persist `Detection` polygons to PostGIS, expose via FastAPI, wire the Celery job that runs the detector on ingested scene pairs.

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Preset thresholds/morphology are **engineering defaults, not tuned numbers** (design-spec §6 verbatim): port ssim_dissim≥0.35 ∧ ndvi≤−0.10, forest ndvi≤−0.20, flood ndwi≥0.20; min-areas 1,500/5,000/10,000 m²; open→close kernel 3px. They held on synthetic + real Vizhinjam/Novo pairs without tuning; revisit empirically if Phase 3+ real-data review demands it.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI not installed — PR flow runs via GitHub UI (user merges); CI status checked read-only via Actions API with the stored git credential. Consider installing `gh`.
- Direct push to main is denied by permission settings — every phase ends with a branch push + compare URL for the user to merge.
- 2026-07-03: accidental "revert PR" on GitHub was closed unmerged; leftover `revert-1-phase-0-scaffold` branch deleted from origin. Main history is clean.
- numpy 2.5 `DeprecationWarning` surfaces via `rasterio.windows` (harmless; will break on a future numpy — watch rasterio releases). rasterio also logs "boto3 not available, DummySession" INFO noise on HTTPS reads (cosmetic).
- Negative-test runs ingested two real monsoon scenes for vizhinjam (2021-06-17 usable 0.734, 2021-07-17 usable 0.925) alongside the demo pair — legitimate rows, kept.
- Phase 2: synthetic fixtures import as `from tests.synthetic import …` (tests/ is a package with `__init__.py`) — the plan's `from synthetic import …` snippets are wrong; use the package-qualified path.
- Phase 2: forest NDVI-decrease rule conflated deforestation with crop harvest (both drop NDVI). **Mitigated** (branch `phase-2-forest-precondition`) by ANDing a `ndvi_before ≥ 0.60` precondition — the before image must have been forest-level green. Cut real-pair detections 103 → 63. Residual: mature-crop→harvest where the crop itself was ≥0.60 NDVI can still slip through; a temporal-persistence check (deforestation is permanent, harvest recovers) is the Phase 3+ next lever if needed.
- Phase 2: NBR index function is implemented + tested but unused by any preset (needs a `swir22` band the CLI doesn't read) — kept for future presets per the roadmap.
