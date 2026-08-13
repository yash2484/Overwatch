# Overwatch MVP — Design Spec

> **Date:** 2026-07-02
> **Status:** Approved (brainstorm session, user-confirmed decisions)
> **Owner:** Yash
> **Relationship to PROJECT.md:** PROJECT.md is the strategic scaffold and single source of truth for scope; this spec records the brainstorm-resolved decisions, the fusion-layer design (the one component the brainstorm materially changed), the data model, and the concrete engineering defaults. On conflict, this spec wins for design detail; PROJECT.md wins for scope and strategy.

---

## 1. Decisions Resolved (2026-07-02 brainstorm)

| Decision | Outcome | Decided by |
|---|---|---|
| OSINT/news fusion | **IN the MVP**, constrained (GDELT only, three-gate scorer, kill-switch) | User |
| Port AOI | **Vizhinjam International Seaport, Kerala, India** | User |
| Deforestation AOI | **Novo Progresso (BR-163 corridor), Pará, Brazil** | User |
| Flood AOI | **Porto Alegre, Brazil — Rio Grande do Sul floods, May 2024** | User |
| STAC provider | **Earth Search** (Sentinel-2 L2A COGs, AWS Open Data); Copernicus Data Space as fallback behind `ImageryProvider` | Default, user-visible |
| Job progress transport | **REST polling** (2s interval); WebSocket deferred | Default, user-visible |
| Alerting | **None in v0.1** — extension #2 in PROJECT.md §8 | Default, user-visible |
| Detection/robustness thresholds | Engineering defaults per vertical (§6 below), tuned empirically in Phase 2 | Engineering default |

---

## 2. Architecture Summary

Unchanged from PROJECT.md §4 except for the fusion addition. The trust architecture is the through-line:

> **Deterministic pipeline decides; the LLM only narrates over stored, verified rows.** No LLM in the detection path, and now also: no LLM in the news-correlation path.

Components: FastAPI backend · Celery workers (ingestion, detection, **fusion**) + Celery beat scheduler · PostGIS · Redis · React + Vite + MapLibre GL + deck.gl frontend · Anthropic API (brief narration only) · Earth Search STAC + GDELT (external, free).

Docker Compose services: `api`, `worker`, `beat`, `postgis`, `redis`, `frontend`. Everything runs in containers (GDAL on native Windows is a known tarpit).

---

## 3. Fusion Layer Design (new in this spec)

### 3.1 Approaches considered

- **A — Correlate at brief time:** brief generator queries GDELT live during generation. Least code, but non-reproducible (regenerating a brief cites different articles), correlation logic hides inside the LLM step where it can't be unit-tested, and a GDELT outage breaks brief generation. **Rejected.**
- **B — Persisted correlation (chosen):** fusion is its own Celery task, downstream of detection. Query GDELT for the AOI's region and detection window → deterministic relevance scorer → persist passing articles and correlation rows in PostGIS. The brief generator reads only from the database, exactly as it reads detections. Reproducible, independently testable, outage-isolated.

### 3.2 The three-gate relevance scorer

Pure function, no I/O — the project's second TDD target after the detection engine. A candidate article passes only if **all three** gates pass (AND, not a weighted score — conservative by construction):

1. ~~**Spatial:** article geotag (GDELT GKG geocoding) falls within the AOI geometry buffered by **25 km**.~~
   > 🚫 **SUPERSEDED 2026-07-12 — DO NOT BUILD THIS.** There is no article geotag: GDELT DOC 2.0 returns no coordinates
   > and has no location operator, and GEO 2.0 404s on every form. The geocoder behind GKG/GEO/BigQuery-GGG is
   > **centroid-based by GDELT's own documentation** (*"every reference to Paris, France will always yield precisely the
   > same coordinate"*), so it resolves a place *mention* to that place's centroid — while our AOIs are sub-place
   > polygons. Measured: a 25 km geofence **rejects 100% of our true positives**.
   > **Replacement: a toponym gate.** See `design-specs/2026-07-12-phase-5-osint-fusion-design.md` §2 and §4.
2. **Temporal:** article publication date within **[detection window start − 30 days, window end + 14 days]**.
3. **Thematic:** article matches the AOI vertical's GDELT theme/keyword allowlist:
   - Port: construction / trade / shipping / infrastructure themes.
   - Forest: deforestation / environment / logging themes.
   - Flood: flood / natural-disaster / evacuation themes.

