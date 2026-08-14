# PROGRESS.md — Overwatch

> Living session-state file. Convention: nothing is "done" until it's in **Built & verified** with a note on *how* it was verified.

## Current phase
**Phase 6 — Frontend arena: COMPLETE — all 9 tasks built + verified, demo-ready (2026-07-27). Branch
`phase-6-frontend-arena` (off `phase-5-osint-fusion`), committed, NOT yet pushed / merged.**
Executed `plans/2026-07-12-phase-6-frontend-arena.md` via `superpowers:executing-plans`, verifying each task live in
the browser (Playwright screenshots). **Verification gate GREEN:** tsc clean; 14 frontend tests; 296 backend tests;
`vite build` succeeds (582 KB gz); ruff check + format clean; **both evidence-join directions proven live**
(claim→map leader-line + fly-to; map-polygon→claim select+scroll); contrast measured (ink 14.96:1 / dim 6.98:1 /
faint 4.61:1 on panel); `prefers-reduced-motion` block present.

*Done & verified (2026-07-26/27, in-container + live browser at localhost:5173):*
- **Task 2** scaffold — React **19**, Vite/Tailwind v4, Vitest; bespoke OKLCH tokens; contrast MEASURED (ink 14.96:1, dim 6.98:1).
- **Task 3** pure bidirectional evidence join (`buildEvidenceIndex`/`boundsOf`) — 8 tests. **Task 5** selection reducer — 6 tests. (14 frontend tests green, tsc clean.)
- **Task 4** typed API client + TanStack Query hooks (2s polling), aligned field-for-field to the backend Pydantic schemas.
- **Task 1** scenes API — `GET /aois/{slug}/scenes` + `GET /scenes/{id}/image` (deterministic path, on-demand render + cache). 296 backend tests green.
- **Task 6** map canvas — two synced MapLibre maps + clip-path swipe, vector Carto dark-matter basemap tinted to surround, deck.gl detection overlay (both sides), selection = magenta halo + stroke weight.
- **Comprehension layer (from user feedback):** header context line (`<vertical> · <finding> · <before> → <after>`), dated swipe chips, change-type legend — all derived from AOI+detections, no LLM needed. Fixed-reflectance imagery stretch so before/after read as consistent daytime.
- **Task 7** brief panel + bidirectional click-to-evidence + magenta leader-line (rAF-glued; suppressed above a 6-detection cap) + rejected/stale/empty states. Demo briefs are hand-authored but DATA-GROUNDED (real detection ids, computed areas), seeded via `python -m overwatch.db.seed_briefs`, marked `model="demo-seed"` — real LLM briefs drop in once the Anthropic key is funded.
- **Task 8** scene timeline rail (date axis, pair connected, click a scene to swap after-imagery) + ⌘K/Ctrl-K read-only command palette (jump to area / light a claim) + final column composition.
- **Task 9** verification gate GREEN (see Current-phase summary). **Demo is READ-ONLY (user-approved)** — no live job/brief triggers; always fast, no dependency on live Sentinel-2 or the blocked key.

*Upgrades folded in (user-approved):* vector graphite basemap; clip-path swipe; evidence leader-line; ⌘K palette; React 19.

*Key engineering facts for resume:*
- **maplibre-gl pinned to v5** — deck.gl 9.3 `MapboxOverlay` crashes on v6's refactored camera internals (`_nearZ`).
- **Frontend dev runs on the HOST** (`cd frontend && npm run dev`, localhost:5173). The compose `frontend` service bakes source with no bind-mount and shadows the port — **`docker compose stop frontend`** before host dev. Vite proxies `/api` → localhost:8000.
- Backend render robustness: `_scene_meta` backfills pre-Phase-6 rows (porto-alegre) + derives UTM epsg from the MGRS tile; console renders at fixed_max=3000, gamma=0.75.
- Commits on branch (…`8b80e19` fixed-stretch) → `65b6eb7` progress → `c900795` brief-panel/leader-line → `a69fdcb` timeline/palette → `a97ae54` format.
- **Demo caveats (honest, not bugs):** (1) ~~Vizhinjam's *after* (2025) scene still renders dark — its harmonized water reflectance is genuinely ~0 that day.~~ **WRONG, fixed 2026-08-02 (`9ebc0b5`)** — that was a real bug, not real radiometry: the S2C scene's BOA offset was subtracted twice, clipping ~90% of the scene to zero. See the detection-quality iteration below. (2) ~~Porto-alegre has 0 detections — the flood engine found none though the flood is visibly obvious (a Phase-2 detection-tuning matter, out of Phase-6 scope).~~ **WRONG, resolved 2026-08-03** — the engine was never run on porto-alegre (the AOI had **zero job rows**; its scenes were ingested in Phase 1 and nothing followed). The shipped flood preset finds **75 detections / 2,686.5 ha** on that pair untouched. Not a tuning matter; a never-executed one. (3) Briefs are seeded (marked DEMO) until the key is funded.

### Detection-quality iteration (2026-08-01/02, on the same branch, committed `9ebc0b5`…`09c061d`)

A follow-on pass after the phase gate, triggered by the "dark after-image" demo caveat above turning out to be a bug.

