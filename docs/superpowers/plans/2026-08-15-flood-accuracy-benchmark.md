# EMSN194 Flood Accuracy Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a reproducible, date-matched, single-case Porto Alegre flood accuracy baseline for the shipped detector without changing production detections or the flood preset.

**Architecture:** Keep benchmark code under `overwatch.eval`, separate from `overwatch.detection`. The EMSN194 adapter validates the official product and rasterises it onto the detector grid; the runner pins the AOI, dates, STAC IDs, archive hash, and shipped preset, then scores emitted polygons only on pixels valid in both scenes. Tracked JSON records the result while rasters, downloaded archives, and other review artifacts remain local.

**Tech Stack:** Python 3.12, pytest, Ruff, NumPy, rasterio, Shapely, pyproj, Pydantic metrics, Earth Search STAC/COG reads, Docker Compose.

**Spec:** `design-specs/2026-08-15-flood-accuracy-benchmark-design.md`

## Global Constraints

- Evaluate only `S2A_22JDM_20240418_0_L2A` -> `S2A_22JDM_20240508_0_L2A` over `[-51.300, -30.080, -51.180, -29.980]`.
- Use Copernicus EMSN194 AOI01 P04 FLDEL02 with archive SHA-256 `7d61dc66b3440db52ae89a33b415ac2273078278792636a11a37873573db8877`.
- Run the shipped `VERTICAL_PRESETS["flood"]` unchanged; do not add SWIR, MNDWI/AWEI, thresholds, or detector behavior.
- Score rasterised emitted polygons, not the internal threshold mask, and exclude pixels invalid in either SCL plane.
- Do not write to PostGIS, replace live detections, regenerate briefs, or call Anthropic.
- Do not commit secrets, downloaded archives, rasters, PNGs, TIFFs, or generated review artifacts.
- Keep the primary checkout on `main`; all implementation work stays in `.worktrees/phase-flood-accuracy-benchmark`.

---

### Task 1: Validate the Migrated Benchmark Boundary

**Files:**
- Inspect: `backend/src/overwatch/eval/emsn194.py`
- Inspect: `backend/src/overwatch/eval/run_emsn194.py`
- Inspect: `backend/tests/test_eval_emsn194.py`
- Inspect: `benchmarks/results/emsn194-porto-alegre-2024-05-08.json`
- Test: `backend/tests/test_eval_emsn194.py`

**Interfaces:**
- Consumes: existing `overwatch.eval.metrics.score_masks`, `overwatch.eval.rasterize.mask_from_geometries`, and the detector/imagery models.
- Produces: a clean-branch benchmark adapter, runner, focused tests, and candidate evidence record with no duplicate production changes.

- [ ] **Step 1: Confirm the migrated files are the only implementation delta.**

Run:

```bash
git status --short --untracked-files=all
git diff --name-only main...HEAD
```

Expected: benchmark files plus the approved design/plan and documentation changes; no changes to `imagery/gating.py`, `test_gating.py`, or `docker-compose.yml` beyond `main`.

- [ ] **Step 2: Run the focused tests before changing code.**

Run:

```bash
docker compose run --rm --no-deps api pytest -q tests/test_eval_emsn194.py
```

Expected: all EMSN194 tests pass. If the archive is absent, this focused suite still runs because it uses synthetic GeoJSON fixtures and hash fixtures.

- [ ] **Step 3: Review the runner against the spec.**

Confirm these exact properties in the source before editing: `max_cloud_pct=100.0`, pinned STAC IDs, `MIN_USABLE=0.7`, `flood_truth_mask`, `ClassicalChangeDetector`, `mask_from_geometries`, `score_masks`, and the two sensitivity variants. Any mismatch becomes a focused code/test change before proceeding.

- [ ] **Step 4: Commit the implementation boundary.**

```bash
git add backend/src/overwatch/eval/emsn194.py backend/src/overwatch/eval/run_emsn194.py backend/tests/test_eval_emsn194.py benchmarks/results/emsn194-porto-alegre-2024-05-08.json
git commit -m "feat(eval): add EMSN194 flood benchmark"
```

---

### Task 2: Make the Official Truth Input Reproducible

**Files:**
- Modify: `backend/src/overwatch/eval/run_emsn194.py:40-52,174-187`
- Modify: `backend/tests/test_eval_emsn194.py:148-164`
- Local-only input: `data/benchmarks/emsn194/EMSN194_GeospatialData.zip`

**Interfaces:**
- Consumes: the official EMSN194 archive from the recorded source URL.
- Produces: a local archive validated by the pinned SHA-256 before any truth decoding.

- [ ] **Step 1: Check for the local archive without touching the database.**

```bash
Test-Path data/benchmarks/emsn194/EMSN194_GeospatialData.zip
```

Expected: `True`. If absent, download the archive from the source URL recorded in the evidence JSON into that ignored path, then continue; never commit it.

- [ ] **Step 2: Verify the archive hash independently.**

```bash
Get-FileHash data/benchmarks/emsn194/EMSN194_GeospatialData.zip -Algorithm SHA256
```

Expected: `7D61DC66B3440DB52AE89A33B415AC2273078278792636A11A37873573DB8877`.

- [ ] **Step 3: Run the archive and truth-decoder tests.**

```bash
docker compose run --rm --no-deps api pytest -q tests/test_eval_emsn194.py -k "archive or truth or geometry or raster"
```

Expected: all selected tests pass, including wrong-hash, wrong-date, wrong-CRS, wrong-method, invalid geometry, and official-area rejection cases.

