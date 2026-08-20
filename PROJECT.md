# PROJECT.md — Overwatch: Geospatial Change-Detection Intelligence Platform

> **Status:** Brainstormed & scoped (2026-07-02) — all `[BRAINSTORM]` tags resolved; design spec at `design-specs/2026-07-02-overwatch-mvp-design.md`
> **Owner:** Yash
> **Purpose of this file:** Shared, *non-rigid* starting point for Claude Code sessions. Defines the WHAT and WHY, sketches the HOW; open decisions were resolved in the 2026-07-02 brainstorm (see design spec). Everything here is a strong default, not a contract. When a decision changes, update this file — it is the single source of truth.
> **Build priority:** This is now project #3, built BEFORE Coup (whose PROJECT.md is complete and parked). This is intended to be the flagship — the "best project yet." Budget and scope accordingly.

---

## 0. One-Paragraph Pitch

A platform that watches the Earth for you. Users define areas of interest (AOIs) anywhere on the planet; Overwatch automatically pulls free Sentinel-2 satellite imagery on a schedule, detects meaningful change over time, stores detections as queryable geospatial events, and generates analyst-grade intelligence briefs where **every claim links to the exact pixels and dates that support it**. The current demonstrated verticals are port construction and flooding. Forest-loss monitoring was closed as a research extension in August 2026 after a five-window PRODES baseline (precision **0.216**, recall **0.384**, F1 **0.277**, IoU **0.161**) showed two-date optical imagery cannot reliably separate permanent clearing from harvest and seasonal vegetation change across locations.

---

## 1. Why This Project (Strategic Context)

Project #3 alongside **AgentProof** (AI eval/observability) and **Risk-Copilot** (applied credit-risk ML). Its job is **range**: it adds a genuinely new technical domain (geospatial engineering — raster pipelines, PostGIS, coordinate systems), a new buyer universe (defense/gov-tech, supply chain, insurance, ESG), and the portfolio's most shareable demo. The resulting trio reads as *eval infrastructure + applied ML with business ROI + geospatial intelligence systems* — three distinct competences.

**Positioning: neutral multi-domain platform** (decided). Not framed as a defense tool or an insurance tool — framed as a general change-intelligence engine *demonstrated through* multiple verticals. The multi-vertical demo IS the pitch: one engine, many buyers.

**Primary hiring targets & signal sent:**
- **Defense/gov-tech (Palantir/Anduril-tier, Dubai/Singapore gov):** geospatial + fusion + analyst workflow is their stack. Defense AI is procurement-driven and heavily funded right now.
- **BCG X / QuantumBlack / consulting:** supply-chain risk monitoring is a live client deliverable; supply-chain categories appear in YC's current RFS.
- **Insurance / ESG (London, Singapore):** catastrophe assessment, deforestation monitoring — regulated, monied problems.
- **YC-tier startups:** maps + change detection is the most visceral demo in the portfolio; startup-plausible as a seed MVP.

**The interview-defensible core:** the **evidence chain**. Every sentence in a generated brief traces to specific detections → specific image pairs → specific dates and pixels. The LLM narrates; deterministic geospatial analysis decides. This is the same "LLM proposes, deterministic evidence disposes" trust architecture as AgentProof's methodology — the portfolio thesis (verifiable AI systems) carries through even in a new domain.

---

## 2. Scope Decisions Already Made (do not re-litigate without cause)