- **Root cause found: the S2C double-offset.** Vizhinjam's only 2025 after-scene is Sentinel-2**C**
  (`S2C_43PGK_20250211`). Earth Search advertises `s2:processing_baseline=05.11` with
  `boa_offset_applied=False`, so `boa_dn_offset` returned −1000 — but the raw DNs already lacked the offset
  (red p50=314, matching the before-scene). Subtracting it clipped **~90% of the scene to zero**, which
  produced *both* the dark after-image and broken detection (SSIM saturated, NDWI = −1 over water).
  Fixed with a data-aware `_offset_is_present()` guard: if removing the offset would clip >50% of valid
  pixels to zero, skip harmonization and warn. **Recurs for any S2C scene** — the guard self-corrects, so the
  warning is informational. Recorded in `CONTEXT.md`.
- **Port preset is now SSIM-only** (0.55 / 5,000 m²), dropping the NDVI/NDWI co-signal. Port construction is
  *structural* and the prior surface varies per pixel (sea/bare/vegetation → built), so any spectral co-signal
  vetoes most of the target — NDWI-decrease caught only the water-facing reclaimed edge and left the terminal
  half-outlined. Largest polygon **19.6 → 39.6 ha**, total **31 → 83 ha**, 74.9 ha within ~1 km of the terminal.
- **Forest relaxed** (ndvi decrease 0.20→0.15, ndvi_before 0.60→0.50, min_area 5,000→3,000 m²) after clearings
  visible by eye were being missed. Novo Progresso **24 → 88** detections, largest **11 → 18 ha**. The 0.50 floor
  still sits above cropland NDVI (~0.30–0.45), so the was-forest harvest exclusion survives.
- **New tool** `backend/src/overwatch/db/rerun_detection.py` — re-runs only the detection step against an AOI's
  existing scene pair (no re-ingest, no Celery), so preset tuning iterates in seconds.
  ⚠ **Detection ids change every run → always re-seed briefs after** (`python -m overwatch.db.seed_briefs`).
- **Threshold decision closed:** port stays at **0.55**, confirmed visually by the user 2026-08-02 — the terminal
  and port-adjacent buildings read cleanly. It deliberately favours completeness and leaves ~14 stray coastal
  polygons (8.4 ha total, none over 1.05 ha, 1.5–3.9 km north) that are real 4-year change but not port work.
  0.60 would cut those to 6 (4.3 ha) but shrink the terminal body to ~30.3 ha. Rejected.

### Absolute gates + the first spatial prior (2026-08-13, same branch)

Triggered by two user-reported false positives on the live console. Both were fixed with **free**
signal (no new bands, no re-fetch, no LLM). Verified in-container: **334 passed**, ruff check +
format clean (130 files), plus a read-only A/B against the real scene pairs. The A/B ran *before*
any DB write on purpose: `evidence_links.detection_id` is `ondelete=CASCADE`, so a replace-set
strips the evidence off any brief over that scene pair. Once the numbers were confirmed and the
user approved the spend, detection was re-run and all three briefs regenerated (see below).

| AOI | vertical | previous | now | change |
|---|---|---|---|---|
| porto-alegre | flood | 66 det / 1,932.7 ha | 66 det / 1,932.7 ha | **unchanged — gate withdrawn, see below** |
| vizhinjam | port | 22 det / 83.3 ha | 16 det / **78.9 ha** | −4.4 ha (95% kept) |
| novo-progresso | forest | 88 det / 163.7 ha | 88 det / 163.7 ha | unchanged (no gate added) |

- **Flood: an absolute after-image floor was shipped and WITHDRAWN the same day. It was wrong.**
  The reasoning was sound and the instrument was not. The was-NOT-water precondition is blind to
  land that merely gets **darker** — shading a canopy suppresses NIR harder than green, so NDWI
  climbs ~0.37 (past the 0.20 delta gate) from −0.71 to −0.33 while clearing the was-not-water gate
  *because shaded forest was never water* — so `ndwi_after >= 0.05` was added to demand the pixel
  actually BE water. It cut 1,932.7 ha to 925.8 ha, and I recorded that 1,006.9 ha as false
  positives. **It was mostly real flood.** Porto Alegre's floodwater is heavily sediment-laden, and
  suspended solids raise NIR, which drags NDWI down: the gate rejected the brown turbid water that
  *is* the flood. Caught by the user against the console, not by the sweep — the sweep showed a
  smooth curve with no knee, which I read as "pick on principle" when it actually meant "this index
  does not separate these two populations".
- **`ndvi_after` was measured as the replacement and also rejected.** NDVI is far more
  shade-invariant, so it should discriminate better, and its curve is smooth too: `<= 0.00` keeps
  57.6% of baseline, `<= 0.10` 64.3%, `<= 0.30` 76.4%, `<= 0.50` 92.2% — by which point it no longer
  gates anything. **No absolute threshold on red/green/blue/nir separates turbid floodwater from wet
  vegetation here**, because the scene is a continuum: open brown water, shallow water over grass,
  partly submerged canopy. The lesson worth keeping: a sweep with no knee is evidence the index is
  wrong, not licence to choose a value from first principles.
- **The real fix needs SWIR, which is not fetched** (`_KEEP_ASSETS` is red/green/blue/nir/scl).
  Water absorbs SWIR almost totally whatever its sediment load; shaded and wet vegetation does not.
  MNDWI = (green − swir16)/(green + swir16), or AWEI_sh with its explicit shadow term, makes the cut
  NDWI and NDVI cannot. Two more assets plus a re-fetch, so it is a scoped follow-up. Until then
  flood **prefers recall over precision on purpose**, and the shaded-land false positive is tracked
  by an `xfail(strict=True)` in `test_detector.py` rather than quietly dropped.