- [ ] **Step 4: Commit only source/test changes if the contract needs correction.**

```bash
git add backend/src/overwatch/eval/run_emsn194.py backend/tests/test_eval_emsn194.py
git commit -m "test(eval): enforce EMSN194 input identity"
```

---

### Task 3: Reproduce and Review the Single-Case Score

**Files:**
- Run: `backend/src/overwatch/eval/run_emsn194.py`
- Compare: `benchmarks/results/emsn194-porto-alegre-2024-05-08.json`
- Local-only output: `data/benchmarks/emsn194/results/`

**Interfaces:**
- Consumes: pinned official archive and Earth Search COG windows.
- Produces: before/after PNGs, comparison PNG, truth/predicted/valid masks, predictions GeoJSON, and a fresh summary JSON.

- [ ] **Step 1: Start only the services required for the benchmark.**

```bash
docker compose up -d postgis redis api
```

Do not start worker or beat. The runner is read-only and does not require Celery or PostGIS.

- [ ] **Step 2: Execute the pinned runner.**

```bash
docker compose run --rm --no-deps api python -m overwatch.eval.run_emsn194
```

Expected output includes the fixed pair, `detections=104`, and candidate metrics near precision `0.586`, recall `0.605`, F1 `0.595`, and IoU `0.424`. Exact values must come from the fresh run, not from this plan.

- [ ] **Step 3: Inspect the generated artifacts.**

Open `data/benchmarks/emsn194/results/before.png`, `after.png`, and `comparison.png`. Confirm the images share the detector grid, invalid pixels are dimmed, and green/cyan/red overlays represent intersection, truth-only, and prediction-only areas respectively.

- [ ] **Step 4: Compare fresh summary to tracked evidence.**

Compare `summary.json` with `benchmarks/results/emsn194-porto-alegre-2024-05-08.json` field by field. Update the tracked record only for values proven by the fresh run, and retain the single-case status plus caveats about same-day optical/radar inputs.

- [ ] **Step 5: Stop local services after review.**

```bash
docker compose down
```

Do not use `docker compose down -v`.

- [ ] **Step 6: Commit the verified evidence record.**

```bash
git add benchmarks/results/emsn194-porto-alegre-2024-05-08.json
git commit -m "docs(eval): record EMSN194 flood baseline"
```

---

### Task 4: Update Living Project Documentation

**Files:**
- Modify: `PROGRESS.md:169-214`
- Modify: `CONTEXT.md` under the flood benchmark section

**Interfaces:**
- Consumes: fresh runner summary, artifact review, and verification command output.
- Produces: accurate project state that distinguishes candidate evidence from a verified baseline and prevents generalising the flood result.

- [ ] **Step 1: Replace stale branch-state wording.**

Keep `main` as the primary checkout, identify `.worktrees/phase-flood-accuracy-benchmark` as the active branch, and state that the old `phase-accuracy-benchmarks` worktree/branch was removed after migration.

- [ ] **Step 2: Record the benchmark result with scope.**

Record the exact fresh metrics, pinned dates, truth product, detection count, and verification commands. Use “single date-matched Porto Alegre flood case”; do not call it a general flood accuracy score.

- [ ] **Step 3: Record the truth-product and catalog-cloud constraints.**

Preserve the EMSR720 mismatch, EMSN194 spatial/date match, observed-event semantics, geometry-repair guard, and 72.34% full-tile cloud versus 88.44% AOI SCL usability explanation.

- [ ] **Step 4: Commit documentation separately.**

```bash
git add PROGRESS.md CONTEXT.md
git commit -m "docs: record flood benchmark verification"
```

---

### Task 5: Run the Complete Verification Gate

**Files:**
- Verify: complete branch diff and working tree

**Interfaces:**
- Consumes: all implementation, evidence, and documentation commits.
- Produces: a review-ready branch with fresh test, lint, format, benchmark, and diff evidence.

- [ ] **Step 1: Run the complete backend suite.**

```bash
docker compose run --rm --no-deps api pytest -q
```

Expected: zero failures; the existing tracked flood xfail may remain until SWIR work makes it pass.

- [ ] **Step 2: Run Ruff checks.**

```bash
docker compose run --rm --no-deps api ruff check src tests
docker compose run --rm --no-deps api ruff format --check src tests
```

Expected: both commands exit successfully with no formatting changes required.

- [ ] **Step 3: Check the complete diff.**

```bash
git diff --check main...HEAD
git status --short --branch
```

Expected: no whitespace errors and no unexpected untracked files or secret material.

- [ ] **Step 4: Perform final review.**

Review the complete branch diff against the design spec. Confirm no production DB mutation, Anthropic call, SWIR asset, detector tuning, frontend change, or unsupported general accuracy claim entered the branch.

- [ ] **Step 5: Commit any final verified progress record.**

```bash
git add PROGRESS.md
git commit -m "docs(progress): close flood benchmark gate"
```

---

## Completion Checklist

- [ ] EMSN194 adapter and runner are committed on `phase-flood-accuracy-benchmark`.
- [ ] Official archive hash and truth semantics are validated.
- [ ] Fresh benchmark output reproduces and artifacts are visually reviewed.
- [ ] Tracked evidence matches fresh output and keeps the single-case scope.
- [ ] Full backend tests, Ruff, format, and `git diff --check` pass.
- [ ] Final branch review is clean.
- [ ] Forest baseline is opened as a separate next-cycle design; no forest or SWIR work is included here.
