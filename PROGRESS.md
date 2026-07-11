# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
Phase 4 — Briefs + evidence chain: **implementation complete + reviewed; live gate pending user's Anthropic key** (2026-07-11). All 9 planned tasks built on branch `phase-4-briefs-evidence` following subagent-driven-development (fresh implementer → task review → fixes → final whole-branch review). Non-live gate GREEN (187 passed, ruff clean, alembic `0003 (head)`, `generate_brief` registered in worker). Whole-branch review (opus, `3e1097f`→`3835cd7`) returned **✅ Ready to merge** — the three-gate validator holds as a security boundary end-to-end. The only remaining work is the **live gate (Steps 2–5)**, which needs `OVERWATCH_ANTHROPIC_API_KEY` in `.env` — the user supplies it directly (never via chat / never committed). Full evidence in the plan's "Verification Gate — evidence" section.

Phase 3 merged to main via PR #7 (`3e1097f`, 2026-07-09); merge verified byte-identical to branch tip `5cf599d`, local main synced, stale branch deleted. CI on the merge commit not yet confirmed green — `gh` is installed (2.96.0) but needs `gh auth login` before it can query Actions.

## Last verified working
Phase 4 non-live gate (2026-07-11, in-container, all `docker compose exec -T api …`): **`pytest -q` → 187 passed** (2 pre-existing third-party deprecation warnings only — Starlette/httpx TestClient + Alembic path_separator; not Phase-4 code); `ruff check .` → All checks passed; `ruff format --check .` → 98 files already formatted; `alembic current` → `0003 (head)`; `celery -A overwatch.workers.celery_app inspect registered` lists `overwatch.generate_brief`. Whole-branch review returned **✅ Ready to merge** with the validator security boundary confirmed across `prompt → generator → loop → validator → persist`. Secret hygiene: `git grep -iIn "sk-ant-api"` empty, no `.env` tracked. **Live LLM path (real Anthropic API) not yet run — pending user's key.**

Prior — Phase 3 full pipeline (2026-07-09, in-container): `POST /aois/vizhinjam/jobs` → **HTTP 202** → Celery chain walks `ingest_before → ingest_after → detect` → **succeeded in 463 s with 12 detection polygons** in PostGIS. Queryable by spatial predicate (`ST_Intersects` bbox → 12 features, largest 18,200 m²; disjoint bbox → 0). Re-run of the identical windows selected the same scene pair and left **12 rows, zero duplicates** (pks 37…→49…, proving replace-set deleted+reinserted). Failure path: unreachable STAC → attempts climb 0→2→4 then structured `task_failed`; pre-Sentinel-2 window → fast-fail `no_usable_scene` at attempts=1. Beat: daily 03:00 crontab, due-selection baselines on the last after-scene and stamps `last_checked_at`. **117 tests + ruff check + ruff format green.**

Prior — Forest was-forest precondition (2026-07-07, in-container): forest preset now ANDs `ndvi_before ≥ 0.60` with the NDVI-decrease rule, so crop harvest no longer reads as deforestation. TDD: crop-harvest synthetic pair now yields 0 detections (was 1); genuine FOREST→BARE clearing still detected (regression guard). Real Novo Progresso pair dropped from **103 → 63** detections — removed polygons were cropland/pasture in fields already cleared by 2023; retained polygons sit on forest-edge transitions (eyeballed). 76 tests + ruff check + ruff format all green in-container.
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
- [x] Phase 3 design spec: `design-specs/2026-07-07-phase-3-persistence-api-jobs-design.md` (user-approved 2026-07-07: core-only schema, Celery chain + jobs table, date-window scene selection, sync DB layer).
- [x] Phase 3 plan: `plans/2026-07-07-phase-3-persistence-api-jobs.md` (12 tasks, all executed; Verification Gate evidence appended).
- [x] **Phase 3 — Detection persistence + API + jobs.** *Verified 2026-07-09, all in-container; full evidence in the plan's Verification Gate section:*
  1. Migration 0002 — `aois`/`jobs`/`detections` with GiST indexes on both geometry columns + `ix_detections_pair`; `ON DELETE CASCADE` from aois.
  2. `overwatch.geodesy` — geodesic area (cap math) + UTM→WGS84 reprojection for stored polygons.
  3. AOI repository (slug upsert never clobbers cadence/last_checked_at) + idempotent seeder (`python -m overwatch.db.seed` twice → same ids `[6,7,8]`).
  4. Structured error envelope on every non-2xx (`ApiError` + wrapped FastAPI validation errors).
  5. AOI CRUD; 500 km² geodesic cap from `Settings.max_aoi_km2` → 422 `aoi_too_large` with measured km² in `detail`.
  6. Job repository — staged lifecycle, atomic attempts counter, structured `error` payload, `latest_succeeded_job`.
  7. Detection **replace-set** persistence on the `(aoi, before_scene, after_scene)` natural key + `ST_Intersects`/`since`/`change_type` queries.
  8. `imagery/harmonize.py` — BOA offset lifted out of the Phase-2 CLI, shared with the worker.
  9. Celery chain `ingest_before → ingest_after → detect`; transient errors retry with backoff (`attempts` visible while polling), permanent errors fail fast with a structured code.
  10. `POST /aois/{slug}/jobs` → 202 + `job_id`; `GET /jobs/{id}` polling; `GET /aois/{slug}/detections` → GeoJSON FeatureCollection.
  11. Beat: daily 03:00 tick → `enqueue_due_rechecks`; pure `is_due`/`recheck_windows`; skips AOIs with no successful baseline run.
  12. **Live gate:** API submit → 12 detections on the real Vizhinjam 2021→2025 pair (463 s); spatial query returns them, disjoint bbox returns 0; re-run → same pair, 12 rows, **zero duplicates** (pks replaced); unreachable STAC → attempts 0→2→4 → `task_failed`; pre-Sentinel-2 window → `no_usable_scene` at attempts=1. **117 tests + ruff green.**