Fail any gate → the article is not persisted as a correlation. Zero passing articles → the brief has no news section. **Better to cite nothing than cite garbage.**

Exact GDELT theme identifiers and endpoint choice (DOC 2.0 vs GEO 2.0) are deliberately unspecified here: **Phase 5 opens with an API spike** that verifies the real surface against real queries for the three AOIs before any integration code is written. The allowlists above are semantic targets, not literal API strings.

### 3.3 Kill-switch

Fusion sits behind a single config flag (`FUSION_ENABLED`). Off → ingestion/detection/briefs run imagery-only; the brief schema keeps citation slots either way. This caps the downside of fusion-in-MVP: if correlation quality embarrasses in practice, the demo ships without it and nothing else changes.

### 3.4 Observed vs. reported

Evidence links are polymorphic: a brief claim links to detections (**observed** — pixels) and/or news articles (**reported**). Validator rules:

1. Every quantitative/temporal claim carries ≥ 1 evidence link.
2. A claim backed *only* by articles must use reported-speech framing ("regional news reports…"), never observational framing.

Violation → brief rejected → regeneration with structured feedback, bounded retries (3). The platform never lets journalism masquerade as sensing; this distinction is a demo talking point.

---

## 4. Data Model

PostGIS tables (Pydantic v2 models mirror each; geometries as PostGIS types with GiST indexes):

| Table | Purpose | Key fields |
|---|---|---|
| `aois` | User-defined areas of interest | geometry (polygon), name, vertical preset, cadence |
| `scenes` | Sentinel-2 scene metadata per AOI window | STAC id (natural key), datetime, cloud %, usable-pixel fraction, band/window metadata |
| `detections` | Change events | geometry (polygon), AOI FK, scene-pair FKs, change type, magnitude, confidence, contributing indices |
| `news_articles` | GDELT articles that passed the scorer | url, title, domain, language, seendate, matched AOI FK, after_scene FK, `gates_passed`, `query` — **no geotag column** (superseded 2026-07-12: GDELT exposes no article coordinates; see §3.2) |
| `briefs` | Generated intelligence briefs | AOI FK, window, status (draft/validated/rejected), retry count |
| `brief_claims` | Individual claims in a brief | brief FK, sentence text, claim type (observed/reported/mixed) |
| `evidence_links` | Claim → evidence, polymorphic | claim FK, evidence type (`detection` \| `article`), evidence FK |

Idempotency: ingestion and fusion upsert on natural keys (STAC scene id, article URL) — re-running a job never duplicates rows.

Interfaces (small modules, swappable): `ImageryProvider` (Earth Search today), `ChangeDetector` (classical today, DL later), `NewsProvider` (GDELT today), `BriefGenerator` (Anthropic today).

---

## 5. Showcase AOIs — selections, windows, fallbacks

| Vertical | Site | Image-pair windows | Ground truth | Fallback |
|---|---|---|---|---|
| Port / supply chain | **Vizhinjam International Seaport, Kerala** | Clear Dec–Apr windows across 2021–2025 (construction 2020–2024; first vessel Jul 2024, commissioned Dec 2024) | Extensive public reporting, Adani/Kerala govt milestones | Tuna Tekra, Kandla (arid, very low cloud, younger change) |
| Environment / ESG | **Novo Progresso (BR-163), Pará** | Dry-season pairs Jun–Sep, consecutive years | INPE PRODES/DETER public data | Rondônia fishbone (same ground truth, subtler per-event change) |
| Disaster / insurance | **Porto Alegre — RS floods, May 2024** | Pre-flood Apr 2024 vs. inundated early-to-mid May 2024 (weeks-long inundation → clear post-event scenes findable) | Massive documentation of the event | Valencia DANA Oct 2024 (famous, but tight capture window) |

Phase 1 empirically confirms clean scene pairs exist for each site before the engine is judged against them; a disappointing site gets swapped for its fallback.

---

## 6. Engineering Defaults (starting points, tuned in Phase 2)

All live in per-vertical preset configs, not hardcoded:

- **Cloud gate:** usable-pixel fraction ≥ **70%** after SCL masking; below → skip scene, log reason, auto-widen search window in **+15-day steps capped at +60 days**.
- **AOI size cap:** **500 km²** (≈5 MP per band at 10 m — keeps windowed COG reads laptop-viable; reject larger AOIs at the API with a structured error).
- **Minimum detection area:** port **1,500 m²** (SSIM + NDVI-loss primary); deforestation **5,000 m²** / 0.5 ha (NDVI delta primary); flood **10,000 m²** / 1 ha (NDWI delta primary).
- **Morphology:** opening then closing before polygonization (kernel sizes in preset config).
- **Fusion gates:** ~~25 km spatial buffer~~ **toponym match** (superseded 2026-07-12, §3.2); −30 d/+14 d temporal window **anchored on the after-scene** (the original spanned the whole before→after gap — ~3 years for Vizhinjam — making the gate vacuous); per-vertical theme allowlist.
- **Brief validator:** max 3 regeneration attempts, then brief marked `rejected` and surfaced as such (never silently dropped).
- **Job progress:** REST polling, 2 s interval. No WebSocket, no alerting in v0.1.

None of these numbers goes on a resume or in a README as a claim — they are tunable defaults until Phase 2 verification against the real AOIs.

---

## 7. Build Phases (renumbered with fusion)

0. **Scaffold** — repo, Docker Compose (6 services), pyproject.toml, CI green, PROGRESS.md. Verify: `docker compose up` end-to-end on the Windows machine; rasterio imports in-container.
1. **Imagery ingestion** — STAC search, windowed COG reads, SCL masking, persist to PostGIS. Verify: two clear scenes of Vizhinjam spanning known change, rendered as PNGs, eyeballed. AOI viability confirmed for all three sites.
2. **Change Detection Engine (TDD)** — pure module: indices, differencing, SSIM, threshold → polygons. Verify: synthetic-fixture tests green; known real change detected.
3. **Detection persistence + API** — spatial indexes, AOI CRUD, job endpoints, Celery end-to-end, idempotent re-runs.
4. **Briefs + evidence chain** — generator, evidence links, validator (negative-tested: a deliberately unlinked claim is rejected).
5. **OSINT fusion (GDELT)** — API spike → scorer TDD → Celery task → validator extension (observed/reported). Verify: real correlated articles cited for ≥ 1 AOI; irrelevant article demonstrably rejected; kill-switch tested both ways.
6. **Frontend arena** — MapLibre: AOI draw, before/after slider, detection overlays, click-to-evidence brief panel (article citations open sources). Verify: < 2-minute demo across all three AOIs.
7. **Polish** — README + demo GIF, pre-loaded showcases, one-command spin-up, resume bullet verified against reality.

Each phase gates on `superpowers:verification-before-completion`; PROGRESS.md updated with verification notes.

---

## 8. Testing Strategy

- **TDD targets (pure functions, synthetic fixtures):** the Change Detection Engine (inject a known synthetic change, assert the polygon) and the fusion relevance scorer (synthetic articles at known distances/dates/themes, assert gate outcomes).
- **Negative tests are first-class:** validator rejects unlinked claims; scorer rejects out-of-buffer/out-of-window/off-theme articles; ingestion rejects low-usable-pixel scenes with a logged reason.
- **Idempotency tests:** re-running ingestion/fusion produces zero new rows.
- **Integration:** one end-to-end path (AOI → ingest → detect → fuse → brief → validate) in CI against recorded/stubbed external responses; live-API runs are manual verification steps, not CI.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Fusion-in-MVP schedule creep | Fusion is Phase 5, after the evidence chain works imagery-only; kill-switch means the demo ships regardless |
| Correlation quality embarrasses | Three-gate AND, cite-nothing default, observed/reported framing, kill-switch |
| AOI turns out cloudy/subtle | Phase 1 viability check before engine judgment; ranked fallbacks per vertical |
| GDELT API surface differs from assumptions | Phase 5 opens with a spike; no integration code before the spike verifies reality |
| GDAL/Windows pain | Docker/WSL2 from day zero, non-negotiable |

## 10. Out of Scope (v0.1)

Deep-learning detection (planned extension with OSCD benchmark), alerting, Sentinel-1 SAR, NL AOI tasking, portfolio dashboard, time-series analytics, WebSocket progress, paid imagery.
