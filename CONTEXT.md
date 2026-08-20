# CONTEXT.md — Overwatch Domain Glossary

Maintained via the `domain-modeling` skill. Read this before touching imagery ingestion or the change detection engine — the facts below were each discovered the hard way (a real bug against real Sentinel-2 data), and any change in this area should treat them as constraints, not surprises.

## Reusable accuracy and interview narrative

Use this section for resume bullets, LinkedIn posts, portfolio case studies, and interview answers. Do not reconstruct these claims from session history.

> **Correction, 2026-08-21.** Every OSCD figure in this section was restated. Between 2026-08-13 12:00 (`2398aa7`, benchmark committed) and 16:24 the same day (`c359f83`, terminal-centered spatial prior added), the shipped `port` preset changed and the benchmark was never re-scored. The previously published numbers (precision 0.345, recall 0.526, F1 0.417, IoU 0.263) reproduce only with `focus_radius_m=None` and describe a detector that has not shipped since 2026-08-13. **Do not reuse them from any older copy of this file, an older resume draft, or session history.**

- **Port construction is the most thoroughly benchmarked detector result.** The shipped `port` preset (`ssim_dissim >= 0.55`, `min_area_m2=5,000`, `focus_radius_m=2,000`) scores precision **0.325**, recall **0.280**, F1 **0.301**, and IoU **0.177** on the held-out OSCD test split of 10 Sentinel-2 urban-change scenes. The train split scores precision **0.189**, recall **0.271**, F1 **0.222**, IoU **0.125** over 14 scenes. The evaluation scores emitted polygons after morphology, the minimum-area floor, and the spatial prior — what an API consumer actually receives. The run is bit-reproducible across invocations.
- **Do not lead with a single headline metric.** The defensible framing is the pair of limits, because they have different causes and different fixes:
  - **Precision (0.325)** is a specificity limit. A generic structural-change signal also responds to roads, roofs, bare soil, shadows, and seasonal appearance outside the labelled target. Not a cloud-quality failure.
  - **Recall (0.280)** is a scope limit, and it is largely self-inflicted *by design*. The 2 km spatial prior keeps only change near the largest detection — correct for a single-subject port AOI, wrong for a whole-city benchmark. On metro-wide scenes precision holds while recall collapses (chongqing 0.697/0.061, milano 0.823/0.085, mumbai 0.638/0.069). OSCD is a conservative benchmark for this preset, not a flattering one.
- **Recall is stable across splits; precision is not.** Test recall 0.280 vs train recall 0.271 — the detector's sensitivity is a property of the method. Precision moves 0.325 → 0.189 and tracks how much change a scene actually contains. That asymmetry is the honest characterisation and points at precision as the lever worth working on.
- **The shipped threshold is evidence-backed, and the provenance is the point.** `0.55` is the F1 maximum of the 0.40–0.70 sweep on the held-out split. It was set by eye on Vizhinjam imagery on 2026-08-02 (`git log -S'threshold=0.55'` → `6f9524f`), eleven days before the dataset was downloaded (`2398aa7`, 2026-08-13). State the dates when quoting it — they are what make it external validation rather than fitting.
- **Scope the claim correctly.** OSCD labels urban change, so these figures validate construction/port-style change detection rather than universal port-activity accuracy. The live Vizhinjam result is separate, weaker evidence: **16 detections** and **78.9 ha**, produced by the `rerun_detection` maintenance path after the prior changed — the originating job row still records 12. It demonstrates the workflow; it is not a held-out accuracy score and must not be described as pipeline output without that qualifier.
- **Flood has separate, narrower evidence.** The date-matched Porto Alegre EMSN194 case scored precision **0.586**, recall **0.605**, F1 **0.595**, and IoU **0.424**. These figures cover one event, footprint, and observation date. **Always attach the independence caveat**, which the result file carries itself: CEMS derived the analyst-reviewed extent from same-day Sentinel-2 plus radar, so the truth is authoritative but not fully independent of the optical acquisition being scored. It is the first thing a remote-sensing reviewer will ask about; volunteering it is stronger than being asked.
- **Forest is the only vertical closed as a research extension (2026-08-19).** The five-window PRODES baseline scored precision **0.216**, recall **0.384**, F1 **0.277**, and IoU **0.161**, with severe location dependence (Novo Progresso collapsed to precision **0.011**). The failure is systematic, not cell-specific: two-date optical NDVI cannot separate permanent clearing from harvest, seasonal vegetation change, degraded canopy, haze, and shadow. A spatial holdout would not change the product decision because the detector already demonstrated location dependence across the five benchmark cells, including collapse on the flagship Novo Progresso AOI. Do not present the baseline or the temporary `ndvi_before` candidates as production accuracy.
- **Forest stays future work pending stronger evidence.** A production forest capability would require multi-temporal evidence, seasonal normalization, and stronger spectral features such as SWIR-derived NBR/NDMI, validated on held-out locations. The decision is closed; the five-window baseline is the recorded negative evidence.

