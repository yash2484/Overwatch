# Phase 5 Design — OSINT Fusion (GDELT)

> **Status:** Approved by Yash in-session 2026-07-12 (brainstorm via `superpowers:brainstorming`).
> **Scope authority:** `plans/2026-07-03-mvp-roadmap.md` "Phase 5". Data-model authority is design-spec §4
> (`design-specs/2026-07-02-overwatch-mvp-design.md`), extended by decisions 3 and 4 below.
> **Supersedes:** design-spec §3.2's *spatial* gate and *temporal* window definition. Both were written against an
> assumed GDELT surface that does not exist. See §2 — this supersession is the central result of this phase's spike.
> **Goal:** persisted, deterministic news correlation. The brief generator reads articles from the database exactly as
> it reads detections; journalism is never allowed to masquerade as sensing.

---

## 1. The one-paragraph version

Fusion is its own Celery task, downstream of detection (design-spec §3.1, approach B). It queries GDELT DOC 2.0 for the
AOI's place terms + vertical themes inside the detection's observation window, runs every returned article through a
**pure, unit-tested three-gate AND scorer**, deduplicates syndicated copies, and persists only survivors. The brief
generator then cites those rows. A fourth validator gate enforces the observed/reported wall: a claim backed only by
articles must use reported-speech framing and may carry no quantities. `FUSION_ENABLED=false` turns the whole thing off
and nothing else changes.

---

## 2. Spike results — what GDELT actually is (2026-07-12, measured)

The roadmap mandated an API spike before any integration code. It ran, and it invalidated two load-bearing assumptions
in the approved design spec. **Everything below is measured against live queries, not documentation.**

### 2.1 GEO 2.0 is down, and would not help even if it were up

`https://api.gdeltproject.org/api/v2/geo/geo` returns **HTTP 404** for every form tried — the bare `?query=flood`, the
documented `?query=…&mode=PointData&format=GeoJSON`, `format=csv`, and the exact `?query=theme:env_nuclearpower&
mode=country&format=html` URL published in GDELT's own docs. **5/5 consecutive retries, all 404.** Meanwhile `doc/doc`
and `tv/tv` resolve fine, and `/api/v2/geo` 301-redirects to `/api/v2/geo/` which 403s (a blocked directory listing) —
so the path exists but the endpoint is not served from it.

> **Wording discipline:** an earlier draft of this spec said GEO 2.0 was "retired." That over-claimed the evidence.
> GDELT's client-library docs describe the GEO endpoint as *"occasionally unavailable (HTTP 404) independent of the DOC
> API"* — a **documented-flaky** endpoint. It is unusable right now; whether permanently is not something a 404 can tell
> us. Either way we cannot build a demo on it.

**But uptime is not the issue.** GDELT's own announcement states that the Global Geographic Graph is *"the underlying
dataset **powering the GDELT GEO 2.0 API**"* — GEO 2.0, the GGG BigQuery table, and the GKG `V2Locations` field are the
**same geocoder through different pipes**. Restoring the endpoint (or switching to `format=geojson`, `format=csv`, or
BigQuery) changes the transport, not the payload. See §2.4 for what that payload actually contains.

**DOC 2.0 is the only usable GDELT surface.**

### 2.2 DOC 2.0 returns no coordinates, and has no location operator

A DOC 2.0 `mode=artlist&format=json` record contains exactly:

```json
{ "url": "...", "url_mobile": "...", "title": "...", "seendate": "20240615T170000Z",
  "socialimage": "...", "domain": "thehindu.com", "language": "English", "sourcecountry": "India" }
```

No latitude. No longitude. No themes echoed back. And there is no location operator: `locationcc:BR` comes back as
*"One or more of your keywords were too short, too long or too common: (locationcc:br)"* — GDELT parsed it as a literal
keyword, not an operator.

**Therefore design-spec §3.2's Gate 1 — *"article geotag (GDELT GKG geocoding) falls within the AOI geometry buffered by
25 km"* — cannot be built. There is no geotag to test.**

### 2.3 `sourcecountry` is a trap

It is the **publisher's registration country**, not the story's location. Mongabay's article about Amazon deforestation
in Pará, Brazil returns `"sourcecountry": "Indonesia"`. Any design that uses `sourcecountry` as a geographic proxy is
silently wrong. **Do not.**

### 2.4 The GKG geofence was attempted, measured, and rejected on quality — not cost