- **Rule grammar gained `at_most`/`at_least`** (kept from the attempt): `increase`/`decrease` read
  the threshold as a magnitude about zero, which cannot express a bound whose sign disagrees with
  its direction ("NDVI at most +0.10"). The new directions take the threshold literally, so 0.0 and
  negatives are ordinary values. No shipped preset uses them yet; the SWIR work will.
- **Port: the first *spatial* prior — anchored on the TERMINAL, not the shoreline.** Off-subject
  buildings scored `ssim_dissim` ~0.87, **as high as the terminal itself**, so they are real
  construction and no threshold separates them (raising it drops the terminal too). Only location
  disqualifies them. Final: **`focus_radius_m=2000`**, keeping detections within 2 km of the largest
  polygon. **22 det / 83.3 ha → 16 / 78.9 ha**: the whole ≤2 km cluster survives untouched (8
  polygons at ≤1 km / 34.9 ha, 7 at 1–2 km / 4.4 ha) and all six scattered sub-hectare polygons
  beyond 2 km are dropped. 95% of detected area kept.
- **A shoreline buffer was shipped first and withdrawn.** `near_water_m=1000` + a 10 ha minimum
  water-body size gave 14 det / 77.8 ha, but it was the wrong question: the AOI is 4.5 × 5.5 km of
  coast, so *every* pixel is within 2 km of the sea (a 2 km water buffer gates nothing at all),
  while 1 km reached the strays only by also cutting five genuine near-port polygons. It also needed
  the size floor as a patch, because the water mask holds the 1,538 ha sea **plus 16 specks of
  ≤0.1 ha** that each seeded a buffer of their own. Proximity to water was only ever a proxy for
  proximity to the port; the anchor says it directly and needs no per-AOI configuration (the
  terminal is 39.6 ha against a next-largest of ~1.1 ha).
- **Deliberately permissive, per user direction:** map the change completely first, trim later.
  Whatever survives is a *relevance* question ("is this port work?") that geometry cannot answer,
  and that judgement is the LLM layer's job — the one place in this pipeline where an LLM earns
  its cost, since the spectral and geometric evidence is already exhausted.
- **New module** `detection/priors.py` (`keep_near_largest`) — pure geometry, applied *after*
  polygonization because the anchor does not exist until regions are labelled and measured.
  Distance is edge-to-edge, not centroid-to-centroid: a quay runs hundreds of metres and centroid
  distance would push its own apron outside the radius.

### Fixed: the after-pane sometimes rendered bare basemap under the polygons (2026-08-13)

User report: "sometimes it opens like this", with the right pane showing the dark basemap and
detection polygons but **no imagery** — which reads as the detector outlining dry green land,
because the visible left pane is the *before* scene where those islands had not yet flooded.

Ruled out first, with evidence, not by inspection: the UI pair matches the detection pair for all
three AOIs (checked `scenes[0]/scenes[-1]` against `before_scene_id`/`after_scene_id`); every
scene PNG is cached; `GET /aois/{slug}/scenes` has a stable `ORDER BY captured_at, id`.

Root cause in `applyRaster`: it correctly refuses to touch sources before `isStyleLoaded()`, but
**nothing ever re-ran it**. The caller's readiness flag flips exactly once (maplibre `load`) and
the scene id never changes afterwards. The *after* map loses that race routinely because it is
jump-synced to the before map's camera in the same tick its flag flips — the jump starts basemap
tile loads, so `isStyleLoaded()` reads false right when the effect fires. The raster was dropped
permanently until a reload happened to win.

- Extracted to `frontend/src/components/mapRaster.ts` so the readiness path is testable against a
  fake map; **4 new tests** (18 frontend total). The retry now lives in `applyRaster` rather than
  depending on the caller to re-fire: a one-shot `once("idle")` per map+key, deduped so scene
  switches don't stack listeners, replaying the *latest* requested scene.
- Gate: tsc clean, 18 frontend tests, `vite build` succeeds. **Browser confirmation still pending**
  — the repro is intermittent and no browser driver is available here, so the loop is unit-level.
- ⚠ **Vitest needs `--pool=threads` on this Windows box.** The default forks pool times out at 60 s
  waiting for a worker; with threads the same suite runs in ~2 s.

*Next:* Phase 6 is demo-ready. Remaining is integration, not build: **push `phase-6-frontend-arena` + open a compare URL for the user to merge** (direct push to main is denied by policy; user merges). Optional follow-ups if desired: split the 2 MB JS bundle (`manualChunks` for maplibre/deck). (~~tune the flood preset so porto-alegre lights up~~ — done 2026-08-03; it needed a job run, not tuning.)

### Porto Alegre demo adoption + live brief (2026-08-14)

The live Porto Alegre demo now uses the date-matched EMSN194 pair **2024-04-18 → 2024-05-08**:

- Production job `2b63e224-3571-4ee2-b32e-691f299e3a3c` completed with **104 detections / 1,841.2 ha**.
- The old `2024-04-18 → 2024-05-21` detection set was retired atomically; its briefs remain append-only history and are `stale`.
- Eleven of the fourteen existing GDELT articles fall inside the new fusion window and were copied to after-scene `5392`; the three May 23–27 articles remain on the historical pair.
- Brief `1601` was generated and validated with **Claude Sonnet 5**, attempt 2, with **77 detection evidence links + 11 article evidence links** and zero dangling links. The three first-attempt area violations are retained in the brief's audit history.
- The scene and detection endpoints now derive the active pair from the latest succeeded job, so historical polygons cannot overlay newer imagery and a successful zero-detection run still controls the displayed pair. AOIs without a successful job retain the historical fallback.
- Catalog cloud metadata now ranks candidates without vetoing them before the AOI-level SCL gate; unrestricted Earth Search calls omit the cloud predicate, including the 100% boundary.
- Verified live: both scene PNGs return 200; all API detections use `(17, 5392)`; frontend build succeeds; frontend tests pass **18/18** with `npm run test -- --pool=forks --no-file-parallelism`; backend tests pass **340 passed, 1 xfailed**; Ruff lint and format checks pass.
- Known non-blocking warning: the frontend production JS bundle is **2,063 kB / 582 kB gzip**. The default Windows Vitest worker mode can time out; sequential file execution is the verified command.

**Built & verified (2026-08-14):** live PostGIS/API checks above; `docker compose exec -T api pytest -q`; `docker compose exec -T api ruff check src tests`; `docker compose exec -T api ruff format --check src tests`; `npm run build`; and sequential frontend Vitest command above.

---

**Phase 5 — OSINT fusion (GDELT): all 12 tasks BUILT. Verification gate PARTIALLY complete (last checked 2026-07-26).**
Branch `phase-5-osint-fusion`, clean tree, all work committed and **pushed to origin**. **Two items remain, both
blocked on externals, neither on code. Read `HANDOVER-phase-5-live-gate.md` first — it is kept current in real time;
this section is a summary, not the source of truth.** Phase 6 (frontend arena, plan already written) does **not**
depend on either blocker — it renders whatever a `BriefRequest`/`BriefDraft` shape produces, so it can be built and
tested now against `FakeBriefGenerator`/seeded data and pointed at real briefs later at zero rework cost.

*Verified 2026-07-13, in-container:* `pytest -q` → **289 passed**; `ruff check .` → All checks passed;
`ruff format --check .` → 116 files already formatted; `alembic current` → **`0004 (head)`**;
`celery inspect registered` lists **`overwatch.fuse`**.

**Blocked (external, not code) — both re-diagnosed on 2026-07-26, see the handover's §0 for full evidence:**

1. **Articles cited in a validated brief (the SQL join proof) + the live stale flip** — needs a **funded** Console org,
   not just a key. The env passthrough is proven working (`5c44499`) and a key was created and tested end-to-end this
   session: it authenticated correctly and the API itself returned `400 "Your credit balance is too low"` — a real,
   informative response, not an auth failure. **The org genuinely has $0.00; no payment has ever landed.** Root cause,
   well-evidenced: the card is **RuPay** (routes internationally via Discover/Diners), and **RuPay generally does not
   support one-time international card-not-present transactions** — even with the international-transactions toggle
   on. Consistent with every observed symptom, including the Pro subscription (a *different*, recurring transaction
   type via Link) renewing fine on the same card while every one-time charge attempt gets OTP'd for a literal `$0.00`
   and never proceeds. **Fix: a Visa/Mastercard, any bank, for one ~$6 charge** — not necessarily the user's own card.
   A fresh Anthropic account with possible trial credit is a secondary option. Do not re-run the DNS/network/incognito
   diagnosis again — all exhausted this session, see the handover.
2. **Live GDELT fusion** — worse than previously recorded, not better. The 2026-07-13 handover called this a rate-limit
   problem; a 2026-07-14 retest found a clean `200 OK` returning **zero articles** for novo-progresso (an open bug, not
   rate-limiting). A 2026-07-25 retest — after **12 days of zero traffic from this IP** — got **`429` on the initial
   request and all three retries**. The retry policy (`585d27e`) worked exactly as designed (correct 15/30/60s backoff,
   zero rows written, job row untouched); the block itself is the news. **This IP is under a block lasting weeks, not
   seconds.** Next attempt must come from a genuinely different network (different ISP or a cloud VPS — not another
   Wi-Fi/hotspot on the same regional carrier), per the handover's §0.

Built: migration 0004 (`news_articles` — **deliberately no geometry column**; AOI toponym terms; `evidence_links.article_id`);
`overwatch.fusion` package (presets with spike-verified GDELT theme IDs, diacritic-folding matchers, the three-gate AND
scorer, syndication dedup, `GdeltDocProvider` + offline `FakeNewsProvider`); `db/news.py` replace-set persistence with
the stale-brief flip; and **validator Gate 4 — the observed/reported wall.**

**Two corrections made during execution, both caught by real data rather than review:**

1. **The temporal window (design decision 3) was wrong.** The approved after-scene-anchored 44-day band passed design
   review, then failed against reality: Novo Progresso's *actual* scene pair is `2023-07-30 → 2024-07-24`, putting the
   band at `2024-06-24…2024-08-07` — and **a live GDELT query over it returned ZERO articles.** All four demo articles
   are Aug–Sep 2023. The forest AOI, our best fusion story, would have shipped with no news section at all. Replaced
   with a **capped-interval** window (`start = max(before, after − max_lookback) − lead`), verified against all three
   real pairs — Vizhinjam's 1,460-day gap now yields ~14 months, not 4 years; the cap is the anti-vacuity guard.
   Design doc decision 3 rewritten. **Standing rule: derive test windows from real scene pairs, never hand-invent dates
   — hand-invented dates are what hid this bug.**