### Short portfolio wording

> Overwatch uses deterministic change detection over Sentinel-2 imagery, scored against three independent public ground-truth sets. On the held-out OSCD urban-change test split the shipped construction preset reaches **F1 0.301** (precision 0.325, recall 0.280), measured with the spatial prior it actually ships with; recall holds within 0.01 of that on the train split, so sensitivity is a property of the method rather than of one split. A separate date-matched Porto Alegre flood case reaches **F1 0.595**, with the caveat that the CEMS truth was derived partly from the same-day acquisition being scored. Forest-loss detection was benchmarked against the INPE PRODES baseline, scored **F1 0.277**, and was removed from the product rather than demoed — two-date optical imagery does not distinguish permanent clearing from harvest and seasonal change across heterogeneous tropical scenes.

## Sentinel-2 BOA processing baseline offset

Earth Search STAC items carry a raw digital-number (DN) encoding for Bottom-of-Atmosphere (BOA) reflectance that is **not consistent across processing baselines**. From baseline `04.00` onward, ESA's reprocessing adds a systematic `-1000` offset to the stored DNs unless Earth Search has already normalized it.

- `boa_dn_offset(props)` (`backend/src/overwatch/imagery/earth_search.py`) reads `s2:processing_baseline` and the `earthsearch:boa_offset_applied` flag: baseline `>= 4.0` and offset not already applied → `-1000`; otherwise `0`.
- `SceneMeta.dn_offset` (`backend/src/overwatch/imagery/models.py`) carries this value forward; **add `dn_offset` to raw DNs before any band-index math** (NDVI/NDWI/NBR). Skipping this silently shifts every index computed from a post-04.00 scene.
- Discovered in: `c836c8e fix(phase-2): harmonize Sentinel-2 BOA offset across processing baselines`.
- Why it matters here specifically: mixing an old-baseline scene (offset 0) with a new-baseline scene (offset -1000) in the same before/after pair produces a spurious uniform brightness shift that differencing reads as change everywhere — a false-positive generator, not a localized bug.

### The metadata lies for Sentinel-2C — trust the pixels

`s2:processing_baseline` and `earthsearch:boa_offset_applied` are **not reliable on their own**. Vizhinjam's 2025 after-scene `S2C_43PGK_20250211` advertises baseline `05.11` with `boa_offset_applied=False`, so `boa_dn_offset` returns `-1000` — but the DNs are already offset-free (red p50 = 314, the same scale as the 2021 before-scene). Applying the correction clipped **~90% of the scene to zero**: a near-black after-image, SSIM saturated, NDWI pinned at -1 over water, detection destroyed.

- Guard: `_offset_is_present()` in `backend/src/overwatch/imagery/harmonize.py` checks the data before trusting the metadata — if removing the offset would clip **>50% of valid pixels to zero**, the DNs already lack it, so harmonization is skipped and a warning is logged.
- **Expect this on any Sentinel-2C scene from Earth Search.** The guard self-corrects per scene, so the warning is informational, not a failure — but a new/recent AOI surfacing it is normal, not a regression.
- General lesson: a metadata flag describing what was *done to* the pixels is a hint. Where the correction is destructive if wrong, verify against the pixels themselves.

## One acquisition, several STAC items (reprocessings)

Earth Search can hold **more than one item for the same Sentinel-2 acquisition** — later reprocessings of identical pixels, distinguished by the numeric field in the id: `S2A_43PGK_20210212_0_L2A` vs `S2A_43PGK_20210212_2_L2A`.

- They are not interchangeable: atmospheric correction differs between processing runs, so surface reflectance (and therefore detection polygons) differ slightly. Vizhinjam 2021→2025 yields **9 polygons via `_0_` and 12 via `_2_`**, same dates, same preset.
- Which item you get depends on **how you pick**: `detection/cli.py` takes catalog order (`scenes[0]`); `find_usable_scene` sorts cloud-ascending and takes the first that clears the SCL gate. For 2021-02-12 the cloud values are 0.1416% (`_0_`) vs 0.0313% (`_2_`) — no tie, so each selector is deterministic but they disagree.
- Do **not** reach for the BOA-offset explanation when counts differ across items of the same date: check `dn_offset` first. Both 2021-02-12 items carry `dn_offset=0`.
- Consequence for idempotency: replace-set keys on `(aoi, before_scene_id, after_scene_id)`, and scene rows key on `stac_id` — so a stable selector gives a stable pair and a re-run rewrites the same rows. A selector that flip-flops between reprocessings would write a *second* pair rather than duplicate the first.

