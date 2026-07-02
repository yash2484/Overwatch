# Overwatch MVP — Roadmap & Session Handover

> **Written:** 2026-07-03, after Phase 0 merged to main (PR #1, CI green).
> **Audience:** a fresh Claude Code session picking up the project. Read `PROJECT.md` (scope/strategy), `design-specs/2026-07-02-overwatch-mvp-design.md` (approved design), and `PROGRESS.md` (current state) before this file.

---

## How to run a phase session

1. Start from a synced `main` (`git checkout main && git pull`). Start Docker Desktop first — it does not auto-start on this machine.
2. Invoke `superpowers:writing-plans` to produce the phase's detailed bite-sized plan → save to `plans/YYYY-MM-DD-phase-N-<slug>.md`. Detailed plans are written **one phase at a time** — each depends on the previous phase's verified reality. This roadmap is deliberately goal-level for later phases.
3. Work on a branch `phase-N-<slug>`. Execute with `superpowers:executing-plans` (or subagent-driven), TDD where the plan says so, commit per task.
4. All Python runs **in-container** (`docker compose exec api pytest -v`, etc.). Never install project deps on the Windows host.
5. Gate with `superpowers:verification-before-completion`, update `PROGRESS.md` with evidence, push the branch.
6. **The user merges to main via GitHub PR** — direct push to main is denied by permission settings, and `gh` CLI is not installed; give the user the compare URL: `https://github.com/yash2484/Overwatch/compare/main...<branch>`.
7. CI must be green before asking for merge (workflow: backend ruff+pytest, frontend tsc+build). If CI needs to run pre-merge, note the PR trigger already covers pull requests.

**Environment quirks (verified 2026-07-02):** no `gh`, no `rtk`, PowerShell tool unavailable (use Git Bash); `$TMPDIR` unset — use the session scratchpad for log redirection; Actions API reachable with `git credential fill` token (read-only, never print it).

---

## State after Phase 0 (done, merged, verified)

- Compose stack: `postgis` (PostGIS 3.4), `redis`, `api` (FastAPI `/health`), `worker`+`beat` (Celery, `overwatch.ping` task), `frontend` (Vite/React/TS stub on :5173).
- Backend: `backend/pyproject.toml` (single dep source), typed `Settings` (`OVERWATCH_*` env prefix, `fusion_enabled` flag already present), src layout `backend/src/overwatch/`.
- Tests: 2 (health, celery ping), written TDD, run in-container. CI green on main.
- Known gotcha already handled: `python:3.12-slim` needs `libexpat1` for rasterio's GDAL (in Dockerfile).

---

## Phase 1 — Imagery ingestion (NEXT)

**Goal:** given a hardcoded AOI + date range, find Sentinel-2 L2A scenes, read only the AOI's pixel window from COGs, cloud-mask via SCL, persist scene metadata to PostGIS. Prove the three showcase AOIs are viable.

**Deliverables:**
- `ImageryProvider` interface (design spec §4) with the Earth Search implementation behind it: search scenes for (geometry, date range, max cloud %); read windowed, band-selected arrays for a scene.
- SCL-based cloud masking + usable-pixel-fraction computation (gate: ≥ 70%, else skip scene and widen window in +15-day steps, cap +60 days — design spec §6).
- Minimal `scenes` persistence in PostGIS (SQLAlchemy + GeoAlchemy2 + psycopg + alembic enter the deps here; STAC scene id is the natural key — upserts must be idempotent).
- PNG rendering of AOI windows for eyeball verification.

**Technical starting points (verify against reality in the plan's spike step — do not hardcode blindly):**
- Earth Search STAC: `https://earth-search.aws.element84.com/v1`, collection `sentinel-2-l2a`, no auth for search. `pystac-client` is the standard client; bands as COG assets (`red`, `green`, `blue`, `nir`, `scl`, ...). Windowed reads: `rasterio.open(asset_href)` + `rasterio.windows.from_bounds(aoi_bounds_in_scene_crs, transform)` — reproject AOI to the scene's UTM CRS first (pyproj/shapely), never difference in EPSG:4326.
- SCL is 20 m — upsample nearest-neighbor to 10 m before masking. Mask classes {0,1,3,8,9,10,11} (no-data/saturated/shadow/cloud med+high/cirrus/snow); treat {2,4,5,6,7} as usable. Tune empirically; log per-scene usable fraction.
- AOI seed coordinates (approximate centers — **unverified**, refine while eyeballing): Vizhinjam port ≈ 8.375 N, 76.985 E; Novo Progresso frontier ≈ 7.1 S, 55.4 W; Porto Alegre/Guaíba ≈ 30.03 S, 51.23 W.

**Verification gate:** two clear Vizhinjam scenes spanning known construction (clear-season Dec–Apr windows) rendered as PNGs and eyeballed; usable-pixel gate demonstrably skips a cloudy scene (negative test); scene rows idempotent on re-run; viability confirmed (or fallback swapped per design spec §5) for all three AOIs. CI green.

**Housekeeping folded in:** none pending — the temporary `phase-0-scaffold` CI trigger was removed in the same PR as this roadmap.

---

## Phase 2 — Change Detection Engine (TDD)

**Goal:** the pure, deterministic core — the project's centerpiece TDD target.
**Deliverables:** `ChangeDetector` interface + classical implementation: NDVI/NDWI/NBR deltas, image differencing, SSIM, threshold → morphological open→close → polygonization into typed `Detection` objects (geometry, change type, magnitude, confidence, contributing indices). No I/O, no LLM. Per-vertical preset configs (min areas: port 1,500 m² / forest 5,000 m² / flood 10,000 m² — design spec §6).
**Method:** synthetic-raster fixtures first (inject a known "new building"/"clearing"/"flood" into a synthetic pair; assert the polygon), then run on the real Phase-1 Vizhinjam pair.
**Gate:** synthetic suite green; known real-world change detected; thresholds recorded in preset configs, not hardcoded.

## Phase 3 — Detection persistence + API + jobs end-to-end

**Goal:** full pipeline: API call → Celery ingestion → detection → queryable PostGIS events.
**Deliverables:** full schema (aois, scenes, detections, briefs, brief_claims, evidence_links, news_articles — design spec §4) with GiST indexes; AOI CRUD + job submit/status endpoints (REST polling, 2 s); Celery task chain with retries/backoff; idempotency on natural keys; AOI size cap 500 km² rejected with structured error; beat schedule wired (weekly re-check).
**Gate:** submit AOI via API → detections queryable by spatial predicate; re-run produces zero duplicate rows; job failure path retries visibly.

## Phase 4 — Briefs + evidence chain

**Goal:** the trust architecture — LLM narrates over stored detections only.
**Deliverables:** `BriefGenerator` (Anthropic API, structured detections in, claims out with evidence-link IDs); validator rejecting any claim without ≥1 evidence link, bounded regeneration (3 attempts) with structured feedback, `rejected` status surfaced; evidence-link table wiring (claim → detection).
**Gate:** brief generated for Vizhinjam with every claim's links resolving; **negative test:** a deliberately unlinked claim is demonstrably rejected. Anthropic key enters `.env` here (user provides — never committed).

## Phase 5 — OSINT fusion (GDELT)

**Goal:** persisted, deterministic news correlation (design spec §3 — the constrained fusion decision).
**Order matters:** (1) **API spike first** — verify GDELT DOC 2.0 vs GEO 2.0 surface and theme taxonomy against real queries for the three AOIs; no integration code before the spike. (2) TDD the three-gate AND scorer (spatial ≤ 25 km buffer / temporal −30 d..+14 d / thematic per-vertical allowlist) as a pure function. (3) `NewsProvider` interface + Celery fusion task persisting passing articles. (4) Validator extension: article-only claims must use reported-speech framing.
**Gate:** real correlated articles cited for ≥1 AOI; a deliberately irrelevant article rejected by the gates (negative test); `FUSION_ENABLED` kill-switch tested both ways.

## Phase 6 — Frontend arena

**Goal:** the demo face — MapLibre GL + deck.gl.
**Deliverables:** AOI draw tool, scene timeline, before/after slider, detection polygon overlays, brief panel with **click-to-evidence** (sentence click highlights detections on map; article citations open sources). Use the `frontend-design` skill — this is the flagship's face.
**Gate:** the <2-minute demo works end-to-end for all three showcase AOIs.

## Phase 7 — Polish

**Goal:** ship it. README with demo GIF, three showcases pre-loaded (seed script), one-command spin-up verified from a clean clone on this machine, resume bullet checked word-by-word against measured reality (no unverified numbers — PROJECT.md §11 discipline).
**Gate:** fresh-clone `docker compose up` → working demo; every README/resume claim traceable to a run.

---

## Standing scope discipline

MVP = Phases 0–7 above, nothing else. Extensions (DL benchmark, alerting, SAR, NL tasking, dashboard, time-series) wait — PROJECT.md §8. The flagship fails only one way: staying unfinished.