1. **Neutral multi-domain platform** — showcase via 2 demonstrated AOI verticals (port, flood), forest kept as a research extension, engine stays generic.
2. **Classical change detection for MVP** (band math + differencing + SSIM), **deep-learning segmentation as a planned extension**. Rationale: classical is fast to ship, fully explainable (each detection has a mathematical reason), and interview-defensible; DL without labeled data and evaluation rigor is a liability. The upgrade path is itself a good story ("I shipped explainable detection first, then benchmarked a learned model against it").
3. **Docker/WSL2 from day zero.** GDAL/rasterio on native Windows is a known tarpit. The entire dev environment lives in containers; `C:\dev\` project root convention applies to the repo, execution happens in Docker.
4. **Free data only for MVP.** Sentinel-2 (10m resolution, ~5-day revisit) via a free API (§4). No paid imagery. Cost ceiling for the whole project ≈ LLM API usage only.

---

## 3. OSINT Fusion — DECIDED: IN MVP, constrained (2026-07-02; gates amended 2026-07-12 post-spike)

v0.1 includes the news/OSINT correlation layer, under these constraints:

- **One source: GDELT** (free). Direct API, no MCP. ~~Natively geotagged via GKG~~ — **the spike disproved this**; see the gate note below.
- **Persisted correlation, not correlate-at-brief-time:** fusion is its own Celery task downstream of detection — query GDELT → deterministic relevance scorer → persist passing articles + correlation rows in PostGIS. The brief generator only ever reads stored, verified rows (same trust pattern as detections). Reproducible, independently testable, and a GDELT outage can't break brief generation. **(Unchanged.)**
- **Three-gate AND scorer (conservative by construction):** **toponym** AND **temporal** (article date within −30 d/+14 d of the **after-scene** capture) AND **thematic** (per-vertical GDELT theme/keyword allowlist). Fail any gate → no citation. Zero matches → the brief simply has no news section. Better to cite nothing than cite garbage. **(Architecture unchanged: still three gates, still AND, still conservative. Two gates were redefined — see below.)**
- **Observed vs. reported:** claims backed only by articles must use reported-speech framing ("regional news reports…") and may carry **no quantities**; the brief validator enforces it (§4). **(Unchanged — and now the load-bearing part of the trust story.)**
- **Kill-switch:** fusion sits behind a config flag; if correlation quality disappoints, the demo ships imagery-only with citation slots intact. **(Unchanged.)**
- **Spike first:** ✅ **DONE 2026-07-12.** It changed two gates — exactly what a spike is for.

> ### ⚠️ Gate amendments from the spike (2026-07-12)
> **Authority:** `design-specs/2026-07-12-phase-5-osint-fusion-design.md` §2 supersedes this section and design-spec §3.2 where they differ.
>
> **1. Gate 1 is a TOPONYM gate, not a spatial one.** The original *"article geotag within AOI buffered 25 km"* **cannot be built and would not work if it could.** GDELT's DOC 2.0 returns **no coordinates** and has no location operator; GEO 2.0 is 404 on every form. And the underlying geocoder is documented by GDELT itself as **centroid-based**: *"every reference to Paris, France will always yield precisely the same coordinate."* News geocoding resolves a place *mention* to that place's **centroid** — but our AOIs are **sub-place polygons** (Novo Progresso is a ~38,000 km² municipality; our AOI is ~60 km²). We measured it: a 25 km geofence **rejects 100% of our true positives**. This holds via *any* transport — REST, GeoJSON, CSV, or BigQuery/GGG — because they are all the same geocoder.
>
> **2. The temporal gate anchors on the after-scene.** The original window spanned the whole before→after scene gap, which for Vizhinjam is ~3 years — a "gate" that accepts nearly everything. Now a ~44-day band around the observation.
>
> **Net effect on the trust architecture: none.** It never rested on geofence tightness. It rests on the **observed/reported wall** — journalism is not sensing, and the validator forbids an article-backed claim from carrying a quantity or observational framing. That wall is unchanged and now does more of the work, which is where the burden always belonged.

---

## 4. Architecture Overview

**Design principle:** deterministic geospatial pipeline is the trust anchor; the agent layer sits ON TOP and only ever narrates/plans against stored, verifiable detections. No LLM in the detection path.

```
┌──────────────────────────────────────────────────────────────────┐
│                    FRONTEND (React + Vite + MapLibre GL)           │
│  AOI drawing · before/after slider · detection overlays ·          │
│  brief viewer with click-to-evidence                                │
└───────────────▲──────────────────────────────────────────────────┘
                │ REST + (optional) WebSocket for job progress