## Forest-precondition gate (deforestation preset)

Raw NDVI-decrease is **not sufficient** to detect deforestation: crop harvest also drops NDVI by a similar magnitude, and a naive threshold conflates the two.

- Fix: `_change_maps` in `backend/src/overwatch/detection/detector.py` now also computes absolute `<index>_before` maps (not just before/after deltas). The forest preset (`backend/src/overwatch/detection/presets.py`) ANDs the NDVI-decrease trigger with an `ndvi_before` floor — the "before" image must have actually been forest-level green, not already-cleared cropland.
- Discovered in: `2b6c1fb feat(detection): was-forest precondition for forest preset`, validated against the real Novo Progresso AOI pair: raw NDVI-decrease detections dropped from 103 → 63 polygons after the gate; the 40 removed were cropland already cleared before the observation window, not new deforestation.
- **Current thresholds are looser than the original gate**: NDVI-decrease `0.15`, `ndvi_before >= 0.50`, min_area `3_000` m² (was 0.20 / 0.60 / 5_000). The tighter set missed clearings visible by eye. `0.50` still sits well above cropland NDVI (~0.30–0.45), so the harvest-exclusion property survives. Novo Progresso: 24 → 88 detections, largest 11 → 18 ha.
- The precondition is **not universal**, and the deciding question is whether the *pre-change state* is
  single-valued. Deforestation always starts from forest and flooding always starts from not-water, so both
  take a precondition (see the flood section below). Port construction starts from sea *or* bare fill *or*
  vegetation, so a precondition there vetoes most of the target — see the port section below.

## Port construction is structural, not spectral (SSIM-only preset)

Port expansion is a **structural rebuild** of the harbour, and the pre-change surface differs by pixel: sea → built, bare fill → built, vegetation → built. Any spectral index co-signal captures one of those transitions and **vetoes the other two**.

- Concretely at Vizhinjam: an NDWI-decrease co-signal fired only on the water-facing reclaimed *edge* and vetoed the bare-fill interior, which was already land by the 2021 before-scene. The terminal came back half-outlined.
- Fix: the `port` preset is **SSIM-dissimilarity only**, threshold `0.55`, min_area `5_000` m². SSIM is agnostic to prior cover, so it fires wherever the surface was structurally rebuilt. False positives are controlled by the threshold and min_area, not by an index veto that misses most of the target.
- Result: largest polygon 19.6 → 39.6 ha, total 31 → 83 ha, with 74.9 ha inside ~1 km of the terminal.
- **The threshold is a completeness/precision dial, and 0.55 deliberately favours completeness.** It leaves ~14 stray coastal polygons (8.4 ha total, none over 1.05 ha, 1.5–3.9 km north) that are real 4-year change but not port construction. Tightening to `0.60` cuts the strays to 6 (4.3 ha) but shrinks the terminal body to ~30.3 ha. Confirmed visually and kept at 0.55 — the port reads cleanly, including port-adjacent buildings.

## Flood needs a was-NOT-water precondition (NDWI-increase fires on water→water)

NDWI-increase alone cannot separate **"land became water"** from **"water became more water-like."** Suspended
sediment raises NIR, so turbid water reads at NDWI ~+0.14 while clear water reads ~+0.54 — a delta of +0.40 on
pixels that were already water, double the 0.20 gate. Between two dates, sediment settling or a channel
deepening therefore reads as new flooding.

- Measured on the real Porto Alegre pair (2024-04-18 → 2024-05-21): **26% of detected area, 719.7 ha, sat on
  already-water pixels**, including one **251 ha polygon that was 100% water in the before scene**. Genuine
  flood polygons also swelled across the channels *between* islands, merging separate landmasses into one
  blob — the visual tell that surfaced this.
- Fix: `ThresholdRule(map="ndwi_before", direction="decrease", threshold=0.05)` — the pixel must have read
  `ndwi_before <= -0.05` (non-water) before it can count as flooded. Result: contamination **26.0% → 0.07%**,
  the 251 ha artefact gone, the largest polygon 672.3 → 474.9 ha at 0.00% already-water.