Before falling back, we tested the one path that *could* have preserved a true geofence: DOC gives `seendate` at 15-minute
resolution, which maps directly onto a GKG bucket filename (`20240512214500.gkg.csv.zip`). Fetch that bucket, find the
article by URL, read its `V2Locations` field for real lat/lon. This **works mechanically** — the file is 3.4–8.9 MB, the
article is in it, and `V2Locations` does carry coordinates.

It fails on data quality. Here is what GKG's geocoder actually returned for the three articles this phase's demo depends on:

| Article | GKG `V2Locations` (verbatim) | Nearest point to AOI |
|---|---|---|
| The Hindu — *"Customs grants approval to Vizhinjam International Seaport"* | `1#India#IN#IN#20#77#IN` — **country centroid only.** "Vizhinjam" never geocoded. | ~1,000 km |
| Mongabay — *"probe into Amazon's largest single deforester"* | `Ezequiel, Mato Grosso Do Sul#-22.05#-54.45`; `Guimar, Castilla Y León, **Spain**#41.9#-3.75`; `Castanha, Rio Grande Do Sul#-32.11#-52.59`. **Pará never appears.** | ~330 km |
| Rio Times — *"6,500 hectares cleared"* | The `seendate` bucket does not contain the article at all — it holds an **Ethiopia militia story**. Bucket alignment is unreliable. | not found |

**A 25 km geofence rejects 100% of our true positives.** GKG's V2Locations resolves to country/ADM2 centroids driven by
incidental place mentions in body text, not the story's subject location. The "principled" gate is not stronger than a
name match — on this corpus it is *broken*. Building it would cost ~1–2 days and ~1–2 GB per fusion run to get strictly
worse answers.

> **This is recorded in `CONTEXT.md` as a domain gotcha so nobody rebuilds the geofence in six months.**
> It is also the honest interview answer: *we built the principled gate, measured it, and it rejected every true positive.*

### 2.4b The root cause, in GDELT's own words — and why no access method fixes it

The measured failures in §2.4 are not bugs, and not an artifact of using the raw GKG files instead of a nicer API. They
are the **documented, intended behaviour** of GDELT's geocoder. From the Global Geographic Graph announcement, verbatim:

> *"all locations are drawn from a set of **centroid-based gazeteers** in which every reference to Paris, France will
> always yield **precisely the same coordinate**"*

**News geocoding resolves a place *mention* to that place's gazetteer centroid. Our AOIs are sub-place polygons.** Novo
Progresso is a ~38,000 km² municipality; its centroid can sit >100 km from our ~60 km² AOI. Vizhinjam resolves, at best,
to Thiruvananthapuram — and in the article we actually measured, only to the **country centroid of India**.

So a 25 km geofence is not a strict gate that happens to be broken. It is **geometrically meaningless at the resolution
our AOIs operate at**, and it would remain so via *any* transport:

| Access path | Fixes the centroid ceiling? |
|---|---|
| GEO 2.0 REST (`format=geojson` / `format=csv`) | **No** — GGG is *"the underlying dataset powering the GEO 2.0 API"*. Same geocoder. (Also currently 404 — §2.1.) |
| BigQuery `gdelt-bq.gdeltv2.ggg` | **No** — this *is* GGG. Better access, identical coordinates. |
| Raw GKG `V2Locations` files | **No** — measured directly in §2.4. This is the same extraction. |

**Evaluated and rejected: BigQuery / GGG as the Gate-1 source.** Beyond the centroid ceiling it adds a GCP project,
service-account credentials in `.env`, a `google-cloud-bigquery` dependency, and a hard cloud dependency for anyone
cloning the repo — for a gate whose input resolution is the problem. Rejected for v0.1.

**But GGG holds one column worth revisiting later.** Its rows are per *location-mention* (not per-article) and carry
**`ContextualText` — a 600-character snippet around the mention** — plus `GeoType` (a precision code; `>1` excludes
country centroids like the India hit). `ContextualText` directly attacks §2.5's problem: titles routinely omit the place
name, and 600 characters of real context is a far better substrate for the **toponym and thematic** gates than a
headline. That is a genuine upgrade path — to Gates 1 and 3, **not** to a spatial gate. Filed for v0.2.

