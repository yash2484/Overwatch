# Phase 3 Design — Detection Persistence + API + Jobs

> **Status:** Approved by Yash in-session 2026-07-07 (brainstorm via `superpowers:brainstorming`).
> **Scope authority:** `plans/2026-07-03-mvp-roadmap.md` "Phase 3" heading; data model authority is design-spec §4 (`design-specs/2026-07-02-overwatch-mvp-design.md`), narrowed by decision 1 below.
> **Goal:** full pipeline — API call → Celery ingestion → change detection → queryable PostGIS events.

---

## 1. Decisions resolved (2026-07-07 brainstorm)

1. **Schema scope: core only.** Phase 3 creates `aois`, `jobs`, `detections` (`scenes` already exists). `briefs`/`brief_claims`/`evidence_links` land in Phase 4 and `news_articles` in Phase 5, each shaped by its phase's actual needs (the GDELT spike is deliberately deferred; its outcome shapes `news_articles` columns). This narrows the roadmap's "full schema" line — the roadmap gets a one-line correction.
2. **Job model: Celery chain + `jobs` table.** Granular tasks (`ingest_scene` before → `ingest_scene` after → `run_detection`), each with its own retry/backoff. Job state lives in Postgres, not the Redis result backend: durable, queryable, and the natural home for structured errors and stage progress. Polling reads the DB.
3. **Scene-pair selection: date windows + gate.** Job submission takes two date *ranges*; the worker runs the existing `find_usable_scene` (≥70% usable-pixel gate, +15 d/+60 d auto-widening) in each. Chosen `stac_id`s are recorded on the job for reproducibility. The weekly beat re-check composes on top (before = last successful run's after scene; after window = last capture → today).
4. **DB layer: keep sync SQLAlchemy** for both API and workers. API endpoints are `def` (FastAPI threadpool). Explicit, reversible deviation from the async-first standard: one engine/session layer shared with Celery (which is sync by nature), trivial load at MVP scale. Revisit if the API grows real concurrency needs.

---

## 2. Data model (alembic migrations, additive; `scenes` untouched)

All geometries EPSG:4326 with GiST indexes. Pydantic v2 models mirror each table at the API boundary.

### `aois`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `slug` | TEXT, unique | Natural key; matches existing `scenes.aoi_slug` values |
| `name` | TEXT | |
| `vertical` | TEXT | `port \| forest \| flood` — selects the `DetectionPreset` |
| `geom` | Geometry(POLYGON, 4326) | GiST index |
| `cadence_days` | INT, nullable | null = no re-check; 7 = weekly |
| `last_checked_at` | TIMESTAMPTZ, nullable | Set when a re-check job is enqueued |
| `created_at` / `updated_at` | TIMESTAMPTZ | Same convention as `scenes` |

- **500 km² cap** enforced at the API boundary (geodesic area; structured 422 on breach). Never a DB constraint — the number is a tunable default (spec §6).
- **Seeding:** idempotent seed CLI (`python -m overwatch.db.seed`), upsert on `slug`, seeds the three showcase AOIs from `overwatch.aois.SHOWCASE_AOIS`. A CLI, not a data migration, so it stays re-runnable and testable. `overwatch/aois.py` remains the source of the seed constants.

### `jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Returned by submit; polled by the client |
| `aoi_id` | FK → aois | |
| `status` | TEXT | `queued \| running \| succeeded \| failed` |
| `stage` | TEXT, nullable | `ingest_before \| ingest_after \| detect` |
| `params` | JSONB | The submitted before/after windows, verbatim |
| `before_scene_id` / `after_scene_id` | FK → scenes, nullable | Filled as ingest stages complete |
| `detection_count` | INT, nullable | Filled on success |
| `error` | JSONB, nullable | Structured: `{code, message, detail}` |
| `attempts` | INT, default 0 | Incremented per task retry — makes retries visible while polling |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

### `detections`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `aoi_id` | FK → aois | |
| `job_id` | FK → jobs | Provenance: which run produced this row |
| `before_scene_id` / `after_scene_id` | FK → scenes | The evidence pair — Phase 4's evidence chain hangs off these |
| `geom` | Geometry(POLYGON, 4326) | GiST index; reprojected from the engine's UTM output |
| `src_epsg` | INT | The engine's projected CRS (area/geometry math happened there) |
| `area_m2` | FLOAT | Computed by the engine in projected CRS — not recomputed |
| `change_type` | TEXT | `construction \| vegetation_loss \| flooding` (engine `ChangeType`) |
| `magnitude` / `confidence` | FLOAT | Engine outputs, stored verbatim |
| `contributing_indices` | JSONB | Engine map name → mean value |
| `created_at` | TIMESTAMPTZ | |

**Idempotency — replace-set semantics.** Detections have no per-row natural key (geometry hashing is brittle). The engine is deterministic, so the natural key is the *pair*: in one transaction, delete and reinsert all detections for `(aoi_id, before_scene_id, after_scene_id)`. Re-running a job over the same windows selects the same scenes (deterministic gate) and rewrites identical rows — zero duplicates, satisfying the gate. Scene idempotency already exists (upsert on `(stac_id, aoi_slug)`).

**`DELETE /aois/{slug}`** cascades `jobs` and `detections`; `scenes` rows are kept (ingestion cost is real; `aoi_slug` is informational there).

---

## 3. API surface (FastAPI, pydantic v2 at every boundary)

Structured error envelope everywhere: `{"error": {"code": str, "message": str, "detail": object | null}}`.

| Endpoint | Behavior |
|---|---|
| `POST /aois` | Create; validates vertical, polygon validity, geodesic area ≤ 500 km² (422 `aoi_too_large` with measured km² in detail) |
| `GET /aois` / `GET /aois/{slug}` | List / fetch (GeoJSON geometry in response) |
| `DELETE /aois/{slug}` | Cascade jobs + detections, keep scenes |
| `POST /aois/{slug}/jobs` | Body `{before: {start, end}, after: {start, end}}` → **202** `{job_id}`; writes `queued` job row, dispatches the chain |
| `GET /jobs/{job_id}` | Status/stage/attempts/scene ids/detection_count/error — the ~2 s polling target |
| `GET /aois/{slug}/detections` | Filters: `intersects` (WKT or bbox → ST_Intersects), `since` (date), `change_type`. Returns GeoJSON features with properties |

No auth (single-user MVP, unchanged from prior phases). No WebSocket, no alerting (spec §6).

---

## 4. Celery chain + beat

**Chain:** `POST .../jobs` → job row (`queued`) → `chain(ingest_scene(job, "before"), ingest_scene(job, "after"), run_detection(job))`.

- `ingest_scene`: `find_usable_scene` over the submitted window (existing gate + auto-widen) → existing `upsert_scene` → record scene FK + set `stage`. The BOA `dn_offset` handling currently inlined in the Phase 2 CLI (`detection/cli.py:_load_window`) is lifted into a shared module (`imagery/harmonize.py`) used by both CLI and worker.
- `run_detection`: windowed re-read of the two chosen scenes → `ClassicalChangeDetector` with the AOI's vertical preset → reproject polygons to 4326 → replace-set persist → `succeeded` + `detection_count`.
- **Retries:** `autoretry_for` transient errors (network/STAC/DB-connection) with exponential backoff + jitter, `max_retries=3`; each retry increments `jobs.attempts`. Non-transient failures (no usable scene after widening, coverage error, CRS mismatch) fail fast: `status=failed` + structured `error` — no pointless retries.
- Each task updates `jobs.stage`/`status`; a chain-level failure handler guarantees no job is stuck `running` after terminal failure.

**Beat:** one schedule entry — daily `enqueue_due_rechecks`. Pure, unit-tested due-selection: AOIs where `cadence_days` is set and `last_checked_at + cadence_days ≤ now`. For each due AOI with a prior successful job: submit a job with before = that job's after scene (by exact date), after window = `[last capture + 1 d, today]`; stamp `last_checked_at`. No prior successful run → log and skip (nothing to compare against). Weekly cadence = `cadence_days=7` on the AOI; the beat *tick* is daily so cadences aren't quantized to the tick.

---

## 5. Testing strategy (TDD, red→green per task)

- **Unit (no DB):** geodesic-area cap math; request-model validation; job state transitions; due-recheck selection; window→scene-pair orchestration against a fake `ImageryProvider` serving synthetic `AOIWindow`s (reuse `tests/synthetic.py`); UTM→4326 reprojection of detection polygons.
- **Integration (CI postgis service exists since Phase 1):** migrations up; AOI CRUD round-trip; replace-set idempotency (insert twice → same rows); `ST_Intersects` query endpoint returns/excludes correctly; seed CLI idempotency.
- **Chain test:** end-to-end over fakes (fake provider + eager Celery or direct task-function calls) — submit → job walks stages → detections persisted; failure path → retries counted → structured error.

## 6. Verification gate (live, in-container, evidence appended to the plan)

1. Submit Vizhinjam with before ≈ 2021-02 window, after ≈ 2025-02 window via `POST /aois/vizhinjam/jobs` → poll `GET /jobs/{id}` to `succeeded`.
2. `GET /aois/vizhinjam/detections?intersects=<port bbox>` returns the known construction polygons (~9 from Phase 2).
3. Resubmit the same windows → same scene pair selected → detection row count and content unchanged (zero duplicates).
4. Failure path: forced provider error (e.g., unreachable STAC URL) → polling shows `attempts` climbing, then `failed` with structured error. A no-usable-scene window fails fast with `no_usable_scene`.
5. `pytest` + `ruff check` + `ruff format --check` green in-container; CI green on the PR.

## 7. Out of scope (Phase 3)

Briefs/claims/evidence tables (Phase 4); `news_articles` + GDELT (Phase 5); auth; WebSocket; alerting; detection preset tuning (only if real-data review demands it); temporal-persistence forest check (noted Phase 3+ lever in PROGRESS — deferred until evidence demands it).
