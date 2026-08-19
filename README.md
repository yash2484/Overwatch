# Overwatch

Overwatch is a geospatial change-detection console for monitoring areas of interest with Sentinel-2 imagery. It selects usable imagery, detects meaningful change with deterministic rules, joins detections with GDELT news, and produces evidence-linked intelligence briefs.

The current demo is a read-only console over three seeded AOIs:

- Porto Alegre, flood
- Vizhinjam, port construction
- Novo Progresso, forest-loss research extension

## Current Demo

The primary demo state is Porto Alegre, using the date-matched Sentinel-2 pair from **2024-04-18 to 2024-05-08**.

- 104 flooding detections
- 1,841.2 ha of emitted detection area
- Validated Claude Sonnet 5 brief `1601`
- 11 date-valid news articles in the fusion window
- Every displayed detection and brief uses scene pair `17 -> 5392`

The Porto Alegre flood result has a single-case EMSN194 benchmark: precision **0.586**, recall **0.605**, F1 **0.595**, and IoU **0.424**. These numbers describe this date-matched flood case only.

The port construction workflow has an independent held-out OSCD benchmark over 10 urban-change scenes: precision **0.345**, recall **0.526**, F1 **0.417**, and IoU **0.263**. The shipped SSIM threshold `0.55` maximizes F1 on that split. Recall and F1 are the useful headline measures. Precision is lower because generic structural change also responds to non-target roads, roofs, bare soil, shadows, seasonal appearance, and other urban restructuring. This is a specificity limitation rather than a cloud-quality claim.

Forest loss is not presented as a reliable production capability. An August 2026 evaluation against the INPE PRODES five-window baseline closed forest as a research extension: precision **0.216**, recall **0.384**, F1 **0.277**, IoU **0.161**, with severe location dependence (Novo Progresso precision **0.011**). Two-date optical evidence does not reliably separate permanent clearing from harvest and seasonal vegetation change, so forest remains a future extension rather than a demonstrated product claim. Port and flood metrics do not generalize to forest.

## Architecture

```text
Sentinel-2 / Earth Search
          |
          v
Imagery gating + SCL usability
          |
          v
ChangeDetector -> PostGIS detections
          |             |
          |             +--> GeoJSON API -> React console
          v
GDELT fusion -> evidence validator -> brief API
```

- **Backend:** FastAPI, SQLAlchemy, PostGIS, Celery, Redis, Rasterio, Shapely, and Pydantic.
- **Imagery:** Earth Search STAC metadata plus windowed public COG reads. AOI-level SCL usability is the acceptance gate; catalog cloud cover ranks candidates without vetoing a usable AOI.
- **Detection:** deterministic NDVI/NDWI/SSIM rules, morphology, polygonization, and per-vertical presets. No LLM is used to decide whether pixels changed.
- **Evidence:** validated claims link to stored detection or article rows. Numeric detection claims are checked against linked geometry; reported news remains explicitly reported speech.
- **Frontend:** React 19, Vite, TypeScript, TanStack Query, MapLibre GL v5, deck.gl, and Tailwind CSS. The console supports scene comparison, swipe imagery, timeline selection, map-to-claim linking, and a read-only command palette.

## Quick Start

Requirements: Docker Desktop with WSL2, Node.js, and npm. Rasterio/GDAL work is intended to run inside Docker rather than native Windows Python.

1. Copy `.env.example` to `.env`. Keep secrets in `.env`; never commit it.
2. Start the backend dependencies and API:

   ```bash
   docker compose up -d postgis redis api
   ```

3. Start the host frontend. The repository's local Compose override maps the API to port `8001` because other local projects may use `8000`:

   ```bash
   cd frontend
   VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
   ```

   On Windows PowerShell:

   ```powershell
   $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8001"
   npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
   ```

4. Open:

   - Console: http://localhost:5173/
   - API docs: http://localhost:8001/docs
   - API health: http://localhost:8001/health

The Compose frontend is a baked production image without a source bind mount. Use the host Vite server for development and stop any Compose frontend container that occupies port `5173`.

To stop the demo without deleting database data:

```bash
docker compose stop api redis postgis frontend worker beat
```

To release WSL/Docker memory after stopping the stack on Windows:

```powershell
& "$env:ProgramFiles\Docker\Docker\DockerCli.exe" -Shutdown
wsl --shutdown
```

## Verification

Backend checks run in the API image and require PostGIS:

```bash
docker compose run --rm --no-deps api ruff check src tests
docker compose run --rm --no-deps api ruff format --check src tests
docker compose run --rm --no-deps api pytest -q
```

Frontend checks run on the host:

```bash
cd frontend
npm run build
npm run test -- --pool=forks --no-file-parallelism
```

The verified baseline is **405 backend tests passed, 1 documented xfail, and 18 frontend tests passed**. The xfail tracks the known limitation that flood precision on turbid water needs SWIR; the current ingestion set does not fetch SWIR bands.

## Known Limitations

- The flood benchmark is one date-matched Porto Alegre case, not a broad accuracy claim.
- Forest accuracy is closed as a research extension (2026-08-19). The five-window PRODES baseline showed precision **0.216**, recall **0.384**, F1 **0.277**, and IoU **0.161** with severe location dependence; two-date optical evidence did not reliably separate permanent clearing from harvest and seasonal vegetation change. Forest remains a future extension rather than a headline demo claim.
- GDELT fusion's remaining live gate requires a genuinely different network because the current IP has a long-lived rate-limit block.
- The frontend production bundle is approximately 2.06 MB, or 582 kB gzip. Code splitting is tracked as an optional follow-up.
- Real brief generation requires a funded Anthropic account and `OVERWATCH_ANTHROPIC_API_KEY`. The seeded demo data is read-only and data-grounded.

## Repository Workflow

`main` is integration-only. Substantive work starts on a typed branch such as `feat/<topic>`, `fix/<topic>`, `refactor/<topic>`, or `phase-<number>-<topic>`.

After a coherent feature, fix, or significant update passes its tests and review, create a focused local conventional commit automatically. Keep progress documentation in a separate checkpoint when practical. Never commit secrets, generated evidence, or exported session transcripts.

Pushes, pull requests, and merges require explicit approval. Pull requests are checked by GitHub Actions for branch naming, backend lint/tests, and frontend build.

## Project Documents

- [Project scope](PROJECT.md)
- [Design specifications](design-specs/)
- [Current progress and task queue](PROGRESS.md)
- [Domain context and engineering gotchas](CONTEXT.md)
- [Implementation plans](plans/)
