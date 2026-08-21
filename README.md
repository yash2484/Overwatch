# Overwatch

Satellite change detection with an evidence trail. Give it a place and two dates, and it tells you what changed. Every figure in the written summary traces back to a specific polygon in the database.

![The Overwatch console showing the May 2024 Porto Alegre floods: a swipe comparison of before and after Sentinel-2 imagery with detected flood polygons outlined, next to a generated intelligence brief](docs/demo.png)

Built solo over seven weeks, on real Sentinel-2 imagery from the Earth Search catalog, scored against ground truth published by Copernicus and INPE. The detector is deterministic rules over spectral indices, and a language model writes the summary only after the numbers exist.

## What it finds

**Porto Alegre, Brazil.** The May 2024 Rio Grande do Sul floods. Comparing 18 April against 8 May 2024, the detector emits **104 flood polygons covering 1,841 ha**, and the brief written over them links 11 news articles from the same window.

**Vizhinjam, India.** A deepwater transshipment terminal mid-construction. Comparing February 2021 against February 2025 finds **16 construction polygons over 79 ha**, clustered on the terminal.

The console is read-only. Swipe between the before and after scenes, scrub the timeline, click a polygon to find the sentence describing it, or click a sentence to fly to the polygons behind it.

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

1. **Find usable imagery.** [`imagery/earth_search.py`](backend/src/overwatch/imagery/earth_search.py) queries the Earth Search STAC catalog for Sentinel-2 L2A scenes. Catalog cloud cover ranks candidates. The gate is the fraction of the AOI reading as usable in the scene's own SCL plane, so a scene with a cloud bank parked outside the AOI still qualifies.
2. **Read only what's needed.** Windowed reads pull red, green, blue, NIR and SCL straight from the public COGs. [`imagery/harmonize.py`](backend/src/overwatch/imagery/harmonize.py) applies the ESA baseline-04.00 DN offset so scenes from either side of the 2022 reprocessing stay comparable.
3. **Detect change deterministically.** [`detection/detector.py`](backend/src/overwatch/detection/detector.py) computes spectral index deltas (NDVI, NDWI) and SSIM structural dissimilarity, ANDs a per-vertical set of threshold rules over the usable pixels, cleans the mask with morphological open/close, and polygonises what survives a minimum-area floor. **No model decides whether a pixel changed.**
4. **Join the news.** [`fusion/provider.py`](backend/src/overwatch/fusion/provider.py) retrieves candidate articles from GDELT and hands every one to a pure scorer that applies the date, place and topic gates. Retrieval and judgement stay apart, so the gating is unit-testable without a network.
5. **Write it up, then check it.** Claude receives the detection and article *rows*, never pixels, and writes a brief of typed claims. [`briefs/validator.py`](backend/src/overwatch/briefs/validator.py) then checks it: every observed claim must cite a real detection, quoted areas must reconcile against the linked geometry, dates must match a scene date, and a claim backed only by journalism has to read as reported speech and carry no figures. A failing draft goes back with its violations attached, up to a retry budget.

Step 5 inverts the usual arrangement. Claude is the untrusted component here, and a few hundred lines of regex and arithmetic decide whether its output reaches the API.

## Accuracy

