# CONTEXT.md — Overwatch Domain Glossary

Maintained via the `domain-modeling` skill. Read this before touching imagery ingestion or the change detection engine — the facts below were each discovered the hard way (a real bug against real Sentinel-2 data), and any change in this area should treat them as constraints, not surprises.

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
- The precondition is **not universal**. It applies where one index-delta has two plausible real-world causes (deforestation vs. harvest). It actively *hurts* where the pre-change state varies — see the port preset below.

## Port construction is structural, not spectral (SSIM-only preset)

Port expansion is a **structural rebuild** of the harbour, and the pre-change surface differs by pixel: sea → built, bare fill → built, vegetation → built. Any spectral index co-signal captures one of those transitions and **vetoes the other two**.

- Concretely at Vizhinjam: an NDWI-decrease co-signal fired only on the water-facing reclaimed *edge* and vetoed the bare-fill interior, which was already land by the 2021 before-scene. The terminal came back half-outlined.
- Fix: the `port` preset is **SSIM-dissimilarity only**, threshold `0.55`, min_area `5_000` m². SSIM is agnostic to prior cover, so it fires wherever the surface was structurally rebuilt. False positives are controlled by the threshold and min_area, not by an index veto that misses most of the target.
- Result: largest polygon 19.6 → 39.6 ha, total 31 → 83 ha, with 74.9 ha inside ~1 km of the terminal.
- **The threshold is a completeness/precision dial, and 0.55 deliberately favours completeness.** It leaves ~14 stray coastal polygons (8.4 ha total, none over 1.05 ha, 1.5–3.9 km north) that are real 4-year change but not port construction. Tightening to `0.60` cuts the strays to 6 (4.3 ha) but shrinks the terminal body to ~30.3 ha. Confirmed visually and kept at 0.55 — the port reads cleanly, including port-adjacent buildings.

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
