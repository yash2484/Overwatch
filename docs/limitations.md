# Limitations and what's next

The full version of the short list in the [README](../README.md#whats-next). Everything here is measured or observed, not estimated. Where a fix is known, it's named.

## Detection

**Flood detection can't separate shaded vegetation from water.** NDWI rises when a canopy is shaded — NIR falls harder than green — so a dark hillside can clear both flood rules and be outlined as flood.

The fix is SWIR. Water absorbs it almost completely whatever its sediment load; wet and shaded vegetation doesn't. `MNDWI = (green - swir16) / (green + swir16)` makes the cut that NDWI and NDVI can't. The index functions are written and tested on the `feat/swir-indices` branch; what's missing is the ingestion change, since `_KEEP_ASSETS` currently fetches red/green/blue/nir/scl only. Landing it means re-scoring the EMSN194 flood case and retiring the turbid-water xfail, so it's a scoped piece of work rather than a tuning tweak.

Worth recording that the cheap version was tried first: an absolute after-image gate shipped on 2026-08-13 and was withdrawn the same day. Porto Alegre's floodwater is heavily sediment-laden, suspended solids raise NIR, NDWI drops, and the gate rejected 1,007 ha of the genuine flood it was meant to keep. `ndvi_after` was measured as a replacement and its curve has no knee either. No absolute threshold on these four bands separates turbid floodwater from wet vegetation, because the scene holds a real continuum: open brown water, shallow water over grass, partly submerged canopy.

**Construction recall is capped by a spatial prior.** `focus_radius_m=2000` keeps only detections within 2 km of the largest one, which anchors the subject being watched. Correct for a single-subject port AOI; wrong anywhere change is genuinely dispersed. It's opt-in per vertical for that reason — flood and forest leave it unset.

**`confidence` is not a probability.** It's the fraction of pixels inside a polygon that exceeded the rule threshold. Useful for ranking detections against each other, meaningless as a statement of certainty.

## Briefs and validation

**The validator checks areas and dates, not every number.** What it does check: every observed claim cites a resolvable detection, quoted areas reconcile against the linked geometry within 10%, dates match a scene date exactly, and a claim backed only by news reads as reported speech and carries no figures.

What it doesn't:

- Percentages and bare numbers in observed claims are not cross-checked.
- The area check fails **open** on units it can't parse — acres, "sq km", square miles pass through unverified. A patch exists but is untested and deliberately uncommitted.

"Every area figure reconciles against the linked geometry and every date matches a scene date" is true. "Every number is checked" is not.

**One claim, one quantity.** Gate 3 compares each quoted area against the sum of every detection linked to that claim, so a claim quoting two figures and citing both detections fails twice. This is intended — a reader can't tell which polygon a number refers to when several are cited together — but it means the prompt has to push the model toward atomic claims, and multi-figure first drafts get rejected routinely.

## Operations

**Nothing runs on a schedule.** The weekly re-check logic exists and is unit-tested, and the Celery beat task is registered, but no scheduled run has ever fired. Every pipeline run in this repository was submitted by hand.

**Live GDELT fusion is blocked.** The news in the demo was fetched earlier and stored. The remaining live gate needs a genuinely different network, because the current IP carries a long-lived rate-limit block. Vizhinjam has no articles at all — the fusion layer has only ever produced rows for Porto Alegre.

**Nothing has been load-tested.** Two areas of interest, a handful of runs, one machine. A full pipeline run takes six to fifteen minutes end to end, including in-run retries.

## Reproducibility

**Benchmarks don't reproduce from a clean clone.** `data/` is gitignored, so OSCD (~490 MB) has to be downloaded by hand before `run_oscd` will work, and the EMSN194 and PRODES archives aren't kept locally at all — only their results, each recording the SHA-256 of the source archive and the detector commit that produced it.

**No CI job can catch benchmark drift.** This is the gap that caused the one real documentation failure in this project's history: a preset changed four hours after its benchmark was recorded, and the published accuracy figures described a detector that had stopped shipping. Nothing could detect it automatically, because the benchmark data isn't in the repo for CI to run against. Until that's closed, any preset change invalidates every published number until the benchmark is re-run by hand. The episode is written up in [PROGRESS.md](../PROGRESS.md).

## Frontend

**The production bundle is 2.06 MB** (582 kB gzipped), in one chunk. MapLibre and deck.gl dominate it. Code splitting is an open follow-up.

**Frontend tests don't run in CI.** Three test files, 18 tests, host-only. CI builds the frontend but doesn't test it.

## Rough order of work

1. SWIR ingestion, then MNDWI in the flood preset, then re-score EMSN194 and retire the xfail.
2. Close the validator's numeric gaps — unparseable units fail closed, percentages cross-checked.
3. Get the beat scheduler actually firing against a live AOI.
4. Code-split the frontend bundle.
5. Frontend tests into CI.
