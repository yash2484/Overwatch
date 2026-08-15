# Post-MVP Design — EMSN194 Flood Accuracy Baseline

> **Status:** Approved by Yash in-session 2026-08-15 (brainstorm via
> `superpowers:brainstorming`).
> **Scope authority:** `PROGRESS.md` "Current queue (2026-08-15)" and
> `HANDOVER-post-merge-accuracy.md` priority 1.
> **Goal:** publish a reproducible, date-matched, single-case flood accuracy baseline for the
> shipped detector before changing the flood preset or adding SWIR.

---

## 1. The one-paragraph version

Finish the existing Copernicus EMSN194 evaluation as its own reviewed PR. The benchmark fixes the
Porto Alegre AOI and Sentinel-2 pair to 2024-04-18 -> 2024-05-08, validates the official P04
FLDEL02 flood product and archive hash, runs the shipped flood preset unchanged, rasterises the
detector's emitted polygons onto the truth grid, and reports pixel-level precision, recall, F1,
and IoU only where both scenes are valid. The PR contains the loader, runner, tests, compact
evidence record, and current project documentation. It does not alter production detections, the
live database, the frontend, or the detector.

---

## 2. Why this phase exists

Only the construction preset currently has independent accuracy numbers. Flood changes were twice
accepted from plausible spectral reasoning and later shown to be wrong by visual review. The next
detection change therefore needs a measured baseline first, so any later SWIR/MNDWI work produces
an empirical delta rather than an argument.

The originally proposed EMSR720 activation cannot score the Porto Alegre demo: its product
footprints do not intersect the demo AOI and its observation dates do not match the live
2024-05-21 scene. EMSN194 AOI01 does intersect the exact demo bbox and supplies an observed-event
flood layer for 2024-05-08. Earth Search supplies a date-matched Sentinel-2 scene on the same grid,
so the valid comparison changes the evaluated after-scene rather than comparing observations from
different dates.

---

## 3. Scope and claim boundary

### In scope

- `overwatch.eval.emsn194`: strict decoding, semantic validation, geometry repair, area validation,
  reprojection, and rasterisation of the official P04 FLDEL02 layer.
- `overwatch.eval.run_emsn194`: deterministic scene selection, detector execution, scoring,
  sensitivity checks, review artifacts, and machine-readable summary output.
- Focused unit tests for truth semantics, archive integrity, geometry repair, rasterisation, and
  valid-pixel scoring.
- A compact tracked evidence record containing source identity, input pair, preset, result,
  caveats, and verification commands. Generated rasters and imagery remain ignored.
- `PROGRESS.md` and `CONTEXT.md` updates that record what was measured and the constraints future
  benchmark work must preserve.

### Out of scope

- Forest accuracy, PRODES/Hansen integration, or any multi-window benchmark.
- SWIR ingestion, MNDWI/AWEI, preset tuning, threshold sweeps, or detector changes.
- Replacing the live demo pair, writing detections to PostGIS, regenerating briefs, or making an
  Anthropic call.
- Frontend changes, deployment, GDELT work, or bundle optimisation.

### Allowed claim

The result may be described only as a **single date-matched Porto Alegre flood case** evaluated
against Copernicus EMSN194 P04 FLDEL02. It is not a general flood-accuracy number and must not be
combined with the OSCD construction result as if both measured the same detector population.

---

## 4. Integration strategy

The unfinished `phase-accuracy-benchmarks` worktree starts at PR #9 (`3bad15c`) and contains both
unique EMSN194 work and later fixes that now exist on `main`. Rebasing that dirty worktree would
mix document conflicts with already-landed production changes.

Use a clean branch from current `main` instead:

1. Treat `C:\dev\Overwatch-benchmarks` as the preserved source and audit record.
2. Verify the unique benchmark files in that worktree before checkpointing them.
3. Transplant only the EMSN194 adapter, runner, tests, and tracked evidence record onto
   `phase-flood-accuracy-benchmark`.
4. Manually merge only benchmark-specific `PROGRESS.md` and `CONTEXT.md` material into the current
   versions on `main`.
5. Do not transplant `imagery/gating.py`, `test_gating.py`, or `docker-compose.yml`: their worktree
   bytes are identical to the fixes already on `main`.

This preserves the unfinished worktree until the new branch passes review and avoids reverting or
duplicating verified active-pair, cloud-gate, Compose, README, and workflow changes.

