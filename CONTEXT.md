# CONTEXT.md — Overwatch Domain Glossary

Maintained via the `domain-modeling` skill. Read this before touching imagery ingestion or the change detection engine — the facts below were each discovered the hard way (a real bug against real Sentinel-2 data), and any change in this area should treat them as constraints, not surprises.

## Sentinel-2 BOA processing baseline offset

Earth Search STAC items carry a raw digital-number (DN) encoding for Bottom-of-Atmosphere (BOA) reflectance that is **not consistent across processing baselines**. From baseline `04.00` onward, ESA's reprocessing adds a systematic `-1000` offset to the stored DNs unless Earth Search has already normalized it.

- `boa_dn_offset(props)` (`backend/src/overwatch/imagery/earth_search.py`) reads `s2:processing_baseline` and the `earthsearch:boa_offset_applied` flag: baseline `>= 4.0` and offset not already applied → `-1000`; otherwise `0`.
- `SceneMeta.dn_offset` (`backend/src/overwatch/imagery/models.py`) carries this value forward; **add `dn_offset` to raw DNs before any band-index math** (NDVI/NDWI/NBR). Skipping this silently shifts every index computed from a post-04.00 scene.
- Discovered in: `c836c8e fix(phase-2): harmonize Sentinel-2 BOA offset across processing baselines`.
- Why it matters here specifically: mixing an old-baseline scene (offset 0) with a new-baseline scene (offset -1000) in the same before/after pair produces a spurious uniform brightness shift that differencing reads as change everywhere — a false-positive generator, not a localized bug.

## Forest-precondition gate (deforestation preset)

Raw NDVI-decrease is **not sufficient** to detect deforestation: crop harvest also drops NDVI by a similar magnitude, and a naive threshold conflates the two.

- Fix: `_change_maps` in `backend/src/overwatch/detection/detector.py` now also computes absolute `<index>_before` maps (not just before/after deltas). The forest preset (`backend/src/overwatch/detection/presets.py`) ANDs the NDVI-decrease trigger with `ndvi_before >= 0.60` — the "before" image must have actually been forest-level green, not already-cleared cropland.
- Discovered in: `2b6c1fb feat(detection): was-forest precondition for forest preset`, validated against the real Novo Progresso AOI pair: raw NDVI-decrease detections dropped from 103 → 63 polygons after the gate; the 40 removed were cropland already cleared before the observation window, not new deforestation.
- General lesson for other presets (port, flood): a "was it plausibly in the pre-change state to begin with" precondition is likely needed wherever the same index-delta pattern can arise from two different real-world causes. Check before shipping a new preset threshold.

## Docker/WSL2 requirement

GDAL/rasterio on native Windows is a known tarpit (PROJECT.md §2.3) — the dev environment lives entirely in containers. Don't debug import/build errors on the host; reproduce inside `docker compose` first.