2. **A false green was caught.** A Docker build failed silently while the old image kept running, so the suite "passed"
   against stale code. Always confirm the container restarted on the new image before trusting a green run.

*Highlight:* the adversarial negative is already green as a unit test — **"Amazon Prime Day deals announced" fires the
toponym gate on "Amazon", and the three-gate AND rejects it anyway.**

## Previous phase
Phase 4 — Briefs + evidence chain: **implementation complete + reviewed; live gate pending user's Anthropic key** (2026-07-11). All 9 planned tasks built on branch `phase-4-briefs-evidence` following subagent-driven-development (fresh implementer → task review → fixes → final whole-branch review). Non-live gate GREEN (187 passed, ruff clean, alembic `0003 (head)`, `generate_brief` registered in worker). Whole-branch review (opus, `3e1097f`→`3835cd7`) returned **✅ Ready to merge** — the three-gate validator holds as a security boundary end-to-end. The only remaining work is the **live gate (Steps 2–5)**, which needs `OVERWATCH_ANTHROPIC_API_KEY` in `.env` — the user supplies it directly (never via chat / never committed). Full evidence in the plan's "Verification Gate — evidence" section.

Phase 3 merged to main via PR #7 (`3e1097f`, 2026-07-09); merge verified byte-identical to branch tip `5cf599d`, local main synced, stale branch deleted. CI on the merge commit not yet confirmed green — `gh` is installed (2.96.0) but needs `gh auth login` before it can query Actions.

## Last verified working
**DETECTION ACCURACY MEASURED — the project's first precision/recall numbers (2026-08-04).**
`PROJECT.md` §11 had flagged that every accuracy claim needed hand-labelled ground truth, so
none existed. OSCD (Onera Satellite Change Detection — the benchmark §7 already named) supplies
it without anyone hand-labelling: 24 Sentinel-2 pairs with human-drawn pixel-level change masks,
14 train / 10 held-out test. Run with
`docker compose exec -T api python -m overwatch.eval.run_oscd --split test`.

**Shipped `port` preset, untuned against the benchmark** (SSIM-only ≥0.55, min_area 5,000 m²):

| split | scenes | precision | recall | F1 | IoU |
|---|---|---|---|---|---|
| **test (held out)** | 10 | 0.345 | **0.526** | **0.417** | **0.263** |
| train | 14 | 0.185 | 0.514 | 0.272 | 0.158 |

**Threshold sweep, test split** — the shipped 0.55 is the **F1 maximum**:

| threshold | 0.40 | 0.45 | 0.50 | **0.55** | 0.60 | 0.65 | 0.70 |
|---|---|---|---|---|---|---|---|
| precision | 0.238 | 0.273 | 0.309 | **0.345** | 0.382 | 0.413 | 0.441 |
| recall | 0.725 | 0.662 | 0.594 | **0.526** | 0.449 | 0.377 | 0.307 |
| F1 | 0.359 | 0.387 | 0.406 | **0.417** | 0.413 | 0.394 | 0.362 |

- **What the numbers say:** recall is stable near **0.52 on both splits** while precision tracks how
  much change a scene actually contains — strong where change is common (montpellier F1 0.712,
  lasvegas 0.687, dubai 0.560) and poor below ~1% change (valencia 0.019, saclay_w 0.097, norcia
  0.074). The detector finds roughly half the labelled change and over-fires where change is rare.
  That is the honest characterisation, and it points at precision as the lever worth working on.
- **The 0.55 agreement is external validation, not fitting.** That threshold was set by eye on the
  Vizhinjam imagery (commit `6f9524f`, 2026-08-02) — before this dataset was downloaded — and lands
  on the F1 optimum of an independent 10-scene benchmark. Precision rises monotonically across the
  sweep and recall falls monotonically; the curve has no anomalies.
- ⚠️ **Scope of the claim: OSCD labels urban change, so this scores the construction preset only.**
  The vegetation (`forest`) and water (`flood`) presets have **no public benchmark and remain
  unmeasured** — they still need hand-labelled truth on their own AOIs. Do not generalise these
  figures to them.
- **Method:** the detector's *emitted polygons* are rasterised and scored, not its internal
  threshold mask, so the figure is what a consumer of `GET /aois/{slug}/detections` actually gets —
  morphology and the min-area floor included. Micro-average (pixels pooled across scenes).
- **Caveats on the comparison:** OSCD ships L1C top-of-atmosphere imagery where the pipeline
  normally reads L2A surface reflectance (the indices and SSIM are relative, so it holds, but the
  radiometry is not identical), and OSCD has no SCL plane, so no pixel is excluded as cloud.
- Built TDD as `overwatch.eval` (metrics / OSCD adapter / rasteriser / runner), **18 new tests**.
  Gate: **320 passed**, ruff check clean, ruff format 128 files. Commit `2398aa7`.

**LIVE LLM BRIEFS — Phase 4 live gate GREEN and Phase 5 item A GREEN (2026-08-04, over HTTP).**
The user funded a key ($0.79). All three AOIs now carry **real Anthropic-generated briefs**
(`model=claude-opus-4-8`), replacing the hand-authored `demo-seed` ones. Total spend **$0.306**
(measured from persisted `usage`, priced at $5/$25 per MTok):

| AOI | brief | attempts | input | output | cost |
|---|---|---|---|---|---|
| vizhinjam | 1255 | 2 | 4,674 | 1,589 | $0.063 |
| novo-progresso | 1256 | 3 | 12,600 | 3,544 | $0.152 |
| porto-alegre | 1257 | 2 | 8,834 | 1,875 | $0.091 |

