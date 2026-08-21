# Overwatch

Satellite change detection with an evidence trail. Give it a place and two dates, and it tells you what changed — with every figure in the written summary traceable back to a specific polygon in the database.

![The Overwatch console showing the May 2024 Porto Alegre floods: a swipe comparison of before and after Sentinel-2 imagery with detected flood polygons outlined, next to a generated intelligence brief](docs/demo.png)

This is a side project, built solo over about seven weeks. It runs on real Sentinel-2 imagery, real Copernicus and INPE ground truth, and a real Claude API key. The accuracy numbers below were measured against ground truth someone else drew, not estimated, and every limitation I know about is written down in [docs/limitations.md](docs/limitations.md).

## The two demo areas

**Porto Alegre, Brazil — the May 2024 Rio Grande do Sul floods.** Comparing 18 April against 8 May 2024, the detector emits **104 flood polygons covering 1,841 ha**. The brief written over them links to 11 news articles published in the same window.

**Vizhinjam, India — a deepwater transshipment terminal under construction.** Comparing February 2021 against February 2025 finds **16 construction polygons over 79 ha**, clustered on the terminal itself.

Both are read-only in the demo. The console lets you swipe between the before and after scenes, scrub a timeline, click a polygon to find the sentence that describes it, and click a sentence to fly to the polygons backing it.

## How it works

```text
Earth Search STAC  ──►  scene selection + SCL usability gate
                                    │
                        windowed COG reads, band harmonisation
                                    │
                        ChangeDetector  ──►  PostGIS polygons
                                    │                  │
                        GDELT news fusion              └──►  GeoJSON API ──► React console
                                    │
                        Claude writes a brief  ──►  deterministic validator  ──►  brief API
```

1. **Find usable imagery.** [`imagery/earth_search.py`](backend/src/overwatch/imagery/earth_search.py) queries the Earth Search STAC catalog for Sentinel-2 L2A scenes. Catalog cloud cover only ranks candidates — the actual gate is the fraction of the AOI that reads as usable in the scene's own SCL plane, so a scene with a cloud bank parked outside the AOI still qualifies.
2. **Read only what's needed.** Windowed reads pull red, green, blue, NIR and SCL straight from the public COGs. [`imagery/harmonize.py`](backend/src/overwatch/imagery/harmonize.py) applies the ESA baseline-04.00 DN offset so scenes from either side of the 2022 reprocessing are comparable.
3. **Detect change deterministically.** [`detection/detector.py`](backend/src/overwatch/detection/detector.py) computes spectral index deltas (NDVI, NDWI) and SSIM structural dissimilarity, ANDs a per-vertical set of threshold rules over the usable pixels, cleans the mask with morphological open/close, and polygonises what survives a minimum-area floor. **No model decides whether a pixel changed.**
4. **Join the news.** [`fusion/provider.py`](backend/src/overwatch/fusion/provider.py) retrieves candidate articles from GDELT and hands every one to a pure scorer that applies the date, place and topic gates. Retrieval and judgement are kept apart so the gating is unit-testable without a network.
5. **Write it up, then check it.** Claude receives the detection and article *rows* — never pixels — and writes a brief of typed claims. [`briefs/validator.py`](backend/src/overwatch/briefs/validator.py) then checks it: every observed claim must cite a real detection, quoted areas must reconcile against the linked geometry, dates must match a scene date, and a claim backed only by journalism has to read as reported speech and carry no figures. A failing draft goes back with its violations attached, up to a retry budget.

The point of step 5 is the direction of trust. The language model is the untrusted component; a few hundred lines of regex and arithmetic decide whether its output is allowed to be served.

## Accuracy