- `-0.05` rather than `0.0` because `ThresholdRule.threshold` is constrained `gt=0`, and because the land/water
  NDWI boundary here is sharp (median `ndwi_before` inside true flood area is **-0.73**). The margin costs
  ~19 ha of marginal wet-soil pixels and buys clean separation; the sweep from 0.00 to 0.20 moves total area
  only 2029 → 1956 ha, so the result is not threshold-sensitive.
- Note the direction convention: `direction="decrease"` means `value <= -threshold`, so a "must be low"
  precondition is expressed as a decrease rule (see `rule_mask`).

## A flood benchmark must match both footprint and observation date

A disaster activation covering the same regional event is not automatically valid ground truth for
the demo AOI. Copernicus EMSR720 covers the May 2024 Rio Grande do Sul floods, but none of its five
mapped AOIs intersects Overwatch's Porto Alegre bbox. Its products also stop before the live
2024-05-21 after-scene. Comparing either mismatch would score disagreement between observations,
not detector accuracy.

- Copernicus EMSN194 AOI01 intersects the exact Porto Alegre bbox and supplies P04 FLDEL02 observed
  flood polygons for 2024-05-08. A valid evaluation therefore fixes the Sentinel-2 pair to
  `S2A_22JDM_20240418_0_L2A` -> `S2A_22JDM_20240508_0_L2A`.
- P04 FLDEL02 means observed event-flooded area, not total water extent. Only 1.24% of valid truth
  overlaps the before-scene SCL water class; subtracting it changes F1 from 0.5953 to
  0.5943. Preserve the published event mask for the headline and report permanent-water subtraction
  only as sensitivity.
- The official 335-entry archive has SHA-256
  `7d61dc66b3440db52ae89a33b415ac2273078278792636a11a37873573db8877`. The archive hash, AOI id,
  source date, CRS, extraction method, flood type, and feature areas are benchmark identity. Reject
  mismatches before scoring.
- The source contains ring self-intersections. `make_valid` is acceptable only when repair preserves
  source-coordinate area, remains polygonal, and projected area agrees with the official field
  within 0.2%.
- Earth Search reports the 8 May tile as 72.34% cloudy while the Porto Alegre window is 88.44%
  usable by SCL. Catalog cloud may rank candidates but cannot veto them before AOI-level inspection.
- The verified run scored 104 emitted detections: precision 0.5858272270448109, recall
  0.605060437857485, F1 0.5952885212454537, IoU 0.4237799222465613, TP 107371, FP 75910, FN 70084,
  and TN 887326. It emitted 1,841.2 ha against 1,774.55 ha of truth on valid pixels; valid fraction
  was 0.8843450236496518. Focused tests returned 19 passed, the benchmark exited 0, eight artifacts
  passed structural review, and the tracked evidence matched the fresh summary semantically.
- This is a single date-matched Porto Alegre flood case. Forest and broader flood claims require
  independent multi-case baselines. Reproduce it with
  `docker compose run --rm --no-deps api pytest -q tests/test_eval_emsn194.py` and
  `docker compose run --rm --no-deps api python -m overwatch.eval.run_emsn194`.

## OSCD: read `cm.tif` and `imgs_*_rect`, never `cm.png` or `imgs_*`

Two file-choice traps in the benchmark archives, both of which fail **silently** and produce a
plausible-looking but meaningless number.

- **Labels.** `<city>/cm/<city>-cm.tif` is authoritative and encodes **1 = unchanged, 2 = changed**.
  The sibling `cm.png` is not interchangeable: abudhabi's is **RGBA with an all-255 alpha channel**,
  so the natural "any non-zero is change" decoder marks **100% of the scene changed**; aguasclaras'
  carries antialiasing artefacts spanning 150+ distinct values. `decode_cm()` therefore rejects any
  value outside `{1, 2}` — the guard exists because the assumption was wrong on first contact with
  the data, not in theory.
- **Imagery.** Use `<city>/imgs_1_rect/` and `imgs_2_rect/` — the coregistered pair on one grid,
  matching the label raster exactly. The plain `imgs_1/` / `imgs_2/` folders hold native per-band
  resolutions (10/20/60 m) and are **not pixel-aligned between dates**, so differencing them is
  meaningless. Band files in `_rect` are plain `B02.tif`…`B12.tif` plus `B8A.tif`.