┌───────────────┼──────────────────────────────────────────────────┐
│            BACKEND (FastAPI)                                        │
│                                                                     │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ AOI/Job API │  │ Scheduler        │  │ Brief Generator        │  │
│  │             │  │ (Celery beat)    │  │ (LLM, evidence-linked) │  │
│  └──────┬──────┘  └───────┬──────────┘  └──────────▲────────────┘  │
│         │                 │                         │               │
│         ▼                 ▼                         │               │
│  ┌──────────────────────────────────────┐          │               │
│  │        INGESTION WORKERS (Celery)     │          │               │
│  │  STAC search → COG windowed reads →   │          │               │
│  │  cloud masking (SCL) → co-registration│          │               │
│  └──────────────────┬───────────────────┘          │               │
│                     ▼                               │               │
│  ┌──────────────────────────────────────┐          │               │
│  │      CHANGE DETECTION ENGINE          │          │               │
│  │  (pure, deterministic, unit-tested)   │          │               │
│  │  band math: NDVI/NDWI/NBR deltas ·    │          │               │
│  │  image differencing · SSIM ·          │          │               │
│  │  thresholding → polygonization        │          │               │
│  └──────────────────┬───────────────────┘          │               │
│                     ▼                               │               │
│  ┌──────────────────────────────────────┐          │               │
│  │   POSTGIS (detections as geo events)  │──────────┘               │
│  │   AOIs · scenes · detections ·        │                          │
│  │   briefs · evidence links             │                          │
│  └──────────────────────────────────────┘                          │
│         Redis (Celery broker + job state)                           │
└──────────────────────────────────────────────────────────────────┘
        │
        ▼ external (free)
  Earth Search STAC API (Sentinel-2 L2A COGs on AWS) · GDELT (news fusion)
  Anthropic API (brief generation only)