Every workflow is scored against public ground truth that someone else drew. Nothing here is self-graded, and all of it is re-derivable — commands in [Verification](#verification).

| workflow | benchmark | scenes | precision | recall | F1 | IoU |
|---|---|---|---|---|---|---|
| **Flood** | [Copernicus EMSN194](https://riskandrecovery.emergency.copernicus.eu/) | 1 event | 0.586 | 0.605 | **0.595** | **0.424** |
| **Construction** | [OSCD](https://rcdaudt.github.io/oscd/), held-out test | 10 | 0.325 | 0.280 | 0.301 | 0.177 |
| **Construction** | [OSCD](https://rcdaudt.github.io/oscd/), train | 14 | 0.189 | 0.271 | 0.222 | 0.125 |
| Forest | [INPE PRODES](https://terrabrasilis.dpi.inpe.br/) | 5 windows | 0.216 | 0.384 | 0.277 | 0.161 |

**Flood is the best result, and it's the one the demo shows.** EMSN194 is the Copernicus Emergency Management Service's analyst-delineated flood extent for Porto Alegre on 8 May 2024 — 922 hand-reviewed polygons, the reference product actual responders worked from. Against it the detector reaches **F1 0.595**, mapping 1,841 ha where the analysts mapped 1,775 ha on the pixels both could see. For a rules-based detector reading four bands, agreeing that closely with a human emergency-mapping team is the result I'd point at first. Its scope is depth rather than breadth: one event, one date, and CEMS built that extent partly from the same-day Sentinel-2 pass, so the truth isn't fully independent of what's being scored.

**Construction is the breadth check.** OSCD is a third-party academic benchmark — 24 Sentinel-2 pairs with independently hand-drawn masks, split 14 train / 10 held out. It answers the question a single case can't: does this hold up on scenes nobody tuned it for? It does, at a lower level, and two different limits set that level:

- **Precision** is specificity. A generic structural-change signal also fires on roads, roofs, bare soil, shadows and seasonal appearance.
- **Recall** is scope, and it's self-inflicted on purpose. The preset keeps only change within 2 km of the largest detection — right for watching one port, wrong for a benchmark that labels change across a whole city. On metro-wide scenes precision holds while recall falls away (chongqing 0.697/0.061, milano 0.823/0.085). OSCD scores this preset conservatively, which is the more useful direction for a benchmark to be wrong in.

Recall lands within 0.01 across the two splits (0.280 / 0.271), so sensitivity is a property of the method rather than of a lucky sample. And the SSIM threshold of `0.55` turns out to be the F1 maximum of a 0.40–0.70 sweep on the held-out split — set by eye on Vizhinjam imagery eleven days before the OSCD data was downloaded (`git log -S'threshold=0.55'`), which makes the agreement external validation rather than curve-fitting.

**Forest is a negative result, kept deliberately.** Two-date optical NDVI can't separate permanent clearing from harvest, seasonal change and haze, and PRODES showed it: F1 0.277 overall, collapsing to precision 0.011 at Novo Progresso. The vertical was closed and removed from the product rather than demoed quietly, and the run is kept in [`benchmarks/results/`](benchmarks/results/). Flood and construction numbers do not transfer to forest — this is the evidence they don't.

## Running it

You'll need Docker Desktop with WSL2, Node, and npm. GDAL work happens inside Docker rather than native Windows Python.

```bash
cp .env.example .env          # keep secrets here; never commit it
docker compose up -d postgis redis api
```

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

Then open the console at http://localhost:5173/, the API docs at http://localhost:8000/docs, and health at http://localhost:8000/health.

If you keep a local `docker-compose.override.yml` that remaps the API port (this repo's does, to `8001`, because port 8000 is usually taken), point Vite at it:

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5173 --strictPort
```

The Compose `frontend` service is a baked production image with no source bind-mount, so use the host Vite server for development and stop the container if it's holding port 5173.

To stop without losing the database:

```bash
docker compose stop api redis postgis frontend worker beat
```

## Verification

Backend checks run in the API image and need PostGIS:

```bash
docker compose run --rm --no-deps api ruff check src tests
docker compose run --rm --no-deps api ruff format --check src tests
docker compose exec -T api pytest -q
```

Frontend checks run on the host:

```bash
cd frontend
npm run build
npm run test -- --pool=forks --no-file-parallelism
```

Current baseline: **403 backend tests passed, 1 documented xfail** (404 collected) and **18 frontend tests passed**. The xfail is real and tracks the turbid-water limitation described below.

Re-derive the benchmark numbers (OSCD data must be downloaded into `data/oscd/` first — it isn't in the repo):

```bash
docker compose exec -T api python -m overwatch.eval.run_oscd --split test
docker compose exec -T api python -m overwatch.eval.run_oscd --split test --sweep
```

## What's next

1. **SWIR bands, then MNDWI in the flood preset.** Sediment-laden floodwater drags NDWI down and shaded vegetation pushes it up, so the two are hard to separate on four bands. Water absorbs SWIR almost completely whatever its sediment load, which makes the cut cleanly. The index functions are written and tested on `feat/swir-indices`; the ingestion change and an EMSN194 re-score are what's left.
2. **Close the validator's numeric gaps** — make unparseable area units fail closed, and cross-check percentages.
3. **Get the scheduler firing.** The weekly re-check logic is written and tested but has never run on its own; every pipeline run here was launched by hand.
4. **Code-split the frontend bundle**, currently 2.06 MB in one chunk.

Full detail, including the limitations behind each item and the ones with no fix planned yet, is in **[docs/limitations.md](docs/limitations.md)**.

## Stack

**Backend** — FastAPI, SQLAlchemy, PostGIS, Celery, Redis, Rasterio, Shapely, Pydantic v2, Alembic.
**Frontend** — React 19, Vite, TypeScript, TanStack Query, MapLibre GL v5, deck.gl, Tailwind.
**Evaluation** — a small harness in [`overwatch.eval`](backend/src/overwatch/eval/) that scores the shipped presets against OSCD, EMSN194 and PRODES, writing results with the truth archive's SHA-256 and the detector commit that produced them.

## Further reading

- [docs/limitations.md](docs/limitations.md) — limitations and what's next, in full
- [PROJECT.md](PROJECT.md) — scope, and what may and may not be claimed from each result
- [CONTEXT.md](CONTEXT.md) — domain glossary and the gotchas that cost the most time
- [PROGRESS.md](PROGRESS.md) — running log, including the accuracy corrections
- [design-specs/](design-specs/) and [plans/](plans/) — the design documents each phase was built from

## License

MIT. See [LICENSE](LICENSE).
