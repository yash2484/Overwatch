# Phase 0 — Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running, CI-green skeleton: Docker Compose brings up api / worker / beat / postgis / redis / frontend, rasterio imports in-container, `/health` responds, and GitHub Actions passes on push.

**Architecture:** Monorepo — `backend/` (FastAPI + Celery, single `pyproject.toml`, src layout) and `frontend/` (Vite + React + TS stub). Everything executes inside Docker (GDAL on native Windows is a known tarpit; host runs only `git` and `docker` commands). PostGIS and Redis are stock images with healthchecks.

**Tech Stack:** Python 3.12, FastAPI, Celery[redis], Pydantic v2 + pydantic-settings, rasterio, pytest, ruff · Node 22, Vite 6, React 18, TypeScript · postgis/postgis:16-3.4, redis:7-alpine · GitHub Actions.

## Global Constraints

- Python `>=3.12`; modern typing (`X | None`, `dict[str, str]`); Pydantic v2 only.
- All Python deps declared in `backend/pyproject.toml` — no requirements.txt anywhere.
- Tests run **inside the container**: `docker compose exec api pytest -v` (host has no Python env for this project).
- Lint gate is `ruff check .` **and** `ruff format --check .` — both must pass in CI.
- Env vars prefixed `OVERWATCH_`; `.env` is gitignored; `.env.example` is committed; the only real secret (Anthropic key) is NOT needed in Phase 0 and stays empty.
- Dev-only Postgres credentials (`overwatch` / `overwatch_dev`) are not secrets; they appear in compose and `.env.example` deliberately.
- Conventional commit prefixes (`feat:`, `chore:`, `ci:`); every commit ends with the Claude co-author line.
- Phase 0 exit gate (from design spec §7): `docker compose up` works end-to-end on the Windows machine; rasterio imports inside the container; CI green.

---

### Task 1: Repo hygiene files

**Files:**
- Create: `.gitignore`, `.env.example`, `README.md`
- Create: `backend/.dockerignore`, `frontend/.dockerignore`

**Interfaces:**
- Consumes: nothing.
- Produces: ignore rules later tasks rely on (`.env` never staged; `node_modules/` and caches out of Docker build contexts).

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/

# Node
node_modules/
dist/

# Env & secrets
.env

# OS / editor
.DS_Store
Thumbs.db

# Local data artifacts (rasters land here in Phase 1)
data/
*.tif
*.tiff
```

- [ ] **Step 2: Write `.env.example`**

```dotenv
# Dev-only defaults. Copy to .env for local overrides. Never commit .env.
OVERWATCH_DATABASE_URL=postgresql://overwatch:overwatch_dev@postgis:5432/overwatch
OVERWATCH_REDIS_URL=redis://redis:6379/0
OVERWATCH_ANTHROPIC_API_KEY=
OVERWATCH_FUSION_ENABLED=true
```

- [ ] **Step 3: Write `README.md`**

````markdown
# Overwatch

Geospatial change-detection intelligence platform: watch areas of interest via Sentinel-2 imagery, detect meaningful change deterministically, correlate detections with geotagged news (GDELT), and generate evidence-linked intelligence briefs where every claim traces to pixels, dates, or cited articles.

- Scope & strategy: [PROJECT.md](PROJECT.md)
- Design: [design-specs/2026-07-02-overwatch-mvp-design.md](design-specs/2026-07-02-overwatch-mvp-design.md)
- Session state: [PROGRESS.md](PROGRESS.md)

## Quick start (dev)

```bash
docker compose up --build
```

- API health: http://localhost:8000/health
- Frontend: http://localhost:5173
````

- [ ] **Step 4: Write `backend/.dockerignore`**

```
__pycache__
*.pyc
.pytest_cache
.ruff_cache
*.egg-info
```

- [ ] **Step 5: Write `frontend/.dockerignore`**

```
node_modules
dist
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example README.md backend/.dockerignore frontend/.dockerignore
git commit -m "chore: repo hygiene — gitignore, env example, README stub"
```

---

### Task 2: Backend package skeleton + Dockerfile (rasterio gate)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/overwatch/__init__.py`, `backend/src/overwatch/config.py`
- Create: `backend/Dockerfile`

**Interfaces:**
- Consumes: nothing.
- Produces: `overwatch.config.settings: Settings` with fields `database_url: str`, `redis_url: str`, `anthropic_api_key: str | None`, `fusion_enabled: bool` (env prefix `OVERWATCH_`). Docker image `overwatch-backend` that later tasks run pytest/uvicorn/celery in.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "overwatch"
version = "0.1.0"
description = "Geospatial change-detection intelligence platform"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "celery[redis]>=5.4",
    "rasterio>=1.4",
    "numpy>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "httpx>=0.27",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/overwatch"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `backend/src/overwatch/__init__.py`**