- Band mapping is written out explicitly (`BAND_FILE`) rather than derived from the plane index:
  the "+1" rule that maps plane 1 → `B02` holds only to `B08`, because **B8A sits between B08 and
  B09**. A derived rule would drift the moment anyone reads a SWIR band.

## Score the polygons, not the threshold mask

Accuracy is measured by rasterising the detections the detector *emits* and comparing those to the
truth mask — not by scoring `rule_mask`'s output directly.

- This is what makes the number mean *"what `GET /aois/{slug}/detections` returns"* rather than
  *"what the thresholder saw"*. Morphology (open→close) and the `min_area_m2` floor both change the
  answer, and both are part of the shipped behaviour, so both must be inside the measurement.
- Consequence worth expecting: the min-area floor costs recall on benchmarks full of small changes.
  That is a real property of the shipped system, not a measurement artefact to tune away.
- `overwatch.eval` must never be imported by `overwatch.detection` — scoring code cannot be allowed
  to influence what is detected.

## PRODES annual increments: `year` is identity; `image_date` is provenance

The TerraBrasilis Amazon-biome annual-increment Shapefile is valid forest truth, but its temporal
fields are not interchangeable. `year=2024` and `class_name=d2024` identify the PRODES annual
increment class. `image_date` records the acquisition used to interpret an individual polygon; it
is not a second year label and must not be filtered against an invented July cut-off.

- The verified 2026-07-17 archive is
  `yearly_deforestation_biome_amazonia_v20260717.zip`, SHA-256
  `ffdf5e8f00cbc9f7f0ee9ed78ac2c7bbcc31c182c596205e353298b1cbf92fd4`. It contains one complete
  SIRGAS 2000 (EPSG:4674) Polygon Shapefile with 802,282 rows.
- DBF text is Windows-1252, not UTF-8. The real value `corte raso com vegetação` fails under
  `pyshp`'s UTF-8 default, so the adapter pins `encoding="cp1252"`.
- The main archive already contains 212,673 polygons below 6.25 ha (119,342 in Pará). Do not join
  the separate small-polygon product without proving disjoint semantics; doing so risks
  double-counting truth.
- Identity is fail-closed on `main_class=DESMATAMENTO`, `class_name=d<year>`, matching numeric
  `year`, `source=Amazonia`, `state=PA`, positive area, UUID, SIRGAS 2000 CRS, and polygonal valid
  geometry. The reprocessed archive contains isolated malformed/out-of-scope records, so broad
  trust in every row is unsafe.
- A benchmark pair must bracket every selected polygon's `image_date`. The existing Novo Progresso
  demo after-scene (2024-07-24) predates truth acquired on 2024-07-29 and 2024-08-03, so the forest
  benchmark pins a different pair rather than reusing the demo pair.
- Verified five-window baseline, unchanged forest preset: precision 0.2160882267542699, recall
  0.38420807368286397, F1 0.27660620692263793, IoU 0.1605008721939973. This is a truth-stratified,
  five-cell Pará baseline, not a statewide or Amazon-wide estimate. Full evidence lives in
  `benchmarks/results/prodes-amazon-2024-forest-five-window.json`.
- Product decision closed 2026-08-19: forest is a research extension, not a demonstrated capability.
  The retain/drop gate is retired; no holdout scoring was run because the baseline's systematic
  location dependence already answers the decision.
- Treat the tracked five-window result as immutable baseline evidence. A candidate experiment writes
  a separate detailed result and generated summary; it must retain the detector commit, archive hash,
  scene ids, usable and valid fractions, sampling frame, per-window scores, and pooled confusion
  counts. Never overwrite the baseline while tuning.
- Change one factor family per candidate so the result remains attributable. Forest thresholds,
  validity/cloud handling, morphology, and `min_area_m2` can use the current red/green/blue/nir/SCL
  inputs. SWIR/MNDWI/AWEI requires a separate hypothesis because it changes the imagery asset and
  detector contracts.

## Gate 3 sums the linked detections — one claim, one quantity

The numeric validator compares a quoted area against the **sum of every detection linked to that
claim**, not against any individual one. A claim that quotes two areas and links both detections
therefore fails twice: each quote is measured against the combined total.

- Observed live on the first real LLM brief: *"a single construction zone of about 396,500 m² and
  an adjacent area of roughly 217,200 m²"* with both detections linked → two `area_mismatch`
  violations, each citing `linked_area_m2=613700` (the sum). The regeneration loop split them into
  one-detection-per-claim statements and validated on attempt 2.
