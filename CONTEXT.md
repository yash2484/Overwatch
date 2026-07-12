# CONTEXT.md — Overwatch Domain Glossary

Maintained via the `domain-modeling` skill. Read this before touching imagery ingestion or the change detection engine — the facts below were each discovered the hard way (a real bug against real Sentinel-2 data), and any change in this area should treat them as constraints, not surprises.

## Sentinel-2 BOA processing baseline offset

Earth Search STAC items carry a raw digital-number (DN) encoding for Bottom-of-Atmosphere (BOA) reflectance that is **not consistent across processing baselines**. From baseline `04.00` onward, ESA's reprocessing adds a systematic `-1000` offset to the stored DNs unless Earth Search has already normalized it.

- `boa_dn_offset(props)` (`backend/src/overwatch/imagery/earth_search.py`) reads `s2:processing_baseline` and the `earthsearch:boa_offset_applied` flag: baseline `>= 4.0` and offset not already applied → `-1000`; otherwise `0`.
- `SceneMeta.dn_offset` (`backend/src/overwatch/imagery/models.py`) carries this value forward; **add `dn_offset` to raw DNs before any band-index math** (NDVI/NDWI/NBR). Skipping this silently shifts every index computed from a post-04.00 scene.
- Discovered in: `c836c8e fix(phase-2): harmonize Sentinel-2 BOA offset across processing baselines`.
- Why it matters here specifically: mixing an old-baseline scene (offset 0) with a new-baseline scene (offset -1000) in the same before/after pair produces a spurious uniform brightness shift that differencing reads as change everywhere — a false-positive generator, not a localized bug.

## One acquisition, several STAC items (reprocessings)

Earth Search can hold **more than one item for the same Sentinel-2 acquisition** — later reprocessings of identical pixels, distinguished by the numeric field in the id: `S2A_43PGK_20210212_0_L2A` vs `S2A_43PGK_20210212_2_L2A`.

- They are not interchangeable: atmospheric correction differs between processing runs, so surface reflectance (and therefore detection polygons) differ slightly. Vizhinjam 2021→2025 yields **9 polygons via `_0_` and 12 via `_2_`**, same dates, same preset.
- Which item you get depends on **how you pick**: `detection/cli.py` takes catalog order (`scenes[0]`); `find_usable_scene` sorts cloud-ascending and takes the first that clears the SCL gate. For 2021-02-12 the cloud values are 0.1416% (`_0_`) vs 0.0313% (`_2_`) — no tie, so each selector is deterministic but they disagree.
- Do **not** reach for the BOA-offset explanation when counts differ across items of the same date: check `dn_offset` first. Both 2021-02-12 items carry `dn_offset=0`.
- Consequence for idempotency: replace-set keys on `(aoi, before_scene_id, after_scene_id)`, and scene rows key on `stac_id` — so a stable selector gives a stable pair and a re-run rewrites the same rows. A selector that flip-flops between reprocessings would write a *second* pair rather than duplicate the first.

## Forest-precondition gate (deforestation preset)

Raw NDVI-decrease is **not sufficient** to detect deforestation: crop harvest also drops NDVI by a similar magnitude, and a naive threshold conflates the two.

- Fix: `_change_maps` in `backend/src/overwatch/detection/detector.py` now also computes absolute `<index>_before` maps (not just before/after deltas). The forest preset (`backend/src/overwatch/detection/presets.py`) ANDs the NDVI-decrease trigger with `ndvi_before >= 0.60` — the "before" image must have actually been forest-level green, not already-cleared cropland.
- Discovered in: `2b6c1fb feat(detection): was-forest precondition for forest preset`, validated against the real Novo Progresso AOI pair: raw NDVI-decrease detections dropped from 103 → 63 polygons after the gate; the 40 removed were cropland already cleared before the observation window, not new deforestation.
- General lesson for other presets (port, flood): a "was it plausibly in the pre-change state to begin with" precondition is likely needed wherever the same index-delta pattern can arise from two different real-world causes. Check before shipping a new preset threshold.

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

- **GEO 2.0 is retired.** `api.gdeltproject.org/api/v2/geo/geo` → **HTTP 404** on every variant, including the documented
  `mode=PointData&format=GeoJSON`. DOC 2.0 is the only usable surface.
- **DOC 2.0 returns no coordinates.** A record carries exactly `url, url_mobile, title, seendate, socialimage, domain,
  language, sourcecountry`. There is no location operator either: `locationcc:BR` comes back as *"keywords were too
  short, too long or too common"* — it was parsed as a literal keyword.
- **`sourcecountry` is the publisher's registration country, not the story's location.** Mongabay's article about
  deforestation in Pará, Brazil returns `sourcecountry: Indonesia`. Never use it as a geographic proxy.
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

Full evidence and the resulting gate design: `design-specs/2026-07-12-phase-5-osint-fusion-design.md` §2.