- [~] **Phase 4 — Intelligence briefs + evidence chain (code complete + reviewed; live gate pending key).** Branch `phase-4-briefs-evidence`, base `3e1097f` → head `3835cd7`. *Verified 2026-07-11, all in-container except the live LLM path; full evidence in the plan's Verification Gate section:*
  1. Migration 0003 — `briefs` / `brief_claims` / `evidence_links` with `ck_evidence_links_detection_id` CHECK, `uq_brief_claims_brief_seq` UNIQUE, indexes; cascade from `aois`. ORM models appended. `anthropic` dep + config (`anthropic_model="claude-opus-4-8"`, `brief_max_attempts=3`, `brief_max_prompt_detections=50`).
  2. Brief repository (`db/briefs.py`): create/get/latest-validated, `claims_with_evidence`, `persist_validated`, `mark_rejected/failed`, `mark_stale_briefs`, `detection_rows_for_pair`. **Staleness:** `replace_detections` calls `mark_stale_briefs` in the same transaction *before* the DELETE, so a re-run flips dependent validated briefs to `stale`.
  3. `overwatch.briefs` package — frozen Pydantic contracts (`ClaimDraft`/`BriefDraft`/`Violation`/`DetectionRow`/`BriefRequest`), the **three-gate validator** (Gate 1 linkage, Gate 2 context hygiene, Gate 3 numeric: area ±10% + exact dates, padding-insensitive), generator abstraction (`FakeBriefGenerator` + `AnthropicBriefGenerator` with transient/permanent error split), bounded regeneration loop (3 attempts, usage summed, per-attempt violations fed back), and the prompt builder (detections capped at 50 largest by area, stats over all).
  4. Celery `generate_brief` task (`BriefTask.on_failure → mark_brief_failed`; `autoretry_for=(TransientBriefError,)`, max_retries=3) — registered in the worker; retries proven to fire (`call_count == 4`, discrimination-tested).
  5. API — `POST /aois/{slug}/briefs` (guards: 404 unknown AOI → 422 `briefs_unconfigured` if no key → 409 `no_baseline_run` if no succeeded job → create + commit before dispatch), `GET /briefs/{id}` (claims for validated/stale), `GET /aois/{slug}/brief` (latest validated).
  6. **187 tests + ruff check + ruff format green in-container** (70 new Phase-4 tests, all FakeBriefGenerator/mock — CI needs no key). Whole-branch review: **✅ Ready to merge**, validator security boundary confirmed end-to-end.
  7. **PENDING (live gate, needs user's key):** real-API happy path → `validated` + SQL proof of link→pair resolution; rejected-path violations surfaced; staleness live (re-run job → `stale` → fresh brief `validated`). See plan Steps 2–5.

## In progress
- Phase 4 **live verification gate** — blocked on `OVERWATCH_ANTHROPIC_API_KEY` in `.env` (user supplies directly). Once set + `docker compose restart api worker beat`, run plan Steps 2–5 (live happy path / rejected / staleness).

## Next up
- User: add the Anthropic key to `.env`, restart api/worker/beat → drive the live gate (Steps 2–5).
- User: `gh auth login`, then confirm CI green on branch `phase-4-briefs-evidence` and merge commit `3e1097f` (`gh run list --limit 3`).
- Merge `phase-4-briefs-evidence` → main (compare URL in known-issues) once live gate + CI are green.
- Phase 5: validator hardening — complete the stashed Gate-3 unrecognized-unit patch TDD-first; percentages/bare-number cross-check; explicit-scene-id 4xx.

## Open decisions
- Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike (deliberate).
- Preset thresholds/morphology are **engineering defaults, not tuned numbers** (design-spec §6 verbatim): port ssim_dissim≥0.35 ∧ ndvi≤−0.10, forest ndvi≤−0.20, flood ndwi≥0.20; min-areas 1,500/5,000/10,000 m²; open→close kernel 3px. They held on synthetic + real Vizhinjam/Novo pairs without tuning; revisit empirically if Phase 3+ real-data review demands it.

## Known issues / deviations
- `python:3.12-slim` needs `libexpat1` via apt for rasterio's bundled GDAL — handled in `backend/Dockerfile`, plan updated to match.
- `gh` CLI installed 2026-07-10 (2.96.0, `C:\Program Files\GitHub CLI\gh.exe` — not yet on this session's PATH; invoke by full path or new terminal) but **unauthenticated**: user must run `gh auth login` before CI/PR queries work.
- Direct push to main is denied by permission settings — every phase ends with a branch push + compare URL for the user to merge.
- 2026-07-03: accidental "revert PR" on GitHub was closed unmerged; leftover `revert-1-phase-0-scaffold` branch deleted from origin. Main history is clean.
- numpy 2.5 `DeprecationWarning` surfaces via `rasterio.windows` (harmless; will break on a future numpy — watch rasterio releases). rasterio also logs "boto3 not available, DummySession" INFO noise on HTTPS reads (cosmetic).
- Negative-test runs ingested two real monsoon scenes for vizhinjam (2021-06-17 usable 0.734, 2021-07-17 usable 0.925) alongside the demo pair — legitimate rows, kept.
- Phase 2: synthetic fixtures import as `from tests.synthetic import …` (tests/ is a package with `__init__.py`) — the plan's `from synthetic import …` snippets are wrong; use the package-qualified path.
- Phase 2: forest NDVI-decrease rule conflated deforestation with crop harvest (both drop NDVI). **Mitigated** (branch `phase-2-forest-precondition`) by ANDing a `ndvi_before ≥ 0.60` precondition — the before image must have been forest-level green. Cut real-pair detections 103 → 63. Residual: mature-crop→harvest where the crop itself was ≥0.60 NDVI can still slip through; a temporal-persistence check (deforestation is permanent, harvest recovers) is the Phase 3+ next lever if needed.
- Phase 2: NBR index function is implemented + tested but unused by any preset (needs a `swir22` band the CLI doesn't read) — kept for future presets per the roadmap.
- Phase 3: `worker`/`beat` compose services previously had **no source bind-mount and no `OVERWATCH_DATABASE_URL`** — they ran the Phase-0 baked image and couldn't reach Postgres, so new Celery tasks never registered. Fixed in `docker-compose.yml`. **Workers still do not hot-reload: `docker compose restart worker beat` after touching `workers/`.**
- Phase 3: `api` now runs uvicorn with `--reload --reload-dir /app/src` (it previously ignored the mounted source, so new routers 404'd until a manual restart).
- Phase 3: Celery `retry()` is a **no-op when a task is called directly** (`called_directly` re-raises the original exception). Tests must use `task.apply(...)` to exercise autoretry. See `CONTEXT.md`.
- Phase 3: alembic `fileConfig` disabled already-instantiated app loggers when migrations ran in-process, breaking a caplog-based Phase-1 test once suite ordering changed. Fixed with `disable_existing_loggers=False`. See `CONTEXT.md`.
- Phase 3: pytest DB fixtures — the cleanup fixture must tear down **after** the session commits (`db_session` depends on `clean_t3`), else the cross-session `DELETE` deadlocks against held row locks. Cost a 30-minute hang. See `CONTEXT.md`.
- Phase 3: the same Sentinel-2 acquisition can appear as **multiple STAC items** (reprocessings, e.g. `…_0_L2A` vs `…_2_L2A`). The cloud-ascending gate picks the lowest-cloud item, which is not necessarily catalog order — the Phase-2 CLI's pick differs, giving 9 polygons where the job gives 12 on the same dates. Deterministic, not a bug; both items carry `dn_offset=0` so harmonization is not implicated.
- Phase 3: `earth-search.aws.element84.com` DNS resolution intermittently fails inside the worker container (WSL2 DNS). It surfaces as `TransientIngestError` and the retry recovers it — observed once during the live gate run.
- Phase 4: **Gate 3 fails *open* on unrecognized area units** — an `observed` claim quoting an area in a unit `_AREA_RE` can't convert (acres, "sq km", "square miles") is not cross-checked and validates. Hole in the phase's headline guarantee; low real-risk (prompt mandates m²; a false-negative needs the model to disobey). Deferred to Phase 5. A complete **impl-only** patch (bounded unrecognized-unit regex, reuses `area_mismatch`, fail-closed — **no tests, unverified**) is parked in `git stash` (`stash@{0}`, message contains "Gate3 unrecognized-area-unit"); complete it TDD-first, do not commit as-is.
- Phase 4: explicit `(before, after)` scene ids in the `POST /briefs` body that don't exist hit the scenes FK at `create_brief` flush → unhandled `IntegrityError` → 500 instead of a clean 4xx. Default path (`latest_succeeded_job`) always supplies valid ids, so this only affects the advanced explicit-pair input. Phase-5 fix needs an ownership-semantics decision (404 vs 422, validate AOI membership).
- Phase 4: minor deferred — percentages/bare numbers in `observed` claims are uncross-checked (Gate 3 scoped to areas+dates by design); no blank-`headline` structural check; the permanent-failure persistence path drops `usage`/`attempts`.
- Phase 4: **live gate not yet run** — the real Anthropic API path (happy/rejected/staleness) awaits the user's key in `.env`. All 187 tests use `FakeBriefGenerator`/mocks, so CI stays key-free and green.