```python
"""Overwatch — geospatial change-detection intelligence platform."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `backend/src/overwatch/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values overridable via OVERWATCH_* env vars."""

    model_config = SettingsConfigDict(env_prefix="OVERWATCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://overwatch:overwatch_dev@postgis:5432/overwatch"
    redis_url: str = "redis://redis:6379/0"
    anthropic_api_key: str | None = None
    fusion_enabled: bool = True


settings = Settings()
```

- [ ] **Step 4: Write `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

COPY tests ./tests

EXPOSE 8000
CMD ["uvicorn", "overwatch.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: `tests/` doesn't exist until Task 3 — create an empty `backend/tests/__init__.py` in this task so the build succeeds:

```python
```

(empty file at `backend/tests/__init__.py`)

- [ ] **Step 5: Build the image and verify rasterio imports (the Phase-0 gate)**

Run: `docker build -t overwatch-backend ./backend`
Expected: build succeeds (rasterio manylinux wheels bundle GDAL — no apt packages needed).

Run: `docker run --rm overwatch-backend python -c "import rasterio, numpy; print('rasterio', rasterio.__version__, '| gdal', rasterio.gdal_version())"`
Expected: prints rasterio ≥ 1.4 and a GDAL 3.x version.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/src backend/Dockerfile backend/tests/__init__.py
git commit -m "feat: backend package skeleton, typed settings, Dockerfile with rasterio verified"
```

---

### Task 3: FastAPI app with /health (TDD, in-container)

**Files:**
- Create: `backend/src/overwatch/api/__init__.py`, `backend/src/overwatch/api/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `overwatch.api.main.app: FastAPI` — the ASGI app compose's `api` service serves; `GET /health` → `200 {"status": "ok"}` (the healthcheck URL every later phase's verification uses).

- [ ] **Step 1: Write the failing test at `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from overwatch.api.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker build -t overwatch-backend ./backend && docker run --rm overwatch-backend pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.api'`

- [ ] **Step 3: Write minimal implementation**

`backend/src/overwatch/api/__init__.py`: empty file.

`backend/src/overwatch/api/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="Overwatch API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker build -t overwatch-backend ./backend && docker run --rm overwatch-backend pytest tests/test_health.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/api backend/tests/test_health.py
git commit -m "feat: FastAPI app with /health endpoint (TDD)"
```

---

### Task 4: Celery app + ping task (TDD, in-container)

**Files:**
- Create: `backend/src/overwatch/workers/__init__.py`, `backend/src/overwatch/workers/celery_app.py`
- Test: `backend/tests/test_celery_app.py`

**Interfaces:**
- Consumes: `overwatch.config.settings.redis_url` (Task 2).
- Produces: `overwatch.workers.celery_app.celery_app: Celery` (the `-A` target for worker and beat services) and task `overwatch.ping` returning `"pong"`.

- [ ] **Step 1: Write the failing test at `backend/tests/test_celery_app.py`**

```python
from overwatch.workers.celery_app import ping


def test_ping_task_runs_synchronously() -> None:
    assert ping.run() == "pong"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker build -t overwatch-backend ./backend && docker run --rm overwatch-backend pytest tests/test_celery_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.workers'`

- [ ] **Step 3: Write minimal implementation**

`backend/src/overwatch/workers/__init__.py`: empty file.

`backend/src/overwatch/workers/celery_app.py`:

```python
from celery import Celery

from overwatch.config import settings

celery_app = Celery("overwatch", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"


@celery_app.task(name="overwatch.ping")
def ping() -> str:
    return "pong"
```

- [ ] **Step 4: Run full suite to verify green**

Run: `docker build -t overwatch-backend ./backend && docker run --rm overwatch-backend pytest -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/workers backend/tests/test_celery_app.py
git commit -m "feat: Celery app wired to Redis with ping task (TDD)"
```

---

### Task 5: Docker Compose full stack

**Files:**
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `overwatch-backend` image behavior (Tasks 2–4): uvicorn CMD, `celery -A overwatch.workers.celery_app`, `OVERWATCH_*` env vars.
- Produces: services `postgis`, `redis`, `api` (:8000), `worker`, `beat`, `frontend` (:5173) — the names every later phase's compose commands target.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  postgis:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: overwatch
      POSTGRES_PASSWORD: overwatch_dev
      POSTGRES_DB: overwatch
    ports:
      - "5432:5432"
    volumes:
      - postgis_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U overwatch -d overwatch"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: ./backend
    environment:
      OVERWATCH_DATABASE_URL: postgresql://overwatch:overwatch_dev@postgis:5432/overwatch
      OVERWATCH_REDIS_URL: redis://redis:6379/0
    ports:
      - "8000:8000"
    depends_on:
      postgis:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build: ./backend
    command: celery -A overwatch.workers.celery_app worker --loglevel=info
    environment:
      OVERWATCH_REDIS_URL: redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy

  beat:
    build: ./backend
    command: celery -A overwatch.workers.celery_app beat --loglevel=info
    environment:
      OVERWATCH_REDIS_URL: redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    depends_on:
      - api

volumes:
  postgis_data:
```

- [ ] **Step 2: Bring up the backend stack (frontend doesn't exist yet — start the other five)**

Run: `docker compose up -d --build postgis redis api worker beat`
Expected: five containers running; api waits for healthy postgis+redis.

- [ ] **Step 3: Verify each service**

Run: `curl -s http://localhost:8000/health`
Expected: `{"status":"ok"}`

Run: `docker compose exec postgis psql -U overwatch -d overwatch -c "SELECT PostGIS_version();"`
Expected: a `3.4.x` version row.

Run: `docker compose exec worker celery -A overwatch.workers.celery_app inspect ping`
Expected: `-> celery@...: OK pong`

Run: `docker compose logs beat --tail 5`
Expected: beat started, no tracebacks.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: docker compose stack — postgis, redis, api, worker, beat"
```

---

### Task 6: Frontend stub (Vite + React + TS)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/Dockerfile`

**Interfaces:**
- Consumes: compose `frontend` service definition (Task 5).
- Produces: dev server on :5173 rendering "Overwatch — scaffold OK"; `npm run build` type-checks and bundles (the CI target).

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "overwatch-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.6.3",
    "vite": "^6.0.3"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { host: "0.0.0.0", port: 5173 },
});
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src", "vite.config.ts"]
}
```

- [ ] **Step 4: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Overwatch</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write `frontend/src/main.tsx`**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 6: Write `frontend/src/App.tsx`**

```tsx
export function App() {
  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>Overwatch</h1>
      <p>Scaffold OK — Phase 0.</p>
    </main>
  );
}
```

- [ ] **Step 7: Write `frontend/Dockerfile`**

```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
```

- [ ] **Step 8: Bring up frontend and verify**

Run: `docker compose up -d --build frontend`
Run: `curl -s http://localhost:5173 | findstr /C:"Overwatch"` (or fetch in sandbox)
Expected: HTML containing the Overwatch root page.

- [ ] **Step 9: Commit**

```bash
git add frontend
git commit -m "feat: Vite React TS frontend stub served by compose"
```

---

### Task 7: CI workflow (green from Phase 0)

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `backend/pyproject.toml` dev extras (ruff, pytest); `frontend/package.json` build script.
- Produces: `CI` workflow — the green-gate every later phase pushes against.

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check . && ruff format --check .
      - name: Test
        run: pytest -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Install
        run: npm install
      - name: Build
        run: npm run build
```

- [ ] **Step 2: Run lint locally (in-container) before pushing — CI must not be the first place ruff runs**

Run: `docker compose exec api ruff check . && docker compose exec api ruff format --check .`
Expected: no violations. If format check fails, run `docker compose exec api ruff format .`, copy fixes back is NOT possible (container copy) — instead fix source files on host to match and rebuild.

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: backend lint+test and frontend build workflows"
git push
```

- [ ] **Step 4: Verify CI green**

Run: `gh run watch` (or `gh run list --limit 1`)
Expected: `CI` conclusion `success` for both jobs.

---

### Task 8: Phase-gate verification + PROGRESS.md

**Files:**
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: recorded, evidence-backed Phase 0 completion.

- [ ] **Step 1: Full clean-slate verification (the design-spec §7 Phase 0 gate)**

```bash
docker compose down
docker compose up -d --build
```

Then verify, in order:
1. `curl -s http://localhost:8000/health` → `{"status":"ok"}`
2. `docker compose exec api python -c "import rasterio; print(rasterio.__version__)"` → version prints
3. `docker compose exec api pytest -v` → 2 passed
4. `docker compose exec worker celery -A overwatch.workers.celery_app inspect ping` → pong
5. `docker compose exec postgis psql -U overwatch -d overwatch -c "SELECT PostGIS_version();"` → 3.4.x
6. Frontend responds on :5173
7. `gh run list --limit 1` → success

- [ ] **Step 2: Update `PROGRESS.md`** — move Phase 0 into "Built & verified" with the exact verification evidence from Step 1; set "Current phase" to "Phase 1 — Imagery ingestion (next)"; note any deviations.

- [ ] **Step 3: Commit and push**

```bash
git add PROGRESS.md
git commit -m "chore: record Phase 0 verification in PROGRESS.md"
git push
```

---

## Self-Review Notes

- **Spec coverage:** design-spec §7 Phase 0 = repo ✔ (exists), Compose 6 services ✔ (Task 5+6), pyproject ✔ (Task 2), CI green ✔ (Task 7), PROGRESS.md ✔ (Task 8), rasterio-in-container gate ✔ (Task 2 Step 5, re-verified Task 8).
- **Placeholders:** none — every file's full content is inline.
- **Type consistency:** `settings` fields referenced in `celery_app.py` match `config.py`; compose `-A overwatch.workers.celery_app` matches the module path; test imports match created modules.
- **Deliberate deferrals (not gaps):** no DB driver dep yet (Phase 3 adds SQLAlchemy/GeoAlchemy2 when tables exist — YAGNI); beat has no schedule (Phase 3 wires it); frontend has no MapLibre (Phase 6).