Every workflow is scored against public ground truth someone else drew. Commands to re-derive all of it are in [Verification](#verification).

| workflow | benchmark | precision | recall | F1 | IoU |
|---|---|---|---|---|---|
| **Flood** | [Copernicus EMSN194](https://riskandrecovery.emergency.copernicus.eu/) | 0.586 | 0.605 | **0.595** | **0.424** |
| **Construction** | [OSCD](https://rcdaudt.github.io/oscd/), held-out test | 0.325 | 0.280 | 0.301 | 0.177 |
| Forest | [INPE PRODES](https://terrabrasilis.dpi.inpe.br/) | 0.216 | 0.384 | 0.277 | 0.161 |

**Flood.** EMSN194 is the Copernicus Emergency Management Service's flood extent for Porto Alegre on 8 May 2024: 922 polygons drawn and reviewed by analysts, the reference product responders worked from. Against it the detector reaches **F1 0.595**, mapping 1,841 ha where the analysts mapped 1,775 ha on pixels both could see. It covers one event on one date, and CEMS built that extent partly from the same-day Sentinel-2 pass, so the truth is not fully independent of what it scores.

**Construction.** OSCD is a third-party academic benchmark: 24 Sentinel-2 pairs with independently drawn masks, split 14 train and 10 held out. It answers what a single case cannot, which is whether this holds up on scenes nobody tuned it against.

The shipped SSIM threshold of `0.55` turns out to be the F1 maximum of a 0.40 to 0.70 sweep on that split. I set it by eye on Vizhinjam imagery eleven days before the OSCD data was downloaded (`git log -S'threshold=0.55'`), so the agreement is external validation rather than a curve fitted to the benchmark.

Recall then holds within 0.01 across both splits, with train scoring 0.189 / 0.271 / 0.222 / 0.125. Sensitivity is a property of the method, not of one lucky sample.

Both scores sit under a 2 km spatial prior built for watching a single port, which a whole-city benchmark penalises. [docs/limitations.md](docs/limitations.md) has the detail.

**Forest.** Two-date optical NDVI cannot separate permanent clearing from harvest and seasonal change, and PRODES showed it: F1 0.277, collapsing to precision 0.011 at Novo Progresso. I closed the vertical and pulled it from the product. The run stays in [`benchmarks/results/`](benchmarks/results/) as the reason flood and construction numbers do not transfer.

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

If you keep a local `docker-compose.override.yml` remapping the API port (this repo's does, to `8001`, since 8000 is usually taken), point Vite at it:

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

Current baseline: **403 backend tests passed, 1 documented xfail** (404 collected) and **18 frontend tests passed**. The xfail is real, and it tracks the turbid-water limitation in [docs/limitations.md](docs/limitations.md).

Re-derive the benchmark numbers. OSCD data has to be downloaded into `data/oscd/` first, since it is not in the repo:

```bash
docker compose exec -T api python -m overwatch.eval.run_oscd --split test
docker compose exec -T api python -m overwatch.eval.run_oscd --split test --sweep
```

## What's next

1. **SWIR bands, then MNDWI in the flood preset.** Sediment-laden floodwater drags NDWI down while shaded vegetation pushes it up, so four bands cannot separate them. Water absorbs SWIR whatever its sediment load, which makes the cut cleanly. The index functions are written and tested on `feat/swir-indices`; the ingestion change and an EMSN194 re-score are what's left.
2. **Close the validator's numeric gaps.** Unparseable area units should fail closed, and percentages need cross-checking.
3. **Get the scheduler firing.** The weekly re-check logic is written and tested but has never run on its own. Every pipeline run here was launched by hand.
4. **Code-split the frontend bundle**, currently 2.06 MB in one chunk.

Full detail, including the limitations behind each item and the ones with no fix planned yet, is in **[docs/limitations.md](docs/limitations.md)**.

## Stack

**Backend:** FastAPI, SQLAlchemy, PostGIS, Celery, Redis, Rasterio, Shapely, Pydantic v2, Alembic.
**Frontend:** React 19, Vite, TypeScript, TanStack Query, MapLibre GL v5, deck.gl, Tailwind.
**Evaluation:** a small harness in [`overwatch.eval`](backend/src/overwatch/eval/) that scores the shipped presets against OSCD, EMSN194 and PRODES, writing results with the truth archive's SHA-256 and the detector commit behind them.

## Further reading

- [docs/limitations.md](docs/limitations.md): limitations and what's next, in full
- [PROJECT.md](PROJECT.md): scope, and what may and may not be claimed from each result
- [CONTEXT.md](CONTEXT.md): domain glossary and the gotchas that cost the most time
- [PROGRESS.md](PROGRESS.md): running log, including the accuracy corrections
- [design-specs/](design-specs/) and [plans/](plans/): the design documents behind each phase

## License

MIT. See [LICENSE](LICENSE).