---

## 5. Inputs and data flow

### 5.1 Immutable benchmark identity

- AOI bbox, CRS84: `[-51.300, -30.080, -51.180, -29.980]`.
- Before: `S2A_22JDM_20240418_0_L2A`.
- After: `S2A_22JDM_20240508_0_L2A`.
- Truth: Copernicus EMSN194 AOI01, P04 FLDEL02, source date 2024-05-08.
- Official archive SHA-256:
  `7d61dc66b3440db52ae89a33b415ac2273078278792636a11a37873573db8877`.
- Detector: the shipped `flood` preset, unchanged.

The runner searches Earth Search with a 100% catalog-cloud ceiling but accepts only the two pinned
STAC IDs. AOI-level SCL usability remains the actual quality gate. This is deliberate: full-tile
cloud metadata reports 72.34% cloud for the 8 May scene while the benchmark AOI is 88.44% usable.

### 5.2 Truth validation

The loader rejects any product that is not the expected FeatureCollection, CRS84 declaration,
AOI, source date, extraction method, or flood type. It requires positive official feature areas.
Invalid polygon rings are repaired with `make_valid` only when repair preserves source-coordinate
area. After projection, each geometry must agree with the official area within 0.2%.

P04 FLDEL02 represents observed event-flooded area, not total water extent. The headline score uses
the published event polygons unchanged. Subtracting before-scene SCL/NDWI water is retained only as
a sensitivity analysis and must not replace the headline.

### 5.3 Scoring path

1. Read and harmonise the pinned red, green, blue, and NIR windows.
2. Run `ClassicalChangeDetector` with `VERTICAL_PRESETS["flood"]`.
3. Rasterise emitted detection polygons, not the internal threshold mask.
4. Rasterise EMSN194 truth onto the detector's projected 10 m grid.
5. Exclude pixels invalid in either scene's SCL plane.
6. Compute pixel-level TP, FP, FN, TN, precision, recall, F1, and IoU.
7. Write ignored review artifacts and compare the fresh summary with the tracked evidence record.

---

## 6. Failure handling and honesty gates

The benchmark fails closed when an input cannot support the claimed comparison:

- Missing archive or wrong hash: abort before decoding or scoring.
- Missing pinned STAC item: list discovered candidates and abort.
- Scene below 70% AOI usability: abort rather than widen to a different date.
- Wrong truth date, AOI, method, flood type, CRS, or area: abort.
- Geometry repair changes area or yields non-polygonal output: abort.
- Evidence JSON differs from a fresh run: investigate and update only when the cause is understood.

Network reads may be retried once for the known transient Earth Search COG failure. A retry must not
change the pinned scene IDs or truth product. No benchmark failure may trigger a production DB
write, preset adjustment, or paid brief call.

---

## 7. Verification gate

Before the phase is marked built and verified:

1. Run focused EMSN194 tests.
2. Run the complete backend suite in Docker.
3. Run Ruff lint and format checks in Docker.
4. Run the benchmark against the pinned official archive.
5. Compare the generated summary with the tracked evidence JSON field by field.
6. Review the before, after, and comparison images for obvious grid, cloud-mask, or truth-product
   mismatch.
7. Run `git diff --check`.
8. Perform a final code review of the complete branch diff.
9. Confirm `PROGRESS.md` records the fresh commands and results without generalising the claim.

The existing candidate result is precision 0.586, recall 0.605, F1 0.595, and IoU 0.424 across
104 emitted detections. Those figures remain candidate evidence until reproduced from the clean
branch and accepted at this gate.

---

## 8. API key and operational state

This phase requires no Anthropic API key. The main workspace key remains present and Compose passes
it to API, worker, and beat, but the benchmark worktree has no `.env` and Docker is currently
stopped. Do not copy the key into the new worktree. If a later production brief regeneration is
approved, pass the main workspace environment explicitly and select Sonnet 5; the code default is
the more expensive `claude-opus-4-8`.

---

## 9. Phase exit

The phase exits with one reviewed flood-benchmark PR whose code and evidence reproduce on current
`main`. The preserved `phase-accuracy-benchmarks` worktree is not removed until the new branch is
verified and its unique content is accounted for. Forest accuracy begins as a separate design
cycle after this PR; SWIR begins only after both baseline and target evaluation protocol are fixed.