- The rule this enforces: **one claim, one quantity, one evidence set.** It is why the prompt must
  push the model toward atomic claims — and it is a genuine accuracy property, not pedantry, since
  a reader cannot tell which polygon a number refers to when several are cited together.
- Practical consequence for prompt work: expect a first-attempt rejection rate on multi-figure
  claims, and budget for `brief_max_attempts` accordingly (novo-progresso needed all 3).

## Demo briefs and real briefs share a table — the seeder is destructive

`seed_briefs` calls `_purge_briefs`, which deletes **every** brief for an AOI before writing its
hand-authored one. Run it after a live `generate_brief` and the paid Anthropic output is gone with
no warning.

- Guard: `_has_real_brief()` treats any **validated** brief whose `model != "demo-seed"` as real
  and skips that AOI; `--force` overrides. `DEMO_MODEL` is the single source of that literal.
- The distinction is the `model` column, not the status — both kinds land as `validated`, because
  the seeder calls `persist_validated` directly and bypasses the validator entirely.

## "Zero detections" is ambiguous — check for a job row before touching thresholds

An AOI serving **0 detections** has two completely different causes, and they look identical from the API:
the detector ran and found nothing (a tuning problem), or **the detector never ran** (an orchestration gap).
Scenes can exist without a job: ingestion during an AOI-viability check writes `scenes` rows directly, and
nothing downstream requires a job to follow.

- Porto-alegre sat at 0 detections for weeks, recorded in `PROGRESS.md` as "the flood engine found none
  though the flood is visibly obvious — a detection-tuning matter," with an inherited hypothesis about
  turbid-water NDWI false-negatives. Both were wrong: the AOI had **zero rows in `jobs`**. Running the
  shipped preset on its existing pair, unchanged, produced **75 detections / 2,686.5 ha**.
- **Check first:** `select count(*) from jobs where aoi_id = ...`. One query separates the two causes and
  costs nothing. Tuning a preset against an AOI that never ran is unfalsifiable work.
- Note that `rerun_detection.py` and `seed_briefs.py` both derive the scene pair from the AOI's *latest
  detection*, so neither can bootstrap an AOI that has none — the first run must go through
  `POST /aois/{slug}/jobs`. Tight date windows (±1 day around the known captures) reselect the existing
  scene rows rather than creating new ones.

## Alembic fileConfig silently disables app loggers

Running a migration **in-process** (the `migrated_db` pytest fixture, any programmatic `command.upgrade`) executes `alembic/env.py`, whose `fileConfig(...)` defaults to `disable_existing_loggers=True` — every already-instantiated app logger (e.g. `overwatch.imagery.gating`) goes dead afterward, and `caplog` assertions on their output fail *only when a migration ran earlier in the same process*.

- Fix: `fileConfig(config.config_file_name, disable_existing_loggers=False)` in `backend/alembic/env.py`.
- Symptom to recognize: a log-asserting test passes in isolation but fails in the full suite, with the failure appearing when an unrelated DB test file is added before it alphabetically (discovered Phase 3, Task 1: adding `test_db_schema.py` broke `test_gating.py`).

## Pytest DB fixtures: cleanup must depend on the session fixture's consumer

A function-scoped DB-session fixture (`db_session`) keeps its transaction open until teardown. Any cleanup fixture that deletes the same rows from a *separate* session must tear down **after** it — otherwise the cleanup `DELETE` blocks on row locks held by the still-open transaction while that transaction's commit waits for the cleanup to return: a cross-session hang Postgres cannot detect as a deadlock (one waiter is Python, not SQL).

- Fix shape: `db_session` **depends on** `clean_t3` (`def db_session(clean_t3)`), so pytest instantiates cleanup first and finalizes it last, after the commit.
- Sneaky part: the wrong order passes on a clean DB (uncommitted rows are invisible to the cleanup, which silently deletes nothing and leaks them); it only hangs on the *next* run when the leaked rows are visible and lockable. Discovered Phase 3, Task 6 — a 30-minute pytest hang; `pg_stat_activity` showed `idle in transaction` + a `DELETE ... LIKE 't3-%'` waiting on a lock.

## Celery worker/beat containers need the same mounts and DB env as `api`

Through Phase 2 the `worker` and `beat` services only ever ran `overwatch.ping`, so their compose entries carried neither a source bind-mount nor `OVERWATCH_DATABASE_URL`. They silently ran the **baked image** (stale code) and had no Postgres access at all.