**The one experiment that would overturn this decision.** Runnable in the free BigQuery sandbox (no card, 1 TB/month).
If the Mongabay deforester story comes back, the geofence is alive and Gate 1 should be swapped; if it returns empty,
the geofence is dead on a second, independent dataset. (`ContextualText` is deliberately excluded from the `SELECT` —
600 chars × 1.7 B rows would consume most of the free tier in a single query.)

```sql
SELECT URL, Title, Location, Lat, Lon, GeoType, DATE(DateTime) AS d
FROM `gdelt-bq.gdeltv2.ggg`
WHERE DATE(DateTime) BETWEEN '2023-08-01' AND '2023-09-10'
  AND Lat BETWEEN -7.40 AND -6.90     -- ~±25 km box around the Novo Progresso AOI
  AND Lon BETWEEN -55.70 AND -55.10
  AND GeoType > 1                      -- exclude country centroids
ORDER BY d
```

### 2.5 Titles routinely omit the place name — the finding that shapes the scorer

DOC's artlist exposes **only the title**. GDELT's `query` parameter matches against **full article text**. These are not
the same, and the gap is large:

- **Zero of six** Porto Alegre results contain "Porto Alegre" in the title. They say *"Brazil Rio Grande Do Sul May Have
  More Record Level Flooding"* and *"Brazil Mayor Mammoth Task: Rebuild From Floods"*.
- **Zero of four** Novo Progresso results contain "Novo Progresso" in the title. They all say **"Amazon"**.

A naive "title contains the AOI place name" gate scores **0/6 and 0/4 on our own demo articles.** This is why the scorer
in §4 corroborates against a *generous* toponym list (including regional names) rather than the strict query term — and
why the strict term is enforced at the retrieval layer instead. See §4.1.

### 2.6 What does work

- **`theme:` is a real operator.** `theme:NATURAL_DISASTER_FLOOD` returned correct Porto Alegre flood coverage.
- **Literal theme identifiers**, pulled from the live taxonomy (`LOOKUP-GKGTHEMES.TXT`) with corpus counts:
  `NATURAL_DISASTER_FLOOD` (6.5M), `NATURAL_DISASTER_FLOODING` (6.2M), `EVACUATION` (12.3M),
  `ENV_DEFORESTATION` (722k), `ENV_FORESTRY` (3.6M),
  `MARITIME` (55M), `NEW_CONSTRUCTION` (6.9M), `WB_1803_TRANSPORT_INFRASTRUCTURE` (73M).
- **Historical windows work** — `startdatetime`/`enddatetime` resolve correctly back through 2023.
- **All three AOIs have real, citable coverage.** Novo Progresso is the standout: satellite sees the clearing, Mongabay
  and Rio Times report the enforcement action against the deforester. That is the fusion thesis, written for us.
- **Rate limiting is aggressive:** HTTP **429** with a **plaintext** body (not JSON). ≥5 s between requests is the
  documented ask; after a burst it took ~75 s to clear. The client must handle a 429 whose body is not JSON.

---

## 3. Decisions resolved (2026-07-12 brainstorm)

1. **Gate 1 is a toponym gate, not a spatial gate — and it is named that way everywhere.** No column, function, or doc
   may call it "spatial". The design spec's geofence is formally superseded by §2.2/§2.4. The trust story never rested on
   geofence tightness; it rests on the observed/reported wall (decision 5), which holds regardless.
2. **Conjunctive at two layers.** Retrieval enforces the strict place term against GDELT's full-text index (which sees
   more than we do); the pure scorer corroborates against what the record actually exposes. Both layers are AND-shaped.
   Neither alone is trusted. See §4.