```

### Component responsibilities
- **Ingestion workers (Celery):** given an AOI + date range, query the STAC catalog for Sentinel-2 L2A scenes, **stream only the AOI's pixel window from Cloud-Optimized GeoTIFFs (COGs)** — never download full ~1GB scenes — apply cloud masking via the SCL (scene classification) band, reproject/co-register image pairs, persist normalized rasters/metadata.
- **Change Detection Engine:** pure functions, no I/O, no LLM. Input: two co-registered, cloud-masked rasters. Output: typed `Detection` objects (geometry polygon, change type heuristic, magnitude, confidence, contributing indices). Band math (NDVI for vegetation, NDWI for water, NBR for burn), normalized differencing, SSIM for structural change, threshold → morphological cleanup → polygonization. **This module is the TDD target** — deterministic math with synthetic-raster fixtures.
- **PostGIS:** AOIs, scene metadata, detections (as geometries), briefs, and the **evidence-link table** (brief_claim → detection_ids → scene_ids). Spatial indexes; queries like "all detections intersecting this polygon since March."
- **Brief Generator:** LLM receives structured detections (not pixels) and writes the analyst brief via structured output (SDK-validated Pydantic claims — no prose parsing). **Hard rule: every observed claim must carry evidence-link IDs that resolve to the exact scene pair; the post-generation validator also checks the numbers — quoted areas must match linked detections within ±10% and dates must match the pair — and rejects quantities smuggled into context claims; claims backed only by news articles (not detections) must use reported-speech framing (Phase 5).** This validator is the anti-hallucination gate and a first-class feature.
- **Fusion Correlator (Celery):** post-detection task — GDELT query for the AOI's region and window → three-gate relevance scorer (§3) → persist `news_articles` + correlation rows. Deterministic and unit-tested; the LLM never fetches news.
- **Scheduler:** Celery beat re-checks AOIs on a cadence (e.g., weekly) for new imagery → new detection runs. No alerting in v0.1 (extension, §8).
- **Frontend:** MapLibre GL (free, no token) + deck.gl overlays. AOI drawing tool, timeline of scenes, before/after slider, detection polygons, brief panel where clicking a sentence highlights its evidence on the map. The click-to-evidence interaction is the demo's signature moment.

### Stack summary
| Layer | Choice | Why (interview-defensible) |
|---|---|---|
| Imagery source | **Earth Search STAC API** (Sentinel-2 L2A COGs, AWS Open Data) | Free, no auth for search, COGs enable windowed reads — you process megabytes, not gigabytes. Fallback: Copernicus Data Space behind the `ImageryProvider` interface. **Confirmed 2026-07-02.** |
| Raster processing | **rasterio + numpy (+ GDAL under the hood)** | Industry standard; windowed COG reads are the key cost/perf trick. |
| Geo storage | **PostGIS on Postgres** | Spatial indexes, geometry ops, "intersects/within/since" queries impossible in vanilla Postgres. Your Postgres skills carry over. |
| Jobs | **Celery + Redis** | Imagery pulls are slow/bursty; scheduling + retries + progress state. New to your stack — deliberate, valuable signal. |
| API | **FastAPI** | Your stack; async fits job orchestration. |
| Brief LLM | **Anthropic API** | Narration only, never detection. |
| News fusion | **GDELT DOC 2.0** (spike-verified 2026-07-12) | Free, no key. **Not geotagged** — DOC returns no coordinates and GEO 2.0 is 404 (§3). Correlation gates on toponym/temporal/theme. Direct API, no MCP. |
| Frontend | **React + Vite + MapLibre GL + deck.gl** | Free map stack, no API keys; deck.gl for performant polygon overlays. |
| Packaging | **Docker Compose** (api, worker, beat, postgis, redis, frontend) | One-command spin-up; mandatory on Windows (GDAL). |
| Deps | **pyproject.toml** single source | Your convention. |

Resolved defaults (2026-07-02): Earth Search STAC confirmed; AOI size cap **500 km²** (≈5 MP per band at 10 m — laptop-viable windowed reads); detection thresholds live in **per-vertical preset configs** (§6a for numbers); **no alerting** in v0.1 (extension); **REST polling** for job progress (WebSocket deferred).

---

## 5. The Three Showcase AOIs (multi-domain demo set) — SELECTED 2026-07-02

Real, well-documented sites where change is publicly known (detections verifiable against ground truth):
1. **Port / supply chain — Vizhinjam International Seaport, Kerala, India.** Breakwater + terminal construction 2020–2024; first vessel July 2024, commissioned Dec 2024. Image pairs from clear Dec–Apr windows across 2021–2025 (monsoon Jun–Sep is excluded by the cloud gate anyway).
2. **Environment / ESG — Novo Progresso (BR-163 corridor), Pará, Brazil.** One of the most active, best-documented deforestation frontiers; INPE PRODES/DETER provide public ground truth. Dry-season pairs (Jun–Sep), consecutive years; NDVI delta on clearings is the textbook case.
3. **Disaster / insurance — Porto Alegre, Brazil (Rio Grande do Sul floods, May 2024).** Weeks-long Guaíba river inundation → clear post-event scenes findable despite storm-season cloud. Pre-flood April 2024 vs. early-to-mid May 2024; NDWI delta is dramatic.

Criteria applied: change visible at 10 m; workable clear-sky windows; publicly reported ground truth. Final confirmation that clean scene pairs exist happens empirically in Phase 1 — if a site disappoints, swap it (fallback candidates ranked in the design spec: Tuna Tekra/Kandla, Rondônia, Valencia Oct 2024).

---

## 6. Self-Healing / Correction — both senses, per portfolio convention

### 6a. Runtime robustness (the domain demands it) — v0.1 scope
Satellite pipelines fail in predictable ways; handling them is core competence, not polish:
- **Cloud cover:** SCL-based masking per scene; if usable-pixel fraction < threshold, skip the scene and log why; widen the date search window automatically to find the next clear scene.
- **No-data/partial tiles, AOIs straddling scene boundaries:** detect, mosaic or reject explicitly — never silently produce garbage rasters.
- **Co-registration sanity checks** before differencing (misaligned pairs produce spectacular false change — validate, don't assume).
- **Job failures:** Celery retries with backoff; jobs are idempotent (re-running an ingestion never duplicates scenes/detections — enforce with natural keys).
- **Brief validator** (§4): rejects LLM briefs containing claims without evidence links; regeneration with feedback, bounded retries.

Resolved defaults (starting points — tuned empirically in Phase 2, all in per-vertical preset configs): usable-pixel fraction **≥ 70%** after SCL masking; auto-widen the scene search window in **+15-day steps, capped at +60 days**; minimum detection area — port **1,500 m²**, deforestation **5,000 m²** (0.5 ha), flood **10,000 m²** (1 ha); morphological open→close before polygonization.

### 6b. Development-time self-healing — same discipline as Coup/AgentProof
- **`PROGRESS.md`** — same convention as the Coup file: phase, last-verified-working, built-and-verified with verification notes, next up, open decisions. Nothing is "done" without a verification note.
- **`CONTEXT.md`** — domain glossary, maintained via `domain-modeling`. Captures exactly the kind of fact that otherwise gets rediscovered per phase (Sentinel-2 baseline offsets, precondition rules, CRS gotchas).
- **TDD on the Change Detection Engine** — it's pure math on arrays: synthetic-raster fixtures (inject a known "new building" into a synthetic image pair; assert the polygon comes out). Use the `test-driven-development` skill. This is the ideal TDD target in the whole project.
- **Typed interfaces** — Pydantic v2 models for `AOI`, `Scene`, `Detection`, `Brief`, `EvidenceLink`; breakage surfaces at boundaries.
- **Small modules behind interfaces** — `ImageryProvider` (STAC today, swappable), `ChangeDetector` (classical today, DL later — this interface is what makes the DL extension additive), `BriefGenerator`.
- **Verification gates** — `verification-before-completion` skill before any phase is marked done; CI green from Phase 0.
- **Additive-changes-only convention applies** — no renaming of columns/constants without explicit approval.

---

## 7. Deep-Learning Extension (planned, NOT MVP)

The `ChangeDetector` interface makes this a drop-in: train/fine-tune a change-segmentation model (e.g., a Siamese U-Net on the **OSCD — Onera Satellite Change Detection — dataset**, the standard public benchmark for Sentinel-2 change detection), then **benchmark it against the classical detector on the same AOIs** with precision/recall against hand-labeled ground truth. The comparison itself is the resume line — "replaced heuristic detection with a learned model and measured the improvement" is a far stronger story than "used a neural net." PyTorch (existing stack). Deferred — post-MVP; brainstorm when picked up.

---

## 8. Extensions (post-MVP, rough value-to-effort order)

1. **DL change segmentation + classical-vs-learned benchmark** (§7).
2. **Alerting** — email/webhook when a new detection exceeds severity threshold ("monitoring" becomes real).
3. **Sentinel-1 SAR support** — radar sees through clouds; adding it solves the cloud problem structurally and is a serious remote-sensing credential.
4. **Natural-language AOI tasking** — "watch this port and tell me if activity increases" → agent translates to AOI + cadence + detection config.
5. **Multi-AOI portfolio dashboard** — fleet view across all monitored sites (the "enterprise console" story).
6. **Detection time-series analytics** — change velocity/trends per AOI, not just events.

(OSINT/GDELT fusion moved into the MVP — §3.)

---

## 9. Build Phases (backend-first; thin real UI early)

- **Phase 0 — Scaffold.** Repo, Docker Compose (api/worker/beat/postgis/redis/frontend stubs), pyproject.toml, CI green, `PROGRESS.md`, this file committed. Verify: `docker compose up` works end-to-end on the Windows machine; rasterio imports inside the container.
- **Phase 1 — Imagery ingestion.** STAC search for a hardcoded AOI; windowed COG read of just the AOI; SCL cloud masking; persist scene + raster metadata to PostGIS. Verify: pull two clear scenes of AOI #1 spanning a known change, render them as PNGs, eyeball them.
- **Phase 2 — Change Detection Engine (TDD).** Pure module: band indices, differencing, SSIM, threshold → polygons. Synthetic-fixture tests first, then run on the Phase-1 real pair. Verify: known real-world change is detected; synthetic tests green.
- **Phase 3 — Detection persistence + API.** Detections into PostGIS with spatial indexes; AOI CRUD; job endpoints; Celery wiring end-to-end (submit AOI → ingestion → detection → stored events). Verify: full pipeline from API call to queryable detections, idempotent on re-run.
- **Phase 4 — Briefs + evidence chain.** Brief generator with evidence-link enforcement + validator. Verify: generated brief for AOI #1; every claim's links resolve; validator demonstrably rejects an unlinked claim (test this negatively).
- **Phase 5 — OSINT fusion (GDELT).** API spike first (verify DOC/GEO 2.0 surface and theme taxonomy against real queries); TDD the three-gate relevance scorer (pure function); Celery fusion task; validator extension for observed-vs-reported framing. Verify: correlated articles for at least one AOI pass the gates and appear cited in a regenerated brief; a deliberately irrelevant article is demonstrably rejected; kill-switch flag tested both ways.
- **Phase 6 — Frontend arena.** MapLibre app: AOI draw, before/after slider, detection overlays, brief panel with click-to-evidence (detections highlight on map; article citations open the source). Verify: the <2-minute demo works for all three showcase AOIs.
- **Phase 7 — Polish.** README with demo GIF, the two showcase AOIs pre-loaded, one-command spin-up, resume bullet finalized against reality.

---

## 10. Skills & MCPs to use

**Claude Code skills (from the available set):**
- `superpowers:brainstorming` — DONE (2026-07-02). All tags resolved; outcomes in `design-specs/2026-07-02-overwatch-mvp-design.md`.
- `test-driven-development` / `context-mode:tdd` — the Change Detection Engine (Phase 2) is the ideal target.
- `superpowers:writing-plans` → `superpowers:executing-plans` — brainstorm → phased plan → execution with checkpoints.
- `verification-before-completion` — gate every phase (backbone of dev-time self-healing).
- **`diagnosing-bugs`** — for domain-data bugs specifically: anything that only surfaces against real Sentinel-2/GDELT data rather than synthetic fixtures (the BOA-offset and forest-precondition bugs were both this kind). Leads with building a tight, real-data feedback loop before hypothesizing.
- **`systematic-debugging`** — for everything else (CRS mismatches, masking errors, ordinary logic bugs reproducible from a fixture).
- `superpowers:using-git-worktrees` — isolate the DL-extension work later.
- **`domain-modeling`** — maintain `CONTEXT.md` (now created) continuously: every domain fact discovered from a real-data bug (band offsets, precondition rules, CRS gotchas) goes there, not just into the fix commit message.
- **`resolving-merge-conflicts`** — for in-progress merge/rebase conflicts. Prefer `gh pr merge` over merging through the GitHub web UI — a web-UI merge already caused one accidental "revert PR" incident (PROGRESS.md, 2026-07-03) that needed manual cleanup.
- After each merge, delete the local feature branch (`git branch -d`) — two Phase 2 branches sat around locally for a full phase after merging before this was caught.
- `frontend-design` — the map UI should read as intentional; this is the flagship's face.

**MCPs / external services:**
- **GitHub** — repo, CI, issues per phase.
- **Imagery via direct STAC/HTTP APIs** — no MCP needed; don't add MCPs for their own sake (same call as Coup).
- **GDELT via direct API, not an MCP** (fusion is in MVP, §3).

**API keys/env:** Anthropic key only (briefs). Earth Search requires none. All via env, never hardcoded.

---

## 11. Resume Bullet (draft — every number must be verified against reality before submission)

> *"Built a geospatial change-detection platform (FastAPI, Celery, PostGIS, rasterio, React/MapLibre) that monitors user-defined areas of interest via Sentinel-2 imagery with automated cloud-masked classical change detection, stores detections as queryable geospatial events, correlates them with GDELT news through a deterministic three-gate filter, and generates evidence-linked intelligence briefs in which every claim traces to specific detections, scenes, dates, or cited articles — demonstrated on port-construction and flood-change workflows."*

> **Why "geotagged GDELT news" was removed (2026-07-12):** it would be a false claim. GDELT's DOC 2.0 returns no
> coordinates, and its geocoder is centroid-based by design — we measured a 25 km geofence rejecting 100% of our true
> positives (§3). Under §11's own discipline, **every word on the resume must be empirically true**, so the bullet now
> says what the system actually does: a deterministic three-gate filter (toponym ∧ temporal ∧ thematic). The
> evidence-chain claim — the interview-defensible core — is untouched and remains exactly as strong.

**Claims requiring empirical verification before going on paper** (AgentProof discipline):
- ~~Any detection accuracy/precision figure — requires hand-labeled ground truth on the showcase AOIs.~~
  **MEASURED for the demonstrated construction and flood workflows, with different scope boundaries:**
  construction against OSCD (2026-08-04) and flood against one date-matched EMSN194 case
  (2026-08-15). These results are not interchangeable or evidence of one global detector accuracy
  figure. Forest was evaluated against a five-window PRODES baseline and closed as a research extension (2026-08-19), not a demonstrated production capability.
- **Construction (`port`):** against OSCD (§7's benchmark), **precision 0.325, recall 0.280, F1
  0.301, IoU 0.177** on the 10-scene held-out test split, measured on the preset as shipped
  (spatial prior included) and untuned against the benchmark. Sayable on paper, with its scope
  attached:
  - ⚠️ **Figures restated 2026-08-21.** The previously published 0.345/0.526/0.417/0.263 described
    the preset *before* `focus_radius_m=2000` was added on 2026-08-13 and are retired. See
    `PROGRESS.md` § "OSCD figures corrected (2026-08-21)". Do not reuse them from an older draft.
  - **It covers the construction (`port`) preset only** — OSCD labels urban change. No figure may
    be implied for the forest or flood presets from this result.
  - Report **both splits**. Test 0.325/0.280/0.301/0.177 over 10 scenes; train 0.189/0.271/0.222/0.125
    over 14. Omitting either would be cherry-picking.
  - Supporting detail worth having ready for an interviewer: recall holds within 0.01 across the two
    splits (0.280 / 0.271) while precision follows the scene's change rate (0.325 / 0.189), and a
    threshold sweep puts the shipped 0.55 at the F1 maximum — a value set on Vizhinjam imagery
    eleven days before the dataset was downloaded. Evidence and per-scene tables in `PROGRESS.md`;
    harness in `overwatch.eval`.
  - Give the two limits separately rather than leading with one number. Precision **0.325** is the
    specificity limit of generic SSIM structural change: it also responds to non-target roads,
    roofs, bare soil, shadows, seasonal appearance, and other urban restructuring. Recall **0.280**
    is a scope limit deliberately imposed by the 2 km spatial prior, which is correct for a
    single-subject port AOI and wrong for a whole-city benchmark. Neither is a cloud-quality
    failure.
- **Flood:** one date-matched Porto Alegre case against Copernicus EMSN194 scored **precision
  0.586, recall 0.605, F1 0.595, IoU 0.424**. This is evidence for that one event, footprint, and
  observation date, not a general flood estimate.
  - ⚠️ **Always attach the independence caveat**, which the result file itself records
    (`benchmarks/results/emsn194-porto-alegre-2024-05-08.json`, `caveats[1]`): CEMS produced the
    analyst-reviewed extent from same-day Sentinel-2 plus radar, so the truth is authoritative but
    **not fully independent** of the optical acquisition being scored. Volunteer this before a
    reviewer asks — it is the first question the result invites.
- **Forest:** retain the PRODES five-window result as internal negative evidence rather than a
  production accuracy claim. The unchanged preset scored **precision 0.216, recall 0.384, F1 0.277,
  IoU 0.161** and showed severe location dependence; Novo Progresso scored precision **0.0110**.
  The failure is systematic (two-date optical cannot separate clearing from harvest/seasonal
  change), so the retained holdout gate was retired rather than run. Describe forest monitoring as
  future work requiring multi-temporal, seasonal, and stronger spectral (SWIR/NBR/NDMI) evidence.
- Any latency/throughput number (e.g., "AOI-to-brief in under N minutes") — **still unmeasured.**
- Scene/AOI counts — must reflect actually-processed volumes.

---

## 12. Interview Defensibility — the probes to pre-empt

- **"Why classical over deep learning?"** — Explainability (every detection has a mathematical cause), no labeled-data dependency, shippable and testable; DL is the benchmarked extension, not the default. Know the OSCD dataset and the Siamese U-Net upgrade path cold.
- **"How do you handle clouds?"** — SCL masking, usable-pixel thresholds, auto-widened date windows; Sentinel-1 SAR as the structural fix (extension). Never claim clouds are solved.
- **"What's a CRS and why do you care?"** — Reprojection/co-registration before differencing; misalignment = false change. Be able to explain UTM zones vs. EPSG:4326 and why you compute in projected coordinates.
- **"Why PostGIS?"** — Spatial indexing (GiST), geometry predicates (intersects/within), and the evidence-chain joins; recursive point-in-polygon in app code is the amateur tell.
- **"How do you stop the LLM hallucinating in briefs?"** — It never sees pixels, only structured detections; the validator checks the numbers, not just the links (linkage to the exact pair, quoted areas ±10% of linked rows, dates matching the pair, no quantities in context claims); regeneration is bounded and rejections are surfaced with violations. The brief is narration over verified events, and you can prove it in the demo by clicking any sentence.
- **"How do you avoid embarrassing false news links?"** — Three-gate AND scorer (spatial/temporal/thematic), cite-nothing-over-garbage default, observed-vs-reported framing enforced by the validator, kill-switch flag if quality disappoints. The LLM never fetches or selects news — it narrates over pre-correlated, persisted rows.
- **"Why stream COG windows instead of downloading scenes?"** — ~1GB/scene vs. megabytes per AOI window; this is the difference between a laptop-viable pipeline and one that isn't. Knowing this trick signals real remote-sensing literacy.

---

## 13. How to use this file with Claude Code

1. Brainstorm complete (2026-07-02): fusion IN, constrained (§3); Earth Search confirmed (§4); AOIs selected (§5); robustness and pipeline defaults resolved (§4, §6a). Full rationale in `design-specs/2026-07-02-overwatch-mvp-design.md`.
2. This file is updated; all `[BRAINSTORM]` tags deleted.
3. `superpowers:writing-plans` → phased plan → `superpowers:executing-plans` with verification gates per phase.
4. Keep `PROGRESS.md` and `CONTEXT.md` current every session (same convention as the Coup file).
5. Nothing here is rigid — but scope discipline is: the MVP is §9 Phases 0–7. Extensions wait. The flagship fails only one way: staying unfinished.