- Symptom: `celery inspect registered` lists only the tasks that existed when the image was last built; new tasks appear in `api` (which *is* mounted) but never in the worker, and `docker compose restart worker` does not help — only a rebuild would.
- Fix (Phase 3, Task 9): `worker` and `beat` now mount `./backend/src:/app/src`, set `OVERWATCH_DATABASE_URL`, and `depends_on: postgis`.
- Standing rule: **workers do not hot-reload.** After changing `overwatch/workers/*`, run `docker compose restart worker beat`; after changing the Dockerfile or deps, `docker compose up -d --build worker beat`.

## Celery `retry()` is a no-op when a task is called directly

`task_fn(args)` sets `request.called_directly`, and Celery's `retry()` then **re-raises the original exception instead of retrying**. A test that calls the task directly can never observe `autoretry_for` / backoff, and `on_failure` never fires either.

- To exercise the real retry path in tests, use `task.apply(args=(...))`: it runs eagerly with `called_directly=False`, burns all `max_retries`, and ends in `FAILURE` with `on_failure` recorded. Phase 3's `test_network_error_retries_visibly_then_fails` asserts `attempts == 4` (1 initial + 3 retries) this way.

## Docker/WSL2 requirement

GDAL/rasterio on native Windows is a known tarpit (PROJECT.md §2.3) — the dev environment lives entirely in containers. Don't debug import/build errors on the host; reproduce inside `docker compose` first.

**Clean-shutdown convention (2026-08-19).** Start Docker Desktop and the WSL2 VM only when a
verification run needs them, and shut them down cleanly in the same session. The eval/test gates
need only the `postgis` compose service (`docker compose up -d postgis`); an API daemon, Redis,
worker, and beat are not required. Clean shutdown sequence:
`docker compose -p <project> down`, quit Docker Desktop (no `Docker Desktop` /
`com.docker.backend` processes), then `wsl --shutdown`, then confirm `wsl --list --running` is
empty and no `vmmemWSL` process remains. Leaving the VM up silently burns RAM and battery.

## Anthropic brief generator: Opus 4.8 API constraints + deferred credential validation

The Phase-4 `AnthropicBriefGenerator` (`backend/src/overwatch/briefs/generator.py`) has two non-obvious constraints, both discovered during Phase-4 execution against SDK `anthropic==0.116.0`:

- **Opus 4.8 rejects sampling params.** Sending `temperature`, `top_p`, or `top_k` to `claude-opus-4-8` returns a **400**, not a silent ignore. The generator sends none of them. It uses structured output via `client.messages.parse(..., output_format=BriefDraft)` (read `.parsed_output`) and `thinking={"type": "adaptive"}` (the `budget_tokens` form is also rejected on this model). A refusal or a `None` `.parsed_output` is treated as a permanent failure (`brief_refused` / `brief_parse_failed`), not a crash.
- **`anthropic.Anthropic(api_key=None)` does NOT raise** on this SDK version — credential validation is deferred to the first request, not the constructor (a "fact" I initially got wrong and the implementer corrected empirically). Consequence: constructing the client can't be your missing-key guard. The real guard is at the **API layer** — `POST /aois/{slug}/briefs` returns `422 briefs_unconfigured` when `settings.anthropic_api_key` is falsy, before any brief row is created. The generator itself maps `AuthenticationError` → `PermanentBriefError("anthropic_auth")` as a backstop. When adding new entry points that call the generator, replicate the settings-level key check; do not rely on client construction to fail.

Standing rule: all 187+ tests run with `FakeBriefGenerator` / mocks, so **CI never needs the Anthropic key**. The key enters `.env` only for the live verification gate (user-supplied, never committed).

## GDELT: no geotag exists, and the GKG geofence is a trap

Measured against live queries during the Phase-5 spike (2026-07-12). **Do not rebuild the geofence.** Design-spec §3.2's
"article geotag within the AOI buffered by 25 km" was written against a GDELT surface that does not exist.

- **GEO 2.0 is down (documented-flaky), and would not help even if up.** `api.gdeltproject.org/api/v2/geo/geo` → **HTTP
  404** on every form, 5/5 retries: bare query, `mode=PointData&format=GeoJSON`, `format=csv`, and the exact
  `theme:env_nuclearpower&mode=country&format=html` URL from GDELT's own docs. (`doc/doc` and `tv/tv` resolve fine;
  `/api/v2/geo` 301s to `/api/v2/geo/` which 403s.) GDELT's client-library docs call the GEO endpoint *"occasionally
  unavailable (HTTP 404) independent of the DOC API"* — so it is flaky, not provably retired. **Do not chase it:**
  GDELT states GGG is *"the underlying dataset powering the GEO 2.0 API"*, so GEO 2.0 / `format=geojson` / `format=csv` /
  BigQuery `gdelt-bq.gdeltv2.ggg` / raw GKG `V2Locations` are all **the same geocoder through different pipes**.
  Changing transport does not change the payload. DOC 2.0 is the only usable surface.