- **Evidence chain proven end-to-end: 91 evidence links across the three briefs, 0 dangling.**
  Every `observed` claim's links resolve to detections in that brief's own `(aoi, before, after)`
  pair, and quoted areas match the stored geometry (vizhinjam: "833,100 m²" = the 83.3 ha total,
  "396,500 m²" = the 39.65 ha largest polygon).
- **The regeneration loop self-healed a real failure.** Vizhinjam attempt 1 wrote one claim quoting
  *two* areas while linking *both* detections, so Gate 3 compared each quote against the **sum**
  (613,700 m²) and rejected all five numbers with `area_mismatch`. Attempt 2 split them into
  one-detection-per-claim statements and validated. Novo-progresso needed all 3 attempts.
- **Gate 4 (observed/reported wall) held live.** Porto-alegre's brief carries two `reported` claims
  citing **7 real news articles with zero detection links**, framed as reported speech ("News
  outlets reported that…"). This is Phase 5's blocked item A — *articles cited in a validated
  brief, proven by the SQL join* — now **done**.

**REGENERATED ON SONNET 5 (2026-08-13)** after the detection fixes above changed every AOI's
numbers, making the Opus briefs factually stale. User approved a **$0.22 ceiling**, which Opus
could not meet (the same volume reprices to $0.306). Method: re-run detection first (free), probe
with the smallest brief, then extrapolate before committing. All three **validated, 0 dangling
links**; the Opus and `demo-seed` briefs are now `stale` (`replace_detections` demotes any brief
over that scene pair *before* deleting the evidence it cited, so nothing dangled at any point).

| AOI | brief | attempts | input | output | cost @ $3/$15 |
|---|---|---|---|---|---|
| vizhinjam | 1492 | 1 | 1,569 | 492 | $0.0121 |
| porto-alegre | 1493 | 1 | 3,676 | 4,076 | $0.0722 |
| novo-progresso | 1494 | 2 | 7,422 | 7,062 | $0.1282 |
| **total** | | | **12,667** | **11,630** | **$0.2125** (**$0.1416** at intro $2/$10) |

- **Sonnet 5 was cheaper than the token counts alone suggest**: it validated vizhinjam and
  porto-alegre in **one** attempt where Opus needed two, so the retry tax mostly vanished.
- **Gate 3 self-healed again, on the model that costs less.** Novo-progresso attempt 1 quoted
  1,637,100 m² against 1,480,000 m² of linked detections and quoted three individual clearing
  sizes against the *sum* of the three it linked; six `area_mismatch` violations, all rejected.
  Attempt 2 validated. The guard rail is model-independent, which is the point of putting the
  arithmetic in the validator rather than trusting the generator.
- **Set `OVERWATCH_ANTHROPIC_MODEL` to pick the model** — the default in `config.py` is still
  `claude-opus-4-8`, so the shipped briefs came from an env override, not a code change.

**Regenerated once more (2026-08-13, final)** after the flood revert and the port re-anchor moved
both AOIs' numbers again. porto-alegre (2 attempts, 8,206 in / 2,431 out, $0.0611) and vizhinjam
(2 attempts, 4,094 in / 1,397 out, $0.0332); novo-progresso untouched and still valid. **All three
validated, 0 dangling evidence links**, and porto-alegre's carries **4 article links** alongside 7
detection links — Gate 4's observed/reported wall holding on live data. Session total at standard
rates: $0.306 (Opus, superseded) + $0.2125 + $0.0943 = **$0.613** of the $0.79 funded.

*Live demo state:* porto-alegre 66 det / 1,932.7 ha · novo-progresso 88 / 163.7 ha ·
vizhinjam 16 / 78.9 ha, each with a validated Sonnet 5 brief whose every numeric claim
cross-checks against its own linked detections.
- ⚠️ **`seed_briefs` purges every brief for an AOI**, so re-running it would have destroyed the
  paid output. It now refuses when a validated non-`demo-seed` brief exists (`--force` overrides);
  verified live — all three skipped, real briefs survived.
- Gate after the change: **300 passed**, ruff check clean, ruff format 120 files.

**Flood / porto-alegre resolved (2026-08-03, in-container + over HTTP):**
Root cause was **not** detection tuning: porto-alegre had **0 job rows** — the flood detector had never
run on it. Scenes 17/18 (`S2A_22JDM_20240418` → `S2A_22JDM_20240521`, both usable ≈1.000) were ingested
2026-07-03 during the Phase-1 viability check and nothing followed. Diagnosed by running the real code
path on the pair before changing anything: open water **37.5% → 47.6%** of the window, NDWI delta p95
**+1.03**, newly-water 1,336 ha — the flood is unmistakable in the data, and the **shipped preset needed
no change**. Submitted a real job (`6e929e81`, windows 2024-04-17…19 / 2024-05-20…22): **succeeded, 75
detections**, reusing scene rows 17→18 with no duplicates.

**Then a real false positive, caught by eye and fixed (same day).** User review of the overlay found polygons
spanning water that was water in *both* scenes, bridging the channels between islands. Measured: **26% of
detected area (719.7 ha) sat on already-water pixels**, including a **251 ha polygon that was 100% water
beforehand**. Cause: NDWI-increase cannot separate "land became water" from "water got clearer" — turbid water
(~+0.14) to clear water (~+0.54) is a +0.40 delta on already-water pixels, double the 0.20 gate. Fixed with a
**was-NOT-water precondition** (`ndwi_before <= -0.05`), the flood analogue of forest's was-forest gate; TDD
red→green on a synthetic turbid→clear pair. Contamination **26.0% → 0.07%**; the 251 ha artefact gone; largest
polygon 672.3 → **474.9 ha at 0.00% already-water**.

Final persisted state: **66 polygons / 1,932.7 ha, largest 474.9 ha**, all typed `flooding`. Demo brief seeded
(1254, 4 claims, 72 citations). Gate: **300 passed**, ruff check clean, ruff format 120 files.

**Detection-quality iteration (2026-08-02, in-container + live browser at localhost:5180):**
`docker compose exec -T api python -m pytest -q` → **298 passed** (2 pre-existing third-party deprecation
warnings only); `ruff check .` → All checks passed; `ruff format --check .` → **120 files already formatted**.
Live over HTTP against the running stack: vizhinjam **22 detections / 83.3 ha / largest 39.7 ha**, novo-progresso
**88 / 163.7 ha / largest 18.4 ha**, porto-alegre **0** (flood still untuned); briefs 1143 (4 claims) and 1144
(3 claims) seeded and served. Port threshold confirmed visually by the user at 0.55.

**Phase 5 live gate — the half that needs no API key (2026-07-13, in-container + over HTTP):**

1. **The window correction, proven against real persisted rows.** Rebuilt novo-progresso's baseline from live
   Sentinel-2: the job succeeded in ~100 s with **24 detections** and reproduced the real pair **`2023-07-30 →
   2024-07-24`** exactly. Feeding those DB rows through `FusionWindow.around()`:
   - capped-interval window (**shipped**) → `2023-06-30 … 2024-08-07` → admits **4 / 4** demo articles;
   - after-scene-anchored window (**replaced**) → `2024-06-24 … 2024-08-07` → admits **0 / 4**.

   The forest AOI would have shipped with no news section at all under the formulation that passed design review.
2. **Kill-switch, live, both ways.** `OVERWATCH_FUSION_ENABLED=false` → `POST /aois/{slug}/fusion` returns **503
   `fusion_disabled`**, and it is checked *before* the AOI lookup (an unknown slug returns 503, not a leaked 404). With
   fusion back on, the same unknown slug correctly returns **404 `aoi_not_found`**. In the detection chain with the
   switch off, `overwatch.fuse` was invoked **0 times** — the chain ran `ingest_scene`×2 + `run_detection` only.
3. **GDELT's failure path, exercised for real.** The provider took a live `429` whose body is *plaintext*, parsed it
   without crashing, raised `TransientFusionError`, backed off 15 → 30 → 60 s, exhausted its retries, and failed the
   task **without touching the job row or writing a partial article set** (`fuse` is deliberately not a `JobTask`).
   That is the designed degradation: a GDELT outage costs a news section, nothing more.
4. **A real bug the fixtures could never catch** — see Known issues; fixed in `585d27e`.

Prior — Phase 4 non-live gate (2026-07-11, in-container, all `docker compose exec -T api …`): **`pytest -q` → 187 passed** (2 pre-existing third-party deprecation warnings only — Starlette/httpx TestClient + Alembic path_separator; not Phase-4 code); `ruff check .` → All checks passed; `ruff format --check .` → 98 files already formatted; `alembic current` → `0003 (head)`; `celery -A overwatch.workers.celery_app inspect registered` lists `overwatch.generate_brief`. Whole-branch review returned **✅ Ready to merge** with the validator security boundary confirmed across `prompt → generator → loop → validator → persist`. Secret hygiene: `git grep -iIn "sk-ant-api"` empty, no `.env` tracked. **Live LLM path (real Anthropic API) not yet run — pending user's key.**

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

- [~] **Phase 5 — OSINT fusion (GDELT): all 12 tasks built; live gate partially verified.** Branch `phase-5-osint-fusion`.
  *Verified 2026-07-13, in-container — 289 tests + ruff check + ruff format green; `alembic 0004 (head)`; `overwatch.fuse`
  registered on the live worker. Live evidence in "Last verified working".*
  1. Migration 0004 + ORM: `news_articles` (**deliberately no geometry column** — GDELT exposes no article geotag, and
     its geocoder is centroid-based; Gate 1 is a **toponym** gate, never a spatial one), AOI `place_terms`/`region_terms`,
     `evidence_links.article_id` + the two CHECK constraints that make a link structurally incapable of carrying the
     wrong foreign key.
  2. `overwatch.fusion` — presets (spike-verified GDELT theme IDs), diacritic-folding matchers, the **three-gate AND**
     scorer (toponym ∧ temporal ∧ thematic), syndication dedup, `GdeltDocProvider` + offline `FakeNewsProvider`.
  3. `db/news.py` — replace-set persistence keyed on `(aoi, after_scene)`, flipping dependent validated briefs to
     `stale` *before* deleting the articles they cite.
  4. **Validator Gate 4 — the observed/reported wall.** A claim backed only by journalism must be framed as reported
     speech, may carry no quantity, and `mixed` must cite both sides. Journalism never wears the clothes of sensing.
  5. Briefs read, prompt, and cite articles: a `SOURCES` block (capped, truncation logged) carrying the rules Gate 4
     enforces; `persist_validated` takes 4-tuples and writes an article `EvidenceLink` per citation.
  6. `fuse` Celery task + chain wiring + `FUSION_ENABLED` kill-switch; `POST /aois/{slug}/fusion` backfill endpoint.
  7. **PENDING (needs externals, not code):** articles cited in a *validated* brief (SQL join proof) + live stale flip
     → needs the Anthropic key. Live GDELT fusion → needs a cooled-off IP.

## In progress
- **Phase 5 verification gate — the two blocked items** (see Current phase). Both AOIs are now primed: vizhinjam and
  novo-progresso each have a succeeded job with a real scene pair, so the next session can fuse either immediately.
- Phase 4 **live verification gate** — same key, same unblock. Phase 5's live brief run subsumes most of it.

## Next up
- **Resolve Phase 5's two blockers** (see Current phase + `HANDOVER-phase-5-live-gate.md` §0 for full evidence):
  1. A Visa/Mastercard charge (any bank) to fund the Console org — RuPay appears unable to complete one-time
     international CNP charges. Once funded, Item A (SQL join proof + live stale flip) is a ~10-minute run.
  2. A live GDELT attempt from a genuinely different network (different ISP or a cloud VPS) — this IP has been
     blocked for ≥12 days as of 2026-07-26. **Do not retry from this network in the meantime.**
- **In parallel, start Phase 6 (frontend arena)** — `design-specs/2026-07-12-phase-6-frontend-arena-design.md` →
  `plans/2026-07-12-phase-6-frontend-arena.md` (9 tasks). Doesn't need either blocker: build and test against
  `FakeBriefGenerator`/seeded article data now, point at real briefs later at zero rework.
- Once both Phase 5 blockers clear: run the remaining live-gate proofs, then whole-branch review → merge
  `phase-5-osint-fusion` → main (branch already pushed to origin).
- `gh auth login` is still outstanding if CI status needs checking from the CLI (`gh run list --limit 3`).

## Open decisions
- ~~Exact GDELT endpoint/theme identifiers — deferred to the Phase 5 API spike.~~ **RESOLVED 2026-07-12 by the spike.**
  DOC 2.0 only (GEO 2.0 is a 404); theme identifiers verified against the live taxonomy; **Gate 1 is a toponym gate, not
  a spatial one** — GDELT exposes no geotag, and the GKG geofence was measured and rejects 100% of our true positives.
  Evidence in the Phase 5 design §2; gotcha in `CONTEXT.md`.
- ~~Preset thresholds/morphology are **engineering defaults, not tuned numbers** (design-spec §6 verbatim): port ssim_dissim≥0.35 ∧ ndvi≤−0.10, forest ndvi≤−0.20, flood ndwi≥0.20; min-areas 1,500/5,000/10,000 m²; open→close kernel 3px.~~ **RESOLVED 2026-08-02 — port and forest are now empirically tuned against the real pairs** (port: SSIM-only ≥0.55, 5,000 m²; forest: ndvi≤−0.15 ∧ ndvi_before≥0.50, 3,000 m²), with the visual confirmation and the completeness/precision tradeoff recorded above and in `CONTEXT.md`. **Flood is now tuned too** — the AOI's 0-detection state was a never-run job, not a threshold problem, but running it exposed a real one: NDWI-increase alone fires on water→clearer-water. Flood now carries a was-NOT-water precondition (`ndwi_before ≤ −0.05`) alongside `ndwi ≥ 0.20` / 10,000 m² → **66 detections / 1,932.7 ha**, already-water contamination 26.0% → 0.07%. All three presets are now empirically tuned against their real pairs.

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
- Phase 4/5: **compose never passed the Anthropic key into the containers.** `Settings(env_file=".env")` resolves `.env` against the CWD *inside* the container (`/app`), and compose mounts only `backend/src`, `backend/tests`, `backend/alembic`, `data` — so a repo-root `.env` never reached the app, and no service passed the variable through. Adding the key would have produced a 422 `briefs_unconfigured` that looks exactly like a bad key. Phase 4's live gate was never run, which is why this sat undiscovered. **Fixed** in `5c44499`; the passthrough is proven working (the same mechanism carried `OVERWATCH_FUSION_ENABLED=false` into the container during the kill-switch test).
- Phase 5: **the GDELT rate limiter never fired.** `GdeltDocProvider` kept its throttle clock in an *instance* attribute, but `get_news_provider()` builds a fresh provider per task run and Celery re-runs the whole task body on every retry — so each attempt started from a zeroed clock, computed a negative wait, and slept for nothing. Compounding it, `retry_jitter` draws the countdown uniformly from `[0, backoff]` and drew a literal **"Retry in 0s"**. The first live run fired three requests in 28 s at an API that documents one per five. Invisible to every test, because they all replay fixtures through `FakeNewsProvider` and the throttle had **zero coverage**. **Fixed** in `585d27e` (class-level clock + no jitter + 15/30/60 s backoff + Celery `rate_limit="10/m"`, which is the only limit that spans forked pool children). Two tests now pin it.
- Phase 5: **GDELT rate-limits by IP and stays angry.** After that burst, four spaced retries all took `429`, and a single cheap diagnostic query later got a **TLS handshake timeout** — the connection is dropped, not merely refused. Cooldown is well beyond the ~75 s observed during the spike. **Make exactly one call per attempt, and wait (hours) after any burst.** The client degrades correctly either way: both the plaintext `429` and `httpx.ConnectTimeout` map to `TransientFusionError`, retry, and then fail the task without touching the job row or writing partial articles.