3. **Temporal window anchors on the after-scene**, not the detection window. The inherited definition
   (`[window start − 30 d, window end + 14 d]`) is near-vacuous: change-detection pairs span months to years — Vizhinjam's
   pair is ~3 years apart, making the "gate" ~3 years wide. New definition:
   **`[after_scene.captured_at − 30 d, after_scene.captured_at + 14 d]`** — a ~44-day band around when the change was
   actually observed. Bounds live in the per-vertical preset configs (same pattern as Phase 2's min-area thresholds), so
   they are tunable, not hardcoded. *A two-tier proximate/contextual window is explicitly deferred to v0.2.*
4. **Schema: `news_articles` + additive `evidence_links.article_id`** (migration 0004). Phase 4 already shipped the
   polymorphic `evidence_type` and the `reported`/`mixed` claim types, so this phase adds one FK column and one table —
   no rework. AOIs gain `place_terms` / `region_terms` text arrays.
5. **Validator Gate 4 — the observed/reported wall.** A claim whose evidence is *only* articles must use reported-speech
   framing and may carry **no quantities**. Purely additive to Phase 4's validator: the Gate-4 slot, the claim types, and
   the polymorphic evidence links all already exist.
6. **Trigger: chain + backfill endpoint.** When `fusion_enabled`, the detection chain becomes
   `ingest_before → ingest_after → detect → fuse`. Plus `POST /aois/{slug}/fusion` to (re)run fusion against an existing
   scene pair — needed anyway to backfill the AOIs that already have detections without re-running ~8-minute detection
   jobs, and it doubles as the demo lever.
7. **English-only for v0.1.** Filter on the response's `language` field, which is in every record. We do **not** depend on
   the `sourcelang:` operator — it could not be verified (429'd during the spike), and there is no reason to depend on an
   unverified operator when the record carries the field directly.
8. **Deduplicate syndication.** Two of the six Porto Alegre results are the same Reuters wire story carried by usnews.com
   and yahoo.com. Without dedup, syndication inflates the citation count and makes one story look like corroboration.

---

## 4. The relevance scorer (pure function — this phase's TDD centrepiece)

`score_article(article: NewsArticle, aoi: Aoi, window: FusionWindow, preset: VerticalPreset) -> GateResult`

No I/O. Deterministic. The project's second TDD target after the detection engine.

### 4.1 Why two layers

| Layer | Enforces | Sees | Testable in isolation |
|---|---|---|---|
| **Retrieval** (`GdeltDocProvider`) | strict place term ∧ vertical themes ∧ date range | full article text, GKG themes | via recorded fixtures |
| **Scorer** (pure) | toponym ∧ temporal ∧ thematic corroboration | title, seendate, language, domain | yes — fixtures only |

The strict term (`"Novo Progresso"`) is enforced by GDELT against the body. The scorer cannot re-verify it (§2.5), so it
corroborates with a **generous** term list that includes regional names that *do* appear in titles. An article only
reaches the scorer if it already passed the strict full-text term — so "Amazon" in the corroboration list cannot admit a
Rondônia-only story; that story would never have been retrieved.

### 4.2 The three gates (AND — all must pass)

**Preconditions** (cheap rejects, before the gates): `language` ∈ preset allowlist (`["English"]` in v0.1);
`url` is http(s); `domain` not in the syndication/aggregator blocklist.

1. **Toponym gate.** The normalized title contains ≥1 of the AOI's `place_terms` ∪ `region_terms`.
   Normalization: casefold, strip diacritics (`Pará` → `para`, `Amazônia` → `amazonia`), collapse whitespace,
   match on word boundaries (so "Para" does not match "Paraguay").
2. **Temporal gate.** `seendate` ∈ `[after_scene.captured_at − lead_days, after_scene.captured_at + lag_days]`.
   Defaults `lead_days=30`, `lag_days=14`, per-vertical in the preset.
3. **Thematic gate.** The normalized title contains ≥1 of the vertical's keyword allowlist (stem-matched):
   - **port:** `port, seaport, terminal, berth, shipping, cargo, container, harbour, harbor, vessel, transshipment`
   - **forest:** `deforest, desmatamento, logging, clearing, cleared, forest, rainforest, illegal`
   - **flood:** `flood, inundat, evacuat, deluge, submerged, rainfall, water level`

Fail any gate → not persisted. Zero survivors → the brief simply has no news section. **Better to cite nothing than cite
garbage** (design-spec §3.2, unchanged).

Every persisted row records `gates_passed` (JSONB) and the exact `query` string used → every citation is auditable back
to why it was admitted.

### 4.3 Dedup (pure, after the gates)

Group survivors by normalized title (casefold, strip punctuation and whitespace). Within a group keep one row: highest-
ranked domain by a configured preference order, tie-broken by earliest `seendate`. Persist only the survivor; record the
suppressed URLs in `meta.duplicates` so the dedup is visible rather than silent.

### 4.4 Dry-run against the real corpus (all 14 spiked articles)

This design was validated against every article the spike actually returned, before a line of code:

| AOI | Result |
|---|---|
| **Vizhinjam** | *"Customs grants approval to Vizhinjam International Seaport"* ✅ · *"Vadhavan port may cast a shadow on Vizhinjam port prospects"* ✅ · *"Vizhinjam beckons shipping lines… Colombo Port"* ✅ · Malayalam article → rejected by the language precondition. **3 pass.** |
| **Novo Progresso** | *"Brazilian authorities launch probe into Amazon's largest single deforester"* ✅ · *"Major Amazon deforester arrested: 6,500 hectares cleared"* ✅ · *"Brazil records 66% drop in Amazon deforestation in July"* ✅ · *"How the Amazon's greatest devastator sold cattle to a Carrefour supplier"* → **rejected** (no thematic keyword in title — conservative, correct). **3 pass, including both money stories.** |
| **Porto Alegre** | *"Brazil Rio Grande Do Sul May Have More Record Level Flooding"* ✅ · yahoo.com syndication of the same wire → **deduped away** · *"Brazil Mayor Mammoth Task: Rebuild From Floods"* → **rejected** (no place term in title) · Chinese + Japanese → rejected by language. **1–2 pass after dedup.** |

**Negative tests fall out naturally** and are genuinely adversarial, not strawmen:
- *"Amazon Prime Day deals announced"* → toponym ✅ (`Amazon`!), thematic ❌ → **rejected**. Proves the AND matters.
- *"Porto Alegre wins football derby"* → toponym ✅, thematic ❌ → **rejected**.
- *"Severe flooding hits Bangladesh"* → thematic ✅, toponym ❌ → **rejected**.
- An in-window, on-theme, on-place article dated 6 months after the after-scene → temporal ❌ → **rejected**.

---

## 5. Data model (alembic migration 0004 — additive; existing tables untouched)

### `news_articles`

| column | type | notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `aoi_id` | BIGINT FK → aois | ON DELETE CASCADE |
| `job_id` | UUID FK → jobs | the fusion run that admitted it |
| `after_scene_id` | BIGINT FK → scenes | the observation anchor (decision 3) |
| `url` | TEXT | |
| `title` | TEXT | |
| `domain` | TEXT | |
| `language` | TEXT | |
| `seendate` | TIMESTAMPTZ | parsed from `20240615T170000Z` |
| `gates_passed` | JSONB | `{toponym: [...matched terms], temporal: true, thematic: [...matched keywords]}` |
| `query` | TEXT | the exact GDELT query string that retrieved it — auditability |
| `meta` | JSONB | `{socialimage, sourcecountry, duplicates: [...suppressed urls]}` |
| `created_at` | TIMESTAMPTZ | |

Natural key: **`UNIQUE (aoi_id, after_scene_id, url)`** → idempotent re-runs, consistent with the Phase 3 convention.

### `aois` (additive columns)

| column | type | notes |
|---|---|---|
| `place_terms` | TEXT[] | e.g. `{Vizhinjam, Thiruvananthapuram}`. **Null/empty → fusion skipped for this AOI, logged.** |
| `region_terms` | TEXT[] | e.g. `{Amazon, Amazônia, Pará, BR-163}` — the generous corroboration list of §4.1 |

The **strict** retrieval term is `place_terms[0]`; `region_terms` are corroboration-only and never enter the GDELT query.

### `evidence_links` (additive column)

| column | type | notes |
|---|---|---|
| `article_id` | BIGINT FK → news_articles | nullable |

Plus the CHECK constraint mirroring Phase 4's detection one:
`evidence_type != 'article' OR article_id IS NOT NULL`.

**Staleness carries over.** Phase 4's `replace_detections` flips validated briefs on a pair to `stale`. Fusion re-runs
replace the article set for a pair the same way and must flip validated briefs on that pair to `stale` too — otherwise a
validated brief keeps a dangling `article_id`. Invariant preserved: **validated ⇒ every link resolves.**

---

## 6. Components

### `NewsProvider` (protocol) — mirrors `ImageryProvider` / `BriefGenerator`

```python
class NewsProvider(Protocol):
    def search(self, query: str, start: datetime, end: datetime, max_records: int) -> list[RawArticle]: ...
```

- **`GdeltDocProvider`** — the real one. Builds `("<strict term>") (theme:A OR theme:B)` with `startdatetime`/
  `enddatetime`, `mode=artlist`, `format=json`, `maxrecords` (DOC caps at 250).
  Must handle: **HTTP 429 with a plaintext body** (do not `json.loads` it), a `200` whose body is the plaintext
  *"keywords were too short/long/common"* error, and an empty body. Throttle ≥5 s between calls; retry with backoff.
- **`FakeNewsProvider`** — replays recorded fixtures. **CI never touches the network.** Fixtures are the real spike
  responses, captured verbatim.

### `fuse` Celery task

`ingest_before → ingest_after → detect → fuse` when `fusion_enabled`; else the chain ends at `detect` (kill-switch).
The task: resolve the AOI + after-scene → build the window from the preset → query → score → dedup → replace-set persist →
flip stale briefs. Idempotent on the natural key. Same retry/backoff discipline as the Phase 3 tasks.
Carries Phase 4's prompt-size discipline forward: cap the article count fed to the brief prompt, log any truncation.

### `POST /aois/{slug}/fusion`

202 + `job_id`; polls via the existing `GET /jobs/{id}`. Guards: 404 unknown AOI; **409 if the AOI has no succeeded
detection job** (nothing to anchor on); **409 if `place_terms` is empty**; **503 if `fusion_enabled` is false** — the
kill-switch must be visible at the API boundary, not a silent no-op.

### Validator Gate 4 (extends the Phase 4 validator — additive, no migration)

For each claim whose evidence links are **all** `evidence_type='article'`:
1. **Reported-speech framing required.** The claim text must open with reported framing
   (`reports?|reported|according to|regional news|local media|press reports`). Observational verbs
   (`shows|reveals|indicates|we observe|imagery confirms|detected`) are a **violation**.
2. **No quantities.** Any number-with-unit, percentage, or bare magnitude in an article-only claim is a **violation** —
   articles are not sensing. (Reuses Phase 4's Gate-3 quantity detector, which already exists.)
3. `claim_type` must be `reported`. A `mixed` claim must carry **≥1 detection link AND ≥1 article link**; a claim typed
   `observed` may carry **no** article links.

Violations → brief rejected → bounded regeneration with structured feedback (3 attempts), exactly as Phase 4.

---

## 7. Testing strategy

- **Scorer: pure TDD, fixtures-first.** Each gate gets valid / invalid / boundary cases. The boundary cases matter:
  seendate exactly on `after − 30d` and `after + 14d` (inclusive), diacritic folding (`Pará` ↔ `Para`), word-boundary
  (`Para` must not match `Paraguay`), stem matching (`deforester` must hit the `deforest` stem).
- **Negative tests are first-class**, per §4.4 — the "Amazon Prime Day" case is the headline one and belongs in the demo.
- **Provider tests** run against recorded fixtures, including the **429-plaintext** and **200-plaintext-error** bodies.
  CI never hits the network.
- **Kill-switch tested both ways**: `fusion_enabled=true` → chain has 4 links, endpoint returns 202;
  `fusion_enabled=false` → chain has 3, endpoint returns 503, briefs still generate imagery-only.
- **Validator Gate 4 negative test**: a claim linked only to an article but phrased observationally
  (*"imagery confirms 6,500 hectares were cleared"*) must be **rejected**, and the rejection surfaced with its violation.
- **Idempotency**: re-run fusion → zero duplicate rows (natural key), and validated briefs on that pair flip to `stale`.

---

## 8. Gate (definition of done)

1. Real correlated articles cited for **≥1 AOI** in a regenerated brief, every citation resolving to a `news_articles`
   row (SQL join proof).
2. A deliberately irrelevant article is **demonstrably rejected** by the gates (negative test, with the violation shown).
3. `FUSION_ENABLED` **tested both ways**.
4. Validator Gate 4 rejects an article-only claim wearing observational framing.
5. Re-run produces zero duplicate rows; a validated brief on the re-fused pair flips to `stale`.

---

## 9. Risks

- **GDELT rate limiting / outage.** Fusion is a separate task by design (§3.1 approach B) — a GDELT failure fails the
  fusion task, never ingestion, detection, or brief generation. Retries with backoff; the brief just has no news section.
- **Toponym recall.** A generous corroboration list trades precision for recall; the strict retrieval term is what keeps
  precision. If a term list proves noisy in practice, it is per-AOI data (a column), not code — tune without a deploy.
- **Thin coverage for an AOI.** Novo Progresso and Porto Alegre are well covered; a future AOI may return zero. That is a
  designed-for outcome (no news section), not a failure.

## 10. Out of scope (v0.1)

Two-tier proximate/contextual windows (decision 3 — deferred to v0.2). Non-English articles. Article body text /
full-text fetching. Sentiment or tone gates. GKG raw-file ingestion (§2.4 — rejected on measured quality grounds).