- **DOC 2.0 returns no coordinates.** A record carries exactly `url, url_mobile, title, seendate, socialimage, domain,
  language, sourcecountry`. There is no location operator either: `locationcc:BR` comes back as *"keywords were too
  short, too long or too common"* — it was parsed as a literal keyword.
- **`sourcecountry` is the publisher's registration country, not the story's location.** Mongabay's article about
  deforestation in Pará, Brazil returns `sourcecountry: Indonesia`. Never use it as a geographic proxy.
- **GDELT's DOC 2.0 *debut* documentation page is STALE about the date range — do not trust it.** It states
  `STARTDATETIME`/`ENDDATETIME` **"must be within the last 3 months"**, and search engines happily quote that back at
  you. It is obsolete: the ["1.5 Year Searching"](https://blog.gdeltproject.org/doc-2-0-updates-1-5-year-searching-and-updated-mobile-interface/)
  post says the rolling cutoff was *"permanently replaced"* with a fixed **Jan 1 2017** start date. Settled empirically
  in-repo: `backend/tests/fixtures/gdelt/vizhinjam_2024.json` is a verbatim DOC `artlist` capture of **June–July 2024**
  articles, retrieved on **2026-07-12** — i.e. **two years** after publication. **Historical windows work.** If a
  historical query comes back empty, the date range is not your bug; look at the query's theme conjunction instead.
  (Cost us most of a session on 2026-07-14 chasing a coverage limit that does not exist.)
- **The GKG-bucket geofence works mechanically and fails on data quality.** DOC's `seendate` does map onto a GKG bucket
  file (`20240512214500.gkg.csv.zip`, 3.4–8.9 MB), the article is findable in it, and `V2Locations` does carry lat/lon.
  But for the three articles our demo depends on, GKG's geocoder returned: the **country centroid of India** (~1,000 km
  from Vizhinjam); **Mato Grosso do Sul, Rio Grande do Sul, and Spain** for the Novo Progresso/Pará story (~330 km, and
  Pará never appears); and for a third, the seendate bucket contained an **Ethiopia militia story** instead of the
  article. **A 25 km geofence rejects 100% of our true positives.** V2Locations resolves to country/ADM2 centroids driven
  by incidental place mentions in body text, not the story's subject location.
- **Titles routinely omit the place name.** DOC exposes only the title; its `query` matches full text. Zero of six Porto
  Alegre articles say "Porto Alegre" in the title; zero of four Novo Progresso articles say "Novo Progresso" — they all
  say "Amazon". A title-only toponym gate scores 0/6 and 0/4 on our own demo corpus. Hence Phase 5's two-layer design:
  the **strict** term is enforced by GDELT against full text at retrieval; the pure scorer corroborates against a
  **generous** term list (including regional names) that actually appears in titles.
- **Rate limiting:** HTTP **429** with a **plaintext** body (not JSON) — never `json.loads` a GDELT response without
  checking. A `200` can also carry a plaintext error. ≥5 s between requests; after a burst it took ~75 s to clear.

**Root cause, in GDELT's own words — this is why no access method rescues the geofence.** From the GGG announcement:
*"all locations are drawn from a set of **centroid-based gazeteers** in which every reference to Paris, France will
always yield precisely the same coordinate."* **News geocoding resolves a place mention to that place's centroid; our
AOIs are sub-place polygons.** Novo Progresso is a ~38,000 km² municipality — its centroid can sit >100 km from our
~60 km² AOI. A 25 km geofence is not a strict gate that happens to be broken; it is geometrically meaningless at our
resolution. BigQuery/GGG was evaluated and rejected on these grounds (plus a GCP dependency for a demo that otherwise
needs no cloud account).

**Worth revisiting in v0.2:** GGG rows are per *location-mention* and carry `ContextualText` (600-char snippet) and
`GeoType` (precision code; `>1` excludes country centroids). That context field is a much better substrate for the
**toponym and thematic** gates than a title — it fixes "titles omit the place name" — but it does **not** rescue a
*spatial* gate. The decisive BigQuery sandbox query that would overturn the decision is in the design doc §2.4b.

Full evidence and the resulting gate design: `design-specs/2026-07-12-phase-5-osint-fusion-design.md` §2.
