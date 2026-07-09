# Phase 3 — Detection Persistence + API + Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full pipeline: `POST /aois/{slug}/jobs` → Celery chain (ingest before → ingest after → detect) → `Detection` polygons persisted to PostGIS → queryable by spatial predicate; idempotent on re-run; failures retry visibly.

**Architecture:** Three new tables (`aois`, `jobs`, `detections` — design doc `design-specs/2026-07-07-phase-3-persistence-api-jobs-design.md`; briefs/news tables deferred to Phases 4–5). Job state lives in Postgres, not Redis; polling reads the `jobs` row. Scene pairs are chosen by the existing `find_usable_scene` gate over submitted date windows. Detections use replace-set idempotency on the `(aoi, before_scene, after_scene)` pair. Sync SQLAlchemy everywhere (API endpoints are `def`, run in FastAPI's threadpool — approved deviation, design doc §1.4).

**Tech Stack:** FastAPI + pydantic v2, SQLAlchemy 2 + GeoAlchemy2 + alembic, Celery 5 (chain, autoretry, beat), PostGIS, pyproj/shapely. **No new dependencies.**

## Global Constraints

- **Everything Python runs in-container**: `docker compose exec api pytest -q`, `docker compose exec api ruff check .` — never on the Windows host. Start Docker Desktop first (manual-start on this machine).
- **Branch:** `phase-3-persistence-api-jobs` (already created; kickoff commit has the design doc). Commit per task. User merges via GitHub PR — end with compare URL `https://github.com/yash2484/Overwatch/compare/main...phase-3-persistence-api-jobs`. Direct push to main is denied; no `gh` CLI.
- **TDD:** red → green per task; negative tests are first-class. Before each commit run `docker compose exec api ruff check . && docker compose exec api ruff format .`.
- **Source is bind-mounted** into the api container (Phases 1–2 ran tests without rebuilds). Celery does NOT autoreload: after touching `workers/*`, run `docker compose restart worker beat`.
- **Structured errors everywhere:** `{"error": {"code": str, "message": str, "detail": any|null}}` — including FastAPI validation errors.
- **Tunable numbers live in config/presets, never hardcoded:** the 500 km² cap goes in `Settings.max_aoi_km2`.
- **Additive only:** `scenes` table and all Phase 1/2 modules are extended, never renamed/reshaped. Exception approved in design: `detection/cli.py:_load_window` refactors to use the new shared harmonize module (Task 8).
- **DB tests** need the compose/CI postgis service; they use the existing session-scoped `migrated_db` fixture and clean up rows with slug prefix `t3-` (fixture in Task 3). Never delete the showcase slugs (`vizhinjam`, `novo-progresso`, `porto-alegre`).
- Existing interfaces consumed (do not modify):
  - `overwatch.db.engine.session_scope()` — commit-on-success context manager; `get_engine()`.
  - `overwatch.db.scenes.upsert_scene(session, scene: SceneMeta, aoi_slug, window_geometry: Polygon, usable_fraction, meta=None) -> int` (idempotent on `(stac_id, aoi_slug)`).
  - `overwatch.imagery.gating.find_usable_scene(provider, geometry, start, end, *, max_cloud_pct=60.0, min_usable=0.7, bands=(...)) -> SceneSelection | None`; `SceneSelection(scene: SceneMeta, window: AOIWindow, usable_fraction: float)`; `MIN_USABLE_FRACTION = 0.7`.
  - `overwatch.imagery.models.SceneMeta` (pydantic; `model_dump(mode="json")` round-trips via `model_validate`) and `AOIWindow` (dataclass: `bands`, `scl`, `transform`, `epsg`).
  - `overwatch.imagery.provider.ImageryProvider` protocol; `overwatch.imagery.earth_search.EarthSearchProvider`.
  - `overwatch.detection.detector.ClassicalChangeDetector().detect(before, after, preset) -> list[Detection]` (raises `ValueError` on CRS/shape/transform mismatch); `overwatch.detection.presets.VERTICAL_PRESETS: dict[str, DetectionPreset]`.
  - `overwatch.detection.models.Detection` — dataclass: `geometry: Polygon` (projected CRS), `epsg: int`, `area_m2`, `change_type: ChangeType` (StrEnum), `magnitude`, `confidence`, `contributing_indices: dict[str, float]`.
  - `overwatch.aois.SHOWCASE_AOIS: dict[str, AOI]` — `.slug`, `.name`, `.vertical`, `.geometry() -> Polygon`.
  - `tests/synthetic.py` — `flat_window(profile, ...)`, `inject_rect(window, profile, rect, ...)`, profiles `FOREST`/`BARE`/..., `EPSG = 32643`, `SCL_CLOUD_HIGH = 9`.

---

### Task 1: Schema migration 0002 + ORM models (aois, jobs, detections)

**Files:**
- Modify: `backend/src/overwatch/db/models.py`
- Create: `backend/alembic/versions/0002_create_aois_jobs_detections.py`
- Test: `backend/tests/test_db_schema.py`

**Interfaces:**
- Consumes: `Base`, `Scene` from `overwatch.db.models`.
- Produces: ORM classes `Aoi` (`id, slug, name, vertical, geom, cadence_days, last_checked_at, created_at, updated_at`), `Job` (`id: UUID, aoi_id, status, stage, params, before_scene_id, after_scene_id, detection_count, error, attempts, created_at, updated_at`), `DetectionEvent` (`id, aoi_id, job_id, before_scene_id, after_scene_id, geom, src_epsg, area_m2, change_type, magnitude, confidence, contributing_indices, created_at`). All later DB tasks import these exact names.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db_schema.py`:

```python
"""Phase 3 schema: tables + GiST indexes exist after migration (design doc §2)."""

from sqlalchemy import inspect, text

from overwatch.db.engine import get_engine


def test_phase3_tables_exist(migrated_db: None) -> None:
    inspector = inspect(get_engine())
    for table in ("aois", "jobs", "detections"):
        assert inspector.has_table(table), f"missing table {table}"


def test_geometry_columns_have_gist_indexes(migrated_db: None) -> None:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('aois', 'detections')")
        ).all()
    defs = {row.indexname: row.indexdef for row in rows}
    assert "gist" in defs["ix_aois_geom"].lower()
    assert "gist" in defs["ix_detections_geom"].lower()
    assert "ix_detections_pair" in defs  # replace-set delete goes through this


def test_jobs_cascade_from_aois(migrated_db: None) -> None:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conrelid = 'jobs'::regclass AND confrelid = 'aois'::regclass"
            )
        ).all()
    assert rows and rows[0].confdeltype == "c"  # ON DELETE CASCADE
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_db_schema.py -q`
Expected: FAIL — `assert False` (missing table aois).

- [ ] **Step 3: Add the ORM models**

Append to `backend/src/overwatch/db/models.py` (extend the imports at top to add `uuid`, `ForeignKey`, and the PG `UUID` type):

```python
import uuid  # add at top with the other stdlib imports

from sqlalchemy import ForeignKey  # merge into the existing sqlalchemy import
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # merge into the postgresql import
```

```python
class Aoi(Base):
    """User-defined area of interest (design doc §2). slug is the natural key."""

    __tablename__ = "aois"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vertical: Mapped[str] = mapped_column(Text, nullable=False)  # port | forest | flood
    geom = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    cadence_days: Mapped[int | None] = mapped_column(Integer)  # null = no re-check
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Job(Base):
    """One detection-pipeline run; polled via the API (design doc §2)."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    aoi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aois.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # queued|running|succeeded|failed
    stage: Mapped[str | None] = mapped_column(Text)  # ingest_before|ingest_after|detect
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    before_scene_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("scenes.id"))
    after_scene_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("scenes.id"))
    detection_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DetectionEvent(Base):
    """One persisted change-event polygon (design doc §2). Named to avoid clashing with
    the engine's Detection dataclass."""

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aoi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aois.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    before_scene_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scenes.id"), nullable=False
    )
    after_scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scenes.id"), nullable=False)
    geom = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    src_epsg: Mapped[int] = mapped_column(Integer, nullable=False)
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    contributing_indices: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/0002_create_aois_jobs_detections.py`:

```python
"""create aois, jobs, detections

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-07

"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aois",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("cadence_days", sa.Integer(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.execute("CREATE INDEX ix_aois_geom ON aois USING gist (geom)")

    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "aoi_id",
            sa.BigInteger(),
            sa.ForeignKey("aois.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("before_scene_id", sa.BigInteger(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("after_scene_id", sa.BigInteger(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("detection_count", sa.Integer(), nullable=True),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_jobs_aoi_id", "jobs", ["aoi_id"])

    op.create_table(
        "detections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "aoi_id",
            sa.BigInteger(),
            sa.ForeignKey("aois.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("before_scene_id", sa.BigInteger(), sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column("after_scene_id", sa.BigInteger(), sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("src_epsg", sa.Integer(), nullable=False),
        sa.Column("area_m2", sa.Float(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("magnitude", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "contributing_indices", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.execute("CREATE INDEX ix_detections_geom ON detections USING gist (geom)")
    op.create_index(
        "ix_detections_pair", "detections", ["aoi_id", "before_scene_id", "after_scene_id"]
    )


def downgrade() -> None:
    op.drop_table("detections")
    op.drop_table("jobs")
    op.drop_table("aois")
```

- [ ] **Step 5: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_db_schema.py -q`
Expected: `3 passed` (the `migrated_db` fixture runs `alembic upgrade head`).

- [ ] **Step 6: Full suite + lint, then commit**

Run: `docker compose exec api pytest -q` → Expected: `79 passed` (76 baseline + 3).
Run: `docker compose exec api ruff check . && docker compose exec api ruff format .`

```bash
git add backend/src/overwatch/db/models.py backend/alembic/versions/0002_create_aois_jobs_detections.py backend/tests/test_db_schema.py
git commit -m "feat(phase-3): aois/jobs/detections schema with GiST indexes (migration 0002)"
```

---

### Task 2: Geodesy helpers (pure)

Geodesic area for the 500 km² cap; UTM→WGS84 reprojection for storing engine detections.

**Files:**
- Create: `backend/src/overwatch/geodesy.py`
- Test: `backend/tests/test_geodesy.py`

**Interfaces:**
- Consumes: pyproj, shapely only.
- Produces: `geodesic_area_km2(polygon: Polygon) -> float` (EPSG:4326 in, km² out); `to_wgs84(geometry: Polygon, src_epsg: int) -> Polygon`. Used by Tasks 5 (cap) and 7 (persist).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_geodesy.py`:

```python
"""Geodesic area + reprojection helpers."""

from pyproj import Transformer
from shapely.geometry import box

from overwatch.geodesy import geodesic_area_km2, to_wgs84


def test_one_degree_equatorial_box_area() -> None:
    # 1 deg x 1 deg at the equator is about 12,300 km^2
    assert 12_000 < geodesic_area_km2(box(0.0, 0.0, 1.0, 1.0)) < 12_700


def test_vizhinjam_bbox_is_well_under_cap() -> None:
    area = geodesic_area_km2(box(76.960, 8.355, 77.010, 8.395))
    assert 20 < area < 30  # about 24 km^2


def test_to_wgs84_round_trips_utm() -> None:
    fwd = Transformer.from_crs(4326, 32643, always_xy=True)
    x, y = fwd.transform(76.98, 8.37)
    utm_square = box(x - 500, y - 500, x + 500, y + 500)
    lonlat = to_wgs84(utm_square, 32643)
    assert abs(lonlat.centroid.x - 76.98) < 1e-3
    assert abs(lonlat.centroid.y - 8.37) < 1e-3


def test_to_wgs84_is_noop_for_4326() -> None:
    square = box(0, 0, 1, 1)
    assert to_wgs84(square, 4326) is square
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_geodesy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.geodesy'`.

- [ ] **Step 3: Implement**

`backend/src/overwatch/geodesy.py`:

```python
"""Geodesic + CRS helpers shared by API validation and detection persistence."""

from functools import lru_cache

import shapely.ops
from pyproj import Geod, Transformer
from shapely.geometry import Polygon

_GEOD = Geod(ellps="WGS84")


def geodesic_area_km2(polygon: Polygon) -> float:
    """Unsigned geodesic area of an EPSG:4326 polygon, in square kilometres."""
    area_m2, _ = _GEOD.geometry_area_perimeter(polygon)
    return abs(area_m2) / 1_000_000.0


@lru_cache(maxsize=16)
def _to_wgs84_transformer(src_epsg: int) -> Transformer:
    return Transformer.from_crs(src_epsg, 4326, always_xy=True)


def to_wgs84(geometry: Polygon, src_epsg: int) -> Polygon:
    """Reproject a polygon from a projected CRS to EPSG:4326 (lon/lat)."""
    if src_epsg == 4326:
        return geometry
    return shapely.ops.transform(_to_wgs84_transformer(src_epsg).transform, geometry)
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_geodesy.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/geodesy.py backend/tests/test_geodesy.py
git commit -m "feat(phase-3): geodesic area + UTM->WGS84 helpers"
```

---

### Task 3: Test fixtures + AOI repository + seed CLI

**Files:**
- Modify: `backend/tests/conftest.py`
- Create: `backend/src/overwatch/db/aois.py`
- Create: `backend/src/overwatch/db/seed.py`
- Test: `backend/tests/test_aois_db.py`, `backend/tests/test_seed.py`

**Interfaces:**
- Consumes: `Aoi` ORM (Task 1); `SHOWCASE_AOIS`; `session_scope`.
- Produces:
  - conftest fixtures `db_session` (function-scoped `Session` over a migrated DB) and `clean_t3` (deletes `t3-%` slug rows from `aois` and `scenes` after the test) — used by every later DB/API test.
  - `upsert_aoi(session, *, slug, name, vertical, geometry: Polygon, cadence_days: int | None = None) -> int` (idempotent on slug; reseeding never clobbers `cadence_days`/`last_checked_at`), `get_aoi(session, slug) -> Aoi | None`, `list_aois(session) -> list[Aoi]`, `delete_aoi(session, slug) -> bool`, `stamp_checked(session, aoi_id, when: datetime) -> None`.
  - `python -m overwatch.db.seed` — idempotent showcase seeder.

- [ ] **Step 1: Add the fixtures**

Append to `backend/tests/conftest.py`:

```python
from collections.abc import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from overwatch.db.engine import session_scope


@pytest.fixture()
def db_session(migrated_db: None) -> Iterator[Session]:
    with session_scope() as session:
        yield session


@pytest.fixture()
def clean_t3(migrated_db: None) -> Iterator[None]:
    """Delete Phase-3 test rows (slug prefix t3-) after the test; cascades jobs/detections."""
    yield
    with session_scope() as session:
        session.execute(text("DELETE FROM aois WHERE slug LIKE 't3-%'"))
        session.execute(text("DELETE FROM scenes WHERE aoi_slug LIKE 't3-%'"))
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_aois_db.py`:

```python
"""AOI repository: idempotent upsert, get/list/delete, cascade."""

from datetime import UTC, datetime

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import delete_aoi, get_aoi, list_aois, stamp_checked, upsert_aoi

GEOM = box(76.96, 8.35, 77.01, 8.40)


def test_upsert_is_idempotent_on_slug(db_session: Session, clean_t3: None) -> None:
    first = upsert_aoi(db_session, slug="t3-up", name="A", vertical="port", geometry=GEOM)
    second = upsert_aoi(db_session, slug="t3-up", name="A2", vertical="port", geometry=GEOM)
    assert first == second
    assert get_aoi(db_session, "t3-up").name == "A2"


def test_upsert_does_not_clobber_cadence(db_session: Session, clean_t3: None) -> None:
    aoi_id = upsert_aoi(
        db_session, slug="t3-cad", name="C", vertical="forest", geometry=GEOM, cadence_days=7
    )
    stamp_checked(db_session, aoi_id, datetime(2026, 7, 1, tzinfo=UTC))
    upsert_aoi(db_session, slug="t3-cad", name="C", vertical="forest", geometry=GEOM)
    row = get_aoi(db_session, "t3-cad")
    assert row.cadence_days == 7
    assert row.last_checked_at is not None


def test_get_list_delete(db_session: Session, clean_t3: None) -> None:
    upsert_aoi(db_session, slug="t3-del", name="D", vertical="flood", geometry=GEOM)
    assert any(a.slug == "t3-del" for a in list_aois(db_session))
    assert delete_aoi(db_session, "t3-del") is True
    assert get_aoi(db_session, "t3-del") is None
    assert delete_aoi(db_session, "t3-del") is False
```

`backend/tests/test_seed.py`:

```python
"""Showcase seeder is idempotent."""

from sqlalchemy.orm import Session

from overwatch.aois import SHOWCASE_AOIS
from overwatch.db.aois import get_aoi
from overwatch.db.seed import seed


def test_seed_twice_yields_three_stable_rows(db_session: Session) -> None:
    first = seed()
    second = seed()
    assert first == second
    assert len(first) == len(SHOWCASE_AOIS) == 3
    db_session.expire_all()
    for slug, aoi in SHOWCASE_AOIS.items():
        row = get_aoi(db_session, slug)
        assert row is not None and row.vertical == aoi.vertical
```

- [ ] **Step 3: Run to verify they fail**

Run: `docker compose exec api pytest tests/test_aois_db.py tests/test_seed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.db.aois'`.

- [ ] **Step 4: Implement the repository**

`backend/src/overwatch/db/aois.py`:

```python
"""AOI persistence — idempotent upsert on the slug natural key (design doc §2)."""

from datetime import datetime

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from overwatch.db.models import Aoi


def upsert_aoi(
    session: Session,
    *,
    slug: str,
    name: str,
    vertical: str,
    geometry: Polygon,
    cadence_days: int | None = None,
) -> int:
    """Insert or update by slug; returns the stable row id.

    Re-seeding refreshes name/vertical/geom but never clobbers cadence_days or
    last_checked_at (user-owned scheduling state).
    """
    geom = from_shape(geometry, srid=4326)
    stmt = (
        insert(Aoi)
        .values(slug=slug, name=name, vertical=vertical, geom=geom, cadence_days=cadence_days)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={"name": name, "vertical": vertical, "geom": geom, "updated_at": func.now()},
        )
        .returning(Aoi.id)
    )
    return session.execute(stmt).scalar_one()


def get_aoi(session: Session, slug: str) -> Aoi | None:
    return session.scalar(select(Aoi).where(Aoi.slug == slug))


def list_aois(session: Session) -> list[Aoi]:
    return list(session.scalars(select(Aoi).order_by(Aoi.slug)))


def delete_aoi(session: Session, slug: str) -> bool:
    """Delete by slug; jobs and detections cascade via FK, scenes are kept."""
    return session.execute(delete(Aoi).where(Aoi.slug == slug)).rowcount > 0


def stamp_checked(session: Session, aoi_id: int, when: datetime) -> None:
    session.execute(
        update(Aoi).where(Aoi.id == aoi_id).values(last_checked_at=when, updated_at=func.now())
    )
```

`backend/src/overwatch/db/seed.py`:

```python
"""Idempotent showcase-AOI seeder. Run in-container: python -m overwatch.db.seed"""

import logging

from overwatch.aois import SHOWCASE_AOIS
from overwatch.db.aois import upsert_aoi
from overwatch.db.engine import session_scope

logger = logging.getLogger(__name__)


def seed() -> list[int]:
    """Upsert the three showcase AOIs; returns their stable row ids (sorted by slug)."""
    with session_scope() as session:
        return [
            upsert_aoi(
                session,
                slug=aoi.slug,
                name=aoi.name,
                vertical=aoi.vertical,
                geometry=aoi.geometry(),
            )
            for _, aoi in sorted(SHOWCASE_AOIS.items())
        ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ids = seed()
    print(f"seeded {len(ids)} showcase aois: {ids}")
```

- [ ] **Step 5: Run to verify they pass**

Run: `docker compose exec api pytest tests/test_aois_db.py tests/test_seed.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/conftest.py backend/src/overwatch/db/aois.py backend/src/overwatch/db/seed.py backend/tests/test_aois_db.py backend/tests/test_seed.py
git commit -m "feat(phase-3): AOI repository + idempotent showcase seeder"
```

---

### Task 4: API error envelope + session dependency

**Files:**
- Create: `backend/src/overwatch/api/errors.py`, `backend/src/overwatch/api/deps.py`
- Modify: `backend/src/overwatch/api/main.py`
- Test: `backend/tests/test_api_errors.py`

**Interfaces:**
- Consumes: `session_scope`.
- Produces: `ApiError(status_code, code, message, detail=None)` exception; `install_error_handlers(app)`; `get_session() -> Iterator[Session]` FastAPI dependency. Every later endpoint raises `ApiError` and depends on `get_session`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_api_errors.py`:

```python
"""Structured error envelope: ApiError and validation errors share one shape."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from overwatch.api.errors import ApiError, install_error_handlers


def _probe_app() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/boom")
    def boom() -> None:
        raise ApiError(422, "aoi_too_large", "too big", {"area_km2": 1234.5})

    @app.post("/typed")
    def typed(body: Body) -> dict[str, int]:
        return {"n": body.n}

    return TestClient(app)


def test_api_error_envelope() -> None:
    resp = _probe_app().get("/boom")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": {"code": "aoi_too_large", "message": "too big", "detail": {"area_km2": 1234.5}}
    }


def test_validation_error_is_wrapped() -> None:
    resp = _probe_app().post("/typed", json={"n": "not-an-int"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["detail"], list)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_api_errors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.api.errors'`.

- [ ] **Step 3: Implement**

`backend/src/overwatch/api/errors.py`:

```python
"""Structured error envelope: {"error": {code, message, detail}} on every non-2xx (design doc §3)."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def _envelope(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": jsonable_encoder(detail)}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(exc.code, exc.message, exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "request validation failed", exc.errors()),
        )
```

`backend/src/overwatch/api/deps.py`:

```python
"""FastAPI dependencies. Endpoints are sync `def` over the shared sync engine (design doc §1.4)."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from overwatch.db.engine import session_scope


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session
```

Modify `backend/src/overwatch/api/main.py` to install the handlers:

```python
from fastapi import FastAPI

from overwatch.api.errors import install_error_handlers

app = FastAPI(title="Overwatch API")
install_error_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_api_errors.py tests/test_health.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/api/errors.py backend/src/overwatch/api/deps.py backend/src/overwatch/api/main.py backend/tests/test_api_errors.py
git commit -m "feat(phase-3): structured error envelope + DB session dependency"
```

---

### Task 5: AOI CRUD endpoints (with the 500 km² cap)

**Files:**
- Modify: `backend/src/overwatch/config.py` (add `max_aoi_km2`)
- Create: `backend/src/overwatch/api/schemas.py`, `backend/src/overwatch/api/aois.py`
- Modify: `backend/src/overwatch/api/main.py` (include router)
- Test: `backend/tests/test_api_aois.py`

**Interfaces:**
- Consumes: `ApiError`, `get_session`, `geodesic_area_km2`, AOI repository (Task 3), `settings`.
- Produces: `POST /aois` (201) / `GET /aois` / `GET /aois/{slug}` / `DELETE /aois/{slug}` (204); pydantic models `AoiCreate` (`slug, name, vertical: Literal["port","forest","flood"], geometry: GeoJSON dict, cadence_days`), `AoiOut` (`slug, name, vertical, geometry, cadence_days, area_km2, created_at`); helper `parse_polygon(geojson: dict) -> Polygon` (raises `ApiError(422, "invalid_geometry", ...)`). Task 10 adds its routers next to this one.

- [ ] **Step 1: Add the cap to Settings**

In `backend/src/overwatch/config.py`, add after `fusion_enabled`:

```python
    max_aoi_km2: float = 500.0  # design spec §6 — reject larger AOIs at the API
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_api_aois.py`:

```python
"""AOI CRUD: create with cap, structured rejections, list/get/delete."""

from fastapi.testclient import TestClient

from overwatch.api.main import app

client = TestClient(app)

SMALL_GEOM = {  # ~1.2 km^2 near the equator
    "type": "Polygon",
    "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
}
HUGE_GEOM = {  # ~12,300 km^2
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}


def _payload(slug: str, geometry: dict) -> dict:
    return {"slug": slug, "name": "Test AOI", "vertical": "port", "geometry": geometry}


def test_create_get_list_delete_roundtrip(clean_t3: None) -> None:
    created = client.post("/aois", json=_payload("t3-crud", SMALL_GEOM))
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "t3-crud" and 0 < body["area_km2"] < 2

    assert client.get("/aois/t3-crud").status_code == 200
    assert any(a["slug"] == "t3-crud" for a in client.get("/aois").json())

    assert client.delete("/aois/t3-crud").status_code == 204
    missing = client.get("/aois/t3-crud")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "aoi_not_found"


def test_oversized_aoi_rejected_with_structured_error(clean_t3: None) -> None:
    resp = client.post("/aois", json=_payload("t3-huge", HUGE_GEOM))
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "aoi_too_large"
    assert err["detail"]["max_km2"] == 500.0
    assert err["detail"]["area_km2"] > 500.0


def test_invalid_geometry_rejected(clean_t3: None) -> None:
    resp = client.post("/aois", json=_payload("t3-bowtie", BOWTIE))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_geometry"


def test_duplicate_slug_conflict(clean_t3: None) -> None:
    assert client.post("/aois", json=_payload("t3-dup", SMALL_GEOM)).status_code == 201
    resp = client.post("/aois", json=_payload("t3-dup", SMALL_GEOM))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "aoi_exists"


def test_unknown_vertical_is_validation_error(clean_t3: None) -> None:
    payload = _payload("t3-vert", SMALL_GEOM) | {"vertical": "volcano"}
    resp = client.post("/aois", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
```

- [ ] **Step 3: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_api_aois.py -q`
Expected: FAIL — 404s / missing routes (no `/aois` router yet).

- [ ] **Step 4: Implement schemas + router**

`backend/src/overwatch/api/schemas.py`:

```python
"""Pydantic v2 boundary models for the Phase 3 API (design doc §3)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AoiCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    name: str = Field(min_length=1, max_length=200)
    vertical: Literal["port", "forest", "flood"]
    geometry: dict[str, Any]  # GeoJSON Polygon, validated against shapely in the endpoint
    cadence_days: int | None = Field(default=None, ge=1)


class AoiOut(BaseModel):
    slug: str
    name: str
    vertical: str
    geometry: dict[str, Any]
    cadence_days: int | None
    area_km2: float
    created_at: datetime


class DateWindow(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "DateWindow":
        if self.end < self.start:
            raise ValueError("window end is before start")
        return self


class JobSubmit(BaseModel):
    before: DateWindow
    after: DateWindow


class JobOut(BaseModel):
    id: UUID
    aoi_slug: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str | None
    attempts: int
    params: dict[str, Any]
    before_scene_id: int | None
    after_scene_id: int | None
    detection_count: int | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
```

`backend/src/overwatch/api/aois.py`:

```python
"""AOI CRUD (design doc §3). The 500 km² cap is enforced here, from Settings."""

from typing import Any

from fastapi import APIRouter, Depends
from geoalchemy2.shape import to_shape
from shapely.geometry import Polygon, mapping, shape
from sqlalchemy.orm import Session

from overwatch.api.deps import get_session
from overwatch.api.errors import ApiError
from overwatch.api.schemas import AoiCreate, AoiOut
from overwatch.config import settings
from overwatch.db.aois import delete_aoi, get_aoi, list_aois, upsert_aoi
from overwatch.db.models import Aoi
from overwatch.geodesy import geodesic_area_km2

router = APIRouter(prefix="/aois", tags=["aois"])


def parse_polygon(geojson: dict[str, Any]) -> Polygon:
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise ApiError(422, "invalid_geometry", f"unparseable GeoJSON: {exc}") from exc
    if not isinstance(geom, Polygon) or not geom.is_valid:
        raise ApiError(422, "invalid_geometry", "geometry must be a valid GeoJSON Polygon")
    return geom


def _to_out(row: Aoi) -> AoiOut:
    geom = to_shape(row.geom)
    return AoiOut(
        slug=row.slug,
        name=row.name,
        vertical=row.vertical,
        geometry=mapping(geom),
        cadence_days=row.cadence_days,
        area_km2=geodesic_area_km2(geom),
        created_at=row.created_at,
    )


def require_aoi(session: Session, slug: str) -> Aoi:
    row = get_aoi(session, slug)
    if row is None:
        raise ApiError(404, "aoi_not_found", f"no AOI with slug {slug!r}")
    return row


@router.post("", status_code=201, response_model=AoiOut)
def create_aoi(payload: AoiCreate, session: Session = Depends(get_session)) -> AoiOut:
    geom = parse_polygon(payload.geometry)
    area = geodesic_area_km2(geom)
    if area > settings.max_aoi_km2:
        raise ApiError(
            422,
            "aoi_too_large",
            f"AOI area {area:.1f} km² exceeds the {settings.max_aoi_km2:.0f} km² cap",
            {"area_km2": area, "max_km2": settings.max_aoi_km2},
        )
    if get_aoi(session, payload.slug) is not None:
        raise ApiError(409, "aoi_exists", f"AOI {payload.slug!r} already exists")
    upsert_aoi(
        session,
        slug=payload.slug,
        name=payload.name,
        vertical=payload.vertical,
        geometry=geom,
        cadence_days=payload.cadence_days,
    )
    return _to_out(require_aoi(session, payload.slug))


@router.get("", response_model=list[AoiOut])
def get_aois(session: Session = Depends(get_session)) -> list[AoiOut]:
    return [_to_out(row) for row in list_aois(session)]


@router.get("/{slug}", response_model=AoiOut)
def get_one(slug: str, session: Session = Depends(get_session)) -> AoiOut:
    return _to_out(require_aoi(session, slug))


@router.delete("/{slug}", status_code=204)
def delete_one(slug: str, session: Session = Depends(get_session)) -> None:
    require_aoi(session, slug)
    delete_aoi(session, slug)
```

In `backend/src/overwatch/api/main.py`, include the router:

```python
from fastapi import FastAPI

from overwatch.api import aois
from overwatch.api.errors import install_error_handlers

app = FastAPI(title="Overwatch API")
install_error_handlers(app)
app.include_router(aois.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_api_aois.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/config.py backend/src/overwatch/api/schemas.py backend/src/overwatch/api/aois.py backend/src/overwatch/api/main.py backend/tests/test_api_aois.py
git commit -m "feat(phase-3): AOI CRUD endpoints with geodesic 500km2 cap"
```

---

### Task 6: Job repository

**Files:**
- Create: `backend/src/overwatch/db/jobs.py`
- Test: `backend/tests/test_jobs_db.py`

**Interfaces:**
- Consumes: `Job` ORM (Task 1), AOI repository.
- Produces: `create_job(session, aoi_id, params) -> Job`; `get_job(session, job_id: str | UUID) -> Job | None`; `set_stage(session, job_id, stage)` (also flips status to `running`); `record_attempt(session, job_id)` (atomic `attempts + 1`); `set_scene(session, job_id, which: str, scene_id: int)`; `mark_succeeded(session, job_id, detection_count)`; `mark_failed(session, job_id, *, code, message, detail=None)`; `latest_succeeded_job(session, aoi_id) -> Job | None`. Tasks 9–11 use exactly these.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_jobs_db.py`:

```python
"""Job rows: lifecycle transitions, attempts counter, latest-succeeded lookup."""

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.jobs import (
    create_job,
    get_job,
    latest_succeeded_job,
    mark_failed,
    mark_succeeded,
    record_attempt,
    set_scene,
    set_stage,
)

PARAMS = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def _aoi(session: Session, slug: str = "t3-job") -> int:
    return upsert_aoi(
        session, slug=slug, name="J", vertical="port", geometry=box(0, 0, 0.01, 0.01)
    )


def test_lifecycle_to_succeeded(db_session: Session, clean_t3: None) -> None:
    aoi_id = _aoi(db_session)
    job = create_job(db_session, aoi_id, PARAMS)
    assert job.status == "queued" and job.attempts == 0 and job.params == PARAMS

    set_stage(db_session, job.id, "ingest_before")
    record_attempt(db_session, job.id)
    db_session.expire_all()
    row = get_job(db_session, str(job.id))
    assert row.status == "running" and row.stage == "ingest_before" and row.attempts == 1

    mark_succeeded(db_session, job.id, detection_count=9)
    db_session.expire_all()
    row = get_job(db_session, job.id)
    assert row.status == "succeeded" and row.detection_count == 9 and row.error is None


def test_mark_failed_records_structured_error(db_session: Session, clean_t3: None) -> None:
    job = create_job(db_session, _aoi(db_session), PARAMS)
    mark_failed(db_session, job.id, code="no_usable_scene", message="nope", detail={"w": 1})
    db_session.expire_all()
    row = get_job(db_session, job.id)
    assert row.status == "failed"
    assert row.error == {"code": "no_usable_scene", "message": "nope", "detail": {"w": 1}}


def test_latest_succeeded_requires_after_scene(db_session: Session, clean_t3: None) -> None:
    aoi_id = _aoi(db_session)
    first = create_job(db_session, aoi_id, PARAMS)
    mark_succeeded(db_session, first.id, detection_count=0)  # no after scene recorded
    assert latest_succeeded_job(db_session, aoi_id) is None

    second = create_job(db_session, aoi_id, PARAMS)
    set_scene(db_session, second.id, "after", _scene_id(db_session))
    mark_succeeded(db_session, second.id, detection_count=1)
    assert latest_succeeded_job(db_session, aoi_id).id == second.id


def _scene_id(session: Session) -> int:
    from datetime import UTC, datetime

    from shapely.geometry import box as _box

    from overwatch.db.scenes import upsert_scene
    from overwatch.imagery.models import SceneMeta

    meta = SceneMeta(
        stac_id="t3-scene-jobs",
        collection="sentinel-2-l2a",
        captured_at=datetime(2024, 6, 10, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    return upsert_scene(session, meta, "t3-job", _box(0, 0, 0.01, 0.01), 1.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_jobs_db.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.db.jobs'`.

- [ ] **Step 3: Implement**

`backend/src/overwatch/db/jobs.py`:

```python
"""Job state — durable in Postgres, polled via the API (design doc §2)."""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from overwatch.db.models import Job


def create_job(session: Session, aoi_id: int, params: dict[str, Any]) -> Job:
    job = Job(id=uuid.uuid4(), aoi_id=aoi_id, status="queued", params=params, attempts=0)
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: str | uuid.UUID) -> Job | None:
    return session.get(Job, uuid.UUID(str(job_id)))


def _update(session: Session, job_id: str | uuid.UUID, **values: Any) -> None:
    values["updated_at"] = func.now()
    session.execute(update(Job).where(Job.id == uuid.UUID(str(job_id))).values(**values))


def set_stage(session: Session, job_id: str | uuid.UUID, stage: str) -> None:
    _update(session, job_id, stage=stage, status="running")


def record_attempt(session: Session, job_id: str | uuid.UUID) -> None:
    _update(session, job_id, attempts=Job.attempts + 1)


def set_scene(session: Session, job_id: str | uuid.UUID, which: str, scene_id: int) -> None:
    if which not in ("before", "after"):
        raise ValueError(f"which must be 'before' or 'after', got {which!r}")
    _update(session, job_id, **{f"{which}_scene_id": scene_id})


def mark_succeeded(session: Session, job_id: str | uuid.UUID, detection_count: int) -> None:
    _update(session, job_id, status="succeeded", detection_count=detection_count, error=None)


def mark_failed(
    session: Session, job_id: str | uuid.UUID, *, code: str, message: str, detail: Any = None
) -> None:
    _update(
        session, job_id, status="failed", error={"code": code, "message": message, "detail": detail}
    )


def latest_succeeded_job(session: Session, aoi_id: int) -> Job | None:
    """Most recent succeeded job that recorded an after scene (re-check baseline)."""
    return session.scalar(
        select(Job)
        .where(Job.aoi_id == aoi_id, Job.status == "succeeded", Job.after_scene_id.is_not(None))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_jobs_db.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/db/jobs.py backend/tests/test_jobs_db.py
git commit -m "feat(phase-3): durable job rows with staged lifecycle + attempts counter"
```

---

### Task 7: Detection persistence — replace-set + spatial query

**Files:**
- Create: `backend/src/overwatch/db/detections.py`
- Test: `backend/tests/test_detections_db.py`

**Interfaces:**
- Consumes: `DetectionEvent` ORM, `Detection` engine dataclass, `to_wgs84` (Task 2), jobs/aois/scenes repositories.
- Produces: `replace_detections(session, *, aoi_id, job_id, before_scene_id, after_scene_id, detections: list[Detection]) -> int` (transactional delete+insert on the pair — the idempotency mechanism); `query_detections(session, aoi_id, *, intersects: Polygon | None = None, since: date | None = None, change_type: str | None = None) -> list[DetectionEvent]` (`since` filters on the **after scene's capture date**, not row creation). Tasks 9–10 use these.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_detections_db.py`:

```python
"""Replace-set idempotency + ST_Intersects / since / change_type filters."""

from datetime import UTC, date, datetime

from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import query_detections, replace_detections
from overwatch.db.jobs import create_job
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)


def _fixture_ids(session: Session) -> tuple[int, str, int, int]:
    aoi_id = upsert_aoi(
        session, slug="t3-det", name="D", vertical="port", geometry=AOI_GEOM
    )
    scene_ids = []
    for stac_id, day in (("t3-det-before", 10), ("t3-det-after", 20)):
        meta = SceneMeta(
            stac_id=stac_id,
            collection="sentinel-2-l2a",
            captured_at=datetime(2024, 6, day, tzinfo=UTC),
            cloud_pct=1.0,
            epsg=32643,
            assets={},
        )
        scene_ids.append(upsert_scene(session, meta, "t3-det", AOI_GEOM, 1.0))
    job = create_job(session, aoi_id, {})
    return aoi_id, str(job.id), scene_ids[0], scene_ids[1]


def _detection(lonlat_box: tuple[float, float, float, float]) -> Detection:
    # epsg=4326 keeps the test geometry in lon/lat directly (to_wgs84 no-ops)
    return Detection(
        geometry=box(*lonlat_box),
        epsg=4326,
        area_m2=20_000.0,
        change_type=ChangeType.CONSTRUCTION,
        magnitude=0.5,
        confidence=0.9,
        contributing_indices={"ssim_dissim": 0.5},
    )


def test_replace_set_is_idempotent(db_session: Session, clean_t3: None) -> None:
    aoi_id, job_id, before_id, after_id = _fixture_ids(db_session)
    dets = [_detection((76.97, 8.36, 76.99, 8.38)), _detection((77.00, 8.40, 77.02, 8.42))]
    kwargs = dict(
        aoi_id=aoi_id, job_id=job_id, before_scene_id=before_id, after_scene_id=after_id
    )
    assert replace_detections(db_session, detections=dets, **kwargs) == 2
    assert replace_detections(db_session, detections=dets, **kwargs) == 2
    assert len(query_detections(db_session, aoi_id)) == 2  # not 4


def test_spatial_and_attribute_filters(db_session: Session, clean_t3: None) -> None:
    aoi_id, job_id, before_id, after_id = _fixture_ids(db_session)
    replace_detections(
        db_session,
        aoi_id=aoi_id,
        job_id=job_id,
        before_scene_id=before_id,
        after_scene_id=after_id,
        detections=[_detection((76.97, 8.36, 76.99, 8.38))],
    )
    hit = query_detections(db_session, aoi_id, intersects=box(76.98, 8.37, 77.00, 8.39))
    miss = query_detections(db_session, aoi_id, intersects=box(75.0, 7.0, 75.1, 7.1))
    assert len(hit) == 1 and len(miss) == 0

    # since: after scene captured 2024-06-20
    assert len(query_detections(db_session, aoi_id, since=date(2024, 6, 1))) == 1
    assert len(query_detections(db_session, aoi_id, since=date(2024, 7, 1))) == 0

    assert len(query_detections(db_session, aoi_id, change_type="construction")) == 1
    assert len(query_detections(db_session, aoi_id, change_type="flooding")) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_detections_db.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.db.detections'`.

- [ ] **Step 3: Implement**

`backend/src/overwatch/db/detections.py`:

```python
"""Detection persistence — replace-set on the (aoi, before, after) pair (design doc §2).

The engine is deterministic, so the pair is the natural key: one transaction deletes the
pair's rows and reinserts. Re-running a job rewrites identical rows — zero duplicates.
"""

import uuid
from datetime import date

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from overwatch.db.models import DetectionEvent, Scene
from overwatch.detection.models import Detection
from overwatch.geodesy import to_wgs84


def replace_detections(
    session: Session,
    *,
    aoi_id: int,
    job_id: str | uuid.UUID,
    before_scene_id: int,
    after_scene_id: int,
    detections: list[Detection],
) -> int:
    session.execute(
        delete(DetectionEvent).where(
            DetectionEvent.aoi_id == aoi_id,
            DetectionEvent.before_scene_id == before_scene_id,
            DetectionEvent.after_scene_id == after_scene_id,
        )
    )
    for det in detections:
        session.add(
            DetectionEvent(
                aoi_id=aoi_id,
                job_id=uuid.UUID(str(job_id)),
                before_scene_id=before_scene_id,
                after_scene_id=after_scene_id,
                geom=from_shape(to_wgs84(det.geometry, det.epsg), srid=4326),
                src_epsg=det.epsg,
                area_m2=det.area_m2,
                change_type=det.change_type.value,
                magnitude=det.magnitude,
                confidence=det.confidence,
                contributing_indices=det.contributing_indices,
            )
        )
    session.flush()
    return len(detections)


def query_detections(
    session: Session,
    aoi_id: int,
    *,
    intersects: Polygon | None = None,
    since: date | None = None,
    change_type: str | None = None,
) -> list[DetectionEvent]:
    """Events for an AOI; `since` filters on the after scene's capture date."""
    stmt = select(DetectionEvent).where(DetectionEvent.aoi_id == aoi_id)
    if intersects is not None:
        stmt = stmt.where(
            func.ST_Intersects(DetectionEvent.geom, from_shape(intersects, srid=4326))
        )
    if since is not None:
        after_scene = aliased(Scene)
        stmt = stmt.join(after_scene, DetectionEvent.after_scene_id == after_scene.id).where(
            after_scene.captured_at >= since
        )
    if change_type is not None:
        stmt = stmt.where(DetectionEvent.change_type == change_type)
    return list(session.scalars(stmt.order_by(DetectionEvent.area_m2.desc())))
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_detections_db.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/db/detections.py backend/tests/test_detections_db.py
git commit -m "feat(phase-3): detection replace-set persistence + spatial predicate queries"
```

---

### Task 8: Shared BOA harmonization module (lift from the Phase 2 CLI)

**Files:**
- Create: `backend/src/overwatch/imagery/harmonize.py`
- Modify: `backend/src/overwatch/detection/cli.py` (`_load_window` uses the shared function)
- Test: `backend/tests/test_harmonize.py`

**Interfaces:**
- Consumes: `AOIWindow`, `SceneMeta`.
- Produces: `harmonize_window(window: AOIWindow, scene: SceneMeta) -> AOIWindow` — applies `scene.dn_offset` to all bands (float32, clipped at 0), no-op when 0. Task 9's worker uses it; the CLI keeps identical behavior.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_harmonize.py`:

```python
"""BOA offset harmonization shared by CLI and workers."""

from datetime import UTC, datetime

import numpy as np

from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.models import SceneMeta
from tests.synthetic import FOREST, flat_window


def _meta(dn_offset: int) -> SceneMeta:
    return SceneMeta(
        stac_id="t3-harm",
        collection="sentinel-2-l2a",
        captured_at=datetime(2025, 1, 1, tzinfo=UTC),
        cloud_pct=0.0,
        epsg=32643,
        assets={},
        dn_offset=dn_offset,
    )


def test_offset_applied_and_clipped() -> None:
    window = flat_window(FOREST)
    out = harmonize_window(window, _meta(-1000))
    assert out is not window
    assert out.bands["red"].dtype == np.float32
    assert float(out.bands["red"].min()) >= 0.0
    np.testing.assert_allclose(
        out.bands["nir"], np.clip(window.bands["nir"].astype(np.float32) - 1000, 0, None)
    )
    assert out.transform == window.transform and out.epsg == window.epsg


def test_zero_offset_is_noop() -> None:
    window = flat_window(FOREST)
    assert harmonize_window(window, _meta(0)) is window
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_harmonize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.imagery.harmonize'`.

- [ ] **Step 3: Implement + refactor the CLI**

`backend/src/overwatch/imagery/harmonize.py`:

```python
"""Sentinel-2 BOA DN-offset harmonization (baseline ≥04.00) — shared by CLI and workers."""

import numpy as np

from overwatch.imagery.models import AOIWindow, SceneMeta


def harmonize_window(window: AOIWindow, scene: SceneMeta) -> AOIWindow:
    """Add the scene's BOA offset to every band (float32, clipped at 0); no-op when 0."""
    if not scene.dn_offset:
        return window
    return AOIWindow(
        bands={
            name: np.clip(band.astype(np.float32) + scene.dn_offset, 0, None)
            for name, band in window.bands.items()
        },
        scl=window.scl,
        transform=window.transform,
        epsg=window.epsg,
    )
```

In `backend/src/overwatch/detection/cli.py`, replace `_load_window`'s offset block with the shared call — the function becomes:

```python
def _load_window(provider: EarthSearchProvider, aoi: AOI, day: date) -> tuple[SceneMeta, AOIWindow]:
    scenes = provider.search_scenes(
        aoi.geometry(), day, day + timedelta(days=1), max_cloud_pct=100.0
    )
    if not scenes:
        raise SystemExit(f"no scene for {aoi.slug} on {day}")
    scene = scenes[0]
    window = provider.read_window(scene, aoi.geometry(), BANDS)
    return scene, harmonize_window(window, scene)
```

Update the CLI's imports: add `from overwatch.imagery.harmonize import harmonize_window`, drop the now-unused `import numpy as np` and the `AOIWindow` import if nothing else uses them (check with ruff — F401 will flag).

- [ ] **Step 4: Run to verify it passes (plus the untouched detection suite)**

Run: `docker compose exec api pytest tests/test_harmonize.py tests/test_detector.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/imagery/harmonize.py backend/src/overwatch/detection/cli.py backend/tests/test_harmonize.py
git commit -m "refactor(phase-3): shared BOA harmonization module, CLI reuses it"
```

---

### Task 9: Celery task chain (ingest → ingest → detect)

**Files:**
- Create: `backend/src/overwatch/workers/tasks.py`
- Modify: `backend/src/overwatch/workers/celery_app.py` (register the tasks module)
- Test: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: everything above — jobs/aois/scenes/detections repositories, `find_usable_scene`, `harmonize_window`, `ClassicalChangeDetector`, `VERTICAL_PRESETS`, `SceneMeta` round-trip via `scenes.meta`.
- Produces: `dispatch_detection_job(job_id: str) -> None` (builds and enqueues the chain — Task 10's submit endpoint and Task 11's beat both call this exact name); tasks `overwatch.ingest_scene(job_id, which)` and `overwatch.run_detection(job_id)`; `get_provider() -> ImageryProvider` (module-level factory, monkeypatched in tests); exceptions `TransientIngestError` (retried) and `JobFailure` (permanent, already recorded).
- Key mechanics: scene meta persisted as `SceneMeta.model_dump(mode="json")` so `run_detection` can re-read windows without re-searching; `JobTask.on_failure` guarantees no job is left `running` after a terminal failure.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tasks.py`:

```python
"""Chain tasks over a fake provider: happy path, idempotent re-run, failure modes."""

from datetime import UTC, date, datetime

import pytest
from celery.exceptions import Retry
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import query_detections
from overwatch.db.jobs import create_job, get_job
from overwatch.imagery.models import AOIWindow, SceneMeta
from overwatch.workers import tasks
from tests.synthetic import BARE, FOREST, SCL_CLOUD_HIGH, flat_window, inject_rect

AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)
PARAMS = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def _meta(stac_id: str, when: datetime) -> SceneMeta:
    return SceneMeta(
        stac_id=stac_id,
        collection="sentinel-2-l2a",
        captured_at=when,
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )


class FakeProvider:
    def __init__(self, scenes: list[SceneMeta], windows: dict[str, AOIWindow]) -> None:
        self.scenes, self.windows = scenes, windows

    def search_scenes(self, geometry, start, end, *, max_cloud_pct):
        return [s for s in self.scenes if start <= s.captured_at.date() < end]

    def read_window(self, scene, geometry, bands):
        return self.windows[scene.stac_id]


def _forest_pair() -> FakeProvider:
    before = flat_window(FOREST)
    after = flat_window(FOREST)
    inject_rect(after, BARE, (20, 60, 20, 60))  # 400m x 400m clearing = 160,000 m2
    return FakeProvider(
        scenes=[
            _meta("t3-fk-before", datetime(2024, 1, 10, tzinfo=UTC)),
            _meta("t3-fk-after", datetime(2024, 6, 10, tzinfo=UTC)),
        ],
        windows={"t3-fk-before": before, "t3-fk-after": after},
    )


def _job(session: Session, vertical: str = "forest") -> tuple[int, str]:
    aoi_id = upsert_aoi(
        session, slug="t3-task", name="T", vertical=vertical, geometry=AOI_GEOM
    )
    job = create_job(session, aoi_id, PARAMS)
    session.commit()
    return aoi_id, str(job.id)


def test_full_chain_persists_detections_idempotently(
    db_session: Session, clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _forest_pair()
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    aoi_id, job_id = _job(db_session)

    tasks.ingest_scene(job_id, "before")
    tasks.ingest_scene(job_id, "after")
    tasks.run_detection(job_id)

    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "succeeded"
    assert job.before_scene_id is not None and job.after_scene_id is not None
    assert job.detection_count >= 1 and job.attempts == 3  # one per stage

    rows = query_detections(db_session, aoi_id)
    assert len(rows) == job.detection_count
    # synthetic grid sits near UTM 43N (500km E, 1000km N) -> about lon 75, lat 9
    assert len(query_detections(db_session, aoi_id, intersects=box(74.5, 8.5, 75.5, 9.5))) >= 1

    tasks.run_detection(job_id)  # re-run: replace-set, zero duplicates
    db_session.expire_all()
    assert len(query_detections(db_session, aoi_id)) == len(rows)


def test_no_usable_scene_fails_fast_with_structured_error(
    db_session: Session, clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloudy = flat_window(FOREST, scl_class=SCL_CLOUD_HIGH)  # usable fraction 0
    provider = FakeProvider(
        scenes=[_meta("t3-fk-cloud", datetime(2024, 1, 10, tzinfo=UTC))],
        windows={"t3-fk-cloud": cloudy},
    )
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    _, job_id = _job(db_session)

    with pytest.raises(tasks.JobFailure):
        tasks.ingest_scene(job_id, "before")
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "failed" and job.error["code"] == "no_usable_scene"


def test_network_error_is_retried_not_failed(
    db_session: Session, clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenProvider:
        def search_scenes(self, *args, **kwargs):
            raise ConnectionError("stac unreachable")

        def read_window(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError

    monkeypatch.setattr(tasks, "get_provider", lambda: BrokenProvider())
    _, job_id = _job(db_session)

    # outside a worker, autoretry surfaces as celery.exceptions.Retry
    with pytest.raises(Retry):
        tasks.ingest_scene(job_id, "before")
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "running" and job.attempts == 1  # retrying, NOT failed


def test_retry_policy_is_configured() -> None:
    for task in (tasks.ingest_scene, tasks.run_detection):
        assert tasks.TransientIngestError in task.autoretry_for
        assert task.max_retries == 3
        assert task.retry_backoff is True


def test_on_failure_marks_job_failed(db_session: Session, clean_t3: None) -> None:
    _, job_id = _job(db_session)
    tasks.ingest_scene.on_failure(RuntimeError("boom"), "tid", (job_id, "before"), {}, None)
    db_session.expire_all()
    job = get_job(db_session, job_id)
    assert job.status == "failed" and job.error["code"] == "task_failed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_tasks.py -q`
Expected: FAIL — `cannot import name 'tasks'` (module missing).

- [ ] **Step 3: Implement**

`backend/src/overwatch/workers/tasks.py`:

```python
"""Detection job chain: ingest before → ingest after → detect (design doc §4).

Transient errors (network/STAC) retry with exponential backoff; permanent failures
(no usable scene, coregistration mismatch) fail fast with a structured error on the
job row. JobTask.on_failure guarantees no job is left 'running' after a terminal crash.
"""

import logging
from datetime import date
from typing import NoReturn

from celery import Task, chain
from geoalchemy2.shape import to_shape

from overwatch.db.aois import stamp_checked  # noqa: F401  (re-exported for Task 11)
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.jobs import (
    get_job,
    mark_failed,
    mark_succeeded,
    record_attempt,
    set_scene,
    set_stage,
)
from overwatch.db.models import Aoi, Scene
from overwatch.db.scenes import upsert_scene
from overwatch.detection.detector import ClassicalChangeDetector
from overwatch.detection.presets import VERTICAL_PRESETS
from overwatch.imagery.earth_search import EarthSearchProvider
from overwatch.imagery.gating import MIN_USABLE_FRACTION, find_usable_scene
from overwatch.imagery.harmonize import harmonize_window
from overwatch.imagery.models import SceneMeta
from overwatch.imagery.provider import ImageryProvider
from overwatch.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BANDS: tuple[str, ...] = ("red", "green", "blue", "nir")


class TransientIngestError(Exception):
    """Network/STAC hiccup — safe to retry with backoff."""


class JobFailure(Exception):
    """Permanent failure; the structured error is already on the job row."""


def get_provider() -> ImageryProvider:
    """Module-level factory so tests can monkeypatch the provider."""
    return EarthSearchProvider()


def dispatch_detection_job(job_id: str) -> None:
    chain(
        ingest_scene.si(job_id, "before"),
        ingest_scene.si(job_id, "after"),
        run_detection.si(job_id),
    ).apply_async()


def _fail(job_id: str, code: str, message: str) -> NoReturn:
    with session_scope() as session:
        mark_failed(session, job_id, code=code, message=message)
    raise JobFailure(message)


class JobTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        if isinstance(exc, JobFailure):
            return  # already recorded structurally
        job_id = args[0] if args else kwargs.get("job_id")
        if job_id is None:
            return
        with session_scope() as session:
            mark_failed(
                session, job_id, code="task_failed", message=str(exc), detail={"task": self.name}
            )


_RETRY = dict(
    base=JobTask,
    bind=True,
    autoretry_for=(TransientIngestError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)


@celery_app.task(name="overwatch.ingest_scene", **_RETRY)
def ingest_scene(self: Task, job_id: str, which: str) -> None:
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None:
            raise JobFailure(f"job {job_id} not found")
        set_stage(session, job_id, f"ingest_{which}")
        record_attempt(session, job_id)
        aoi = session.get(Aoi, job.aoi_id)
        geometry = to_shape(aoi.geom)
        slug = aoi.slug
        window = job.params[which]
    start = date.fromisoformat(window["start"])
    end = date.fromisoformat(window["end"])
    try:
        selection = find_usable_scene(get_provider(), geometry, start, end, bands=BANDS)
    except Exception as exc:
        raise TransientIngestError(f"scene search/read failed: {exc}") from exc
    if selection is None:
        _fail(
            job_id,
            "no_usable_scene",
            f"no scene ≥{MIN_USABLE_FRACTION:.0%} usable in {start}..{end} after widening",
        )
    with session_scope() as session:
        scene_id = upsert_scene(
            session,
            selection.scene,
            slug,
            geometry,
            selection.usable_fraction,
            meta=selection.scene.model_dump(mode="json"),
        )
        set_scene(session, job_id, which, scene_id)
    logger.info("job %s: %s scene %s (id=%s)", job_id, which, selection.scene.stac_id, scene_id)


@celery_app.task(name="overwatch.run_detection", **_RETRY)
def run_detection(self: Task, job_id: str) -> None:
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None or job.before_scene_id is None or job.after_scene_id is None:
            raise JobFailure(f"job {job_id} is missing ingested scenes")
        set_stage(session, job_id, "detect")
        record_attempt(session, job_id)
        aoi = session.get(Aoi, job.aoi_id)
        geometry = to_shape(aoi.geom)
        vertical = aoi.vertical
        aoi_id, before_id, after_id = job.aoi_id, job.before_scene_id, job.after_scene_id
        before_meta = SceneMeta.model_validate(session.get(Scene, before_id).meta)
        after_meta = SceneMeta.model_validate(session.get(Scene, after_id).meta)
    provider = get_provider()
    try:
        before = harmonize_window(provider.read_window(before_meta, geometry, BANDS), before_meta)
        after = harmonize_window(provider.read_window(after_meta, geometry, BANDS), after_meta)
    except Exception as exc:
        raise TransientIngestError(f"window re-read failed: {exc}") from exc
    try:
        detections = ClassicalChangeDetector().detect(before, after, VERTICAL_PRESETS[vertical])
    except ValueError as exc:
        _fail(job_id, "coregistration_error", str(exc))
    with session_scope() as session:
        count = replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job_id,
            before_scene_id=before_id,
            after_scene_id=after_id,
            detections=detections,
        )
        mark_succeeded(session, job_id, count)
    logger.info("job %s: %d detections persisted", job_id, count)
```

Modify `backend/src/overwatch/workers/celery_app.py` — add after `celery_app.conf.timezone = "UTC"`:

```python
celery_app.conf.imports = ("overwatch.workers.tasks",)
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_tasks.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Restart workers, verify registration, full suite**

Run: `docker compose restart worker beat`
Run: `docker compose exec worker celery -A overwatch.workers.celery_app inspect registered`
Expected: `overwatch.ingest_scene`, `overwatch.run_detection` listed alongside `overwatch.ping`.
Run: `docker compose exec api pytest -q` → all green.

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/workers/tasks.py backend/src/overwatch/workers/celery_app.py backend/tests/test_tasks.py
git commit -m "feat(phase-3): celery chain ingest->ingest->detect with retries and structured failure"
```

---

### Task 10: Job submit/status + detections endpoints

**Files:**
- Create: `backend/src/overwatch/api/jobs.py`, `backend/src/overwatch/api/detections.py`
- Modify: `backend/src/overwatch/api/main.py` (include routers)
- Test: `backend/tests/test_api_jobs.py`, `backend/tests/test_api_detections.py`

**Interfaces:**
- Consumes: `JobSubmit`/`JobOut` schemas (Task 5), jobs/detections repositories, `dispatch_detection_job` (Task 9), `require_aoi` (Task 5).
- Produces: `POST /aois/{slug}/jobs` → 202 `{"job_id": "..."}` (commits the row **before** dispatch — the worker is another process); `GET /jobs/{job_id}` → `JobOut`; `GET /aois/{slug}/detections?intersects=&since=&change_type=` → GeoJSON FeatureCollection.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_api_jobs.py`:

```python
"""Job submit (202 + dispatch) and polling endpoint."""

import pytest
from fastapi.testclient import TestClient

from overwatch.api import jobs as jobs_module
from overwatch.api.main import app

client = TestClient(app)

AOI = {
    "slug": "t3-api-job",
    "name": "J",
    "vertical": "port",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
    },
}
SUBMIT = {
    "before": {"start": "2024-01-01", "end": "2024-01-31"},
    "after": {"start": "2024-06-01", "end": "2024-06-30"},
}


def test_submit_returns_202_and_dispatches(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(jobs_module, "dispatch_detection_job", dispatched.append)
    assert client.post("/aois", json=AOI).status_code == 201

    resp = client.post("/aois/t3-api-job/jobs", json=SUBMIT)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert dispatched == [job_id]

    polled = client.get(f"/jobs/{job_id}")
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "queued" and body["aoi_slug"] == "t3-api-job"
    assert body["params"] == SUBMIT and body["attempts"] == 0


def test_submit_unknown_aoi_404(clean_t3: None) -> None:
    resp = client.post("/aois/t3-ghost/jobs", json=SUBMIT)
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "aoi_not_found"


def test_submit_backwards_window_422(clean_t3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "dispatch_detection_job", lambda _: None)
    client.post("/aois", json=AOI)
    bad = {"before": {"start": "2024-01-31", "end": "2024-01-01"}, "after": SUBMIT["after"]}
    resp = client.post("/aois/t3-api-job/jobs", json=bad)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


def test_poll_unknown_job_404(clean_t3: None) -> None:
    resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "job_not_found"
```

`backend/tests/test_api_detections.py`:

```python
"""GeoJSON detections endpoint with spatial + attribute filters."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from shapely.geometry import box

from overwatch.api.main import app
from overwatch.db.aois import upsert_aoi
from overwatch.db.detections import replace_detections
from overwatch.db.engine import session_scope
from overwatch.db.jobs import create_job
from overwatch.db.scenes import upsert_scene
from overwatch.detection.models import ChangeType, Detection
from overwatch.imagery.models import SceneMeta

client = TestClient(app)
AOI_GEOM = box(76.90, 8.30, 77.10, 8.50)


def _seed_one_detection() -> None:
    with session_scope() as session:
        aoi_id = upsert_aoi(
            session, slug="t3-api-det", name="D", vertical="port", geometry=AOI_GEOM
        )
        ids = []
        for stac_id, day in (("t3-ad-before", 10), ("t3-ad-after", 20)):
            meta = SceneMeta(
                stac_id=stac_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2024, 6, day, tzinfo=UTC),
                cloud_pct=1.0,
                epsg=32643,
                assets={},
            )
            ids.append(upsert_scene(session, meta, "t3-api-det", AOI_GEOM, 1.0))
        job = create_job(session, aoi_id, {})
        replace_detections(
            session,
            aoi_id=aoi_id,
            job_id=job.id,
            before_scene_id=ids[0],
            after_scene_id=ids[1],
            detections=[
                Detection(
                    geometry=box(76.97, 8.36, 76.99, 8.38),
                    epsg=4326,
                    area_m2=20_000.0,
                    change_type=ChangeType.CONSTRUCTION,
                    magnitude=0.5,
                    confidence=0.9,
                    contributing_indices={"ssim_dissim": 0.5},
                )
            ],
        )


def test_feature_collection_with_filters(clean_t3: None) -> None:
    _seed_one_detection()

    everything = client.get("/aois/t3-api-det/detections")
    assert everything.status_code == 200
    body = everything.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 1
    props = body["features"][0]["properties"]
    assert props["change_type"] == "construction" and props["area_m2"] == 20_000.0
    assert body["features"][0]["geometry"]["type"] == "Polygon"

    hit = client.get("/aois/t3-api-det/detections?intersects=76.98,8.37,77.0,8.39")
    assert len(hit.json()["features"]) == 1
    miss = client.get("/aois/t3-api-det/detections?intersects=75.0,7.0,75.1,7.1")
    assert len(miss.json()["features"]) == 0
    assert len(client.get("/aois/t3-api-det/detections?since=2024-07-01").json()["features"]) == 0
    assert (
        len(client.get("/aois/t3-api-det/detections?change_type=flooding").json()["features"]) == 0
    )


def test_bad_intersects_422(clean_t3: None) -> None:
    _seed_one_detection()
    resp = client.get("/aois/t3-api-det/detections?intersects=not-a-geometry")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_intersects"
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec api pytest tests/test_api_jobs.py tests/test_api_detections.py -q`
Expected: FAIL — 404s (routes missing).

- [ ] **Step 3: Implement the routers**

`backend/src/overwatch/api/jobs.py`:

```python
"""Job submission + polling (design doc §3). REST polling ~2 s; no WebSocket in v0.1."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from overwatch.api.aois import require_aoi
from overwatch.api.deps import get_session
from overwatch.api.errors import ApiError
from overwatch.api.schemas import JobOut, JobSubmit
from overwatch.db.jobs import create_job, get_job
from overwatch.db.models import Aoi
from overwatch.workers.tasks import dispatch_detection_job

router = APIRouter(tags=["jobs"])


@router.post("/aois/{slug}/jobs", status_code=202)
def submit_job(
    slug: str, payload: JobSubmit, session: Session = Depends(get_session)
) -> dict[str, str]:
    aoi = require_aoi(session, slug)
    job = create_job(session, aoi.id, payload.model_dump(mode="json"))
    # Commit BEFORE dispatch: the worker reads this row from another process.
    session.commit()
    dispatch_detection_job(str(job.id))
    return {"job_id": str(job.id)}


@router.get("/jobs/{job_id}", response_model=JobOut)
def poll_job(job_id: UUID, session: Session = Depends(get_session)) -> JobOut:
    job = get_job(session, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", f"no job {job_id}")
    slug = session.get(Aoi, job.aoi_id).slug
    return JobOut(
        id=job.id,
        aoi_slug=slug,
        status=job.status,
        stage=job.stage,
        attempts=job.attempts,
        params=job.params,
        before_scene_id=job.before_scene_id,
        after_scene_id=job.after_scene_id,
        detection_count=job.detection_count,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
```

`backend/src/overwatch/api/detections.py`:

```python
"""Detections as GeoJSON, filterable by spatial predicate (design doc §3)."""

from datetime import date
from typing import Any

import shapely.wkt
from fastapi import APIRouter, Depends
from geoalchemy2.shape import to_shape
from shapely.geometry import Polygon, box, mapping
from sqlalchemy.orm import Session

from overwatch.api.aois import require_aoi
from overwatch.api.deps import get_session
from overwatch.api.errors import ApiError
from overwatch.db.detections import query_detections
from overwatch.db.models import DetectionEvent

router = APIRouter(tags=["detections"])


def _parse_intersects(raw: str) -> Polygon:
    """Accepts 'west,south,east,north' bbox or a WKT polygon."""
    parts = raw.split(",")
    if len(parts) == 4:
        try:
            return box(*(float(p) for p in parts))
        except ValueError:
            pass
    try:
        geom = shapely.wkt.loads(raw)
    except Exception as exc:
        raise ApiError(
            422, "invalid_intersects", f"expected bbox 'w,s,e,n' or WKT polygon: {exc}"
        ) from exc
    if not isinstance(geom, Polygon):
        raise ApiError(422, "invalid_intersects", "WKT must describe a polygon")
    return geom


def _feature(row: DetectionEvent) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": mapping(to_shape(row.geom)),
        "properties": {
            "id": row.id,
            "job_id": str(row.job_id),
            "before_scene_id": row.before_scene_id,
            "after_scene_id": row.after_scene_id,
            "change_type": row.change_type,
            "area_m2": row.area_m2,
            "magnitude": row.magnitude,
            "confidence": row.confidence,
            "contributing_indices": row.contributing_indices,
            "src_epsg": row.src_epsg,
            "created_at": row.created_at.isoformat(),
        },
    }


@router.get("/aois/{slug}/detections")
def list_detections(
    slug: str,
    intersects: str | None = None,
    since: date | None = None,
    change_type: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    aoi = require_aoi(session, slug)
    geom = _parse_intersects(intersects) if intersects else None
    rows = query_detections(
        session, aoi.id, intersects=geom, since=since, change_type=change_type
    )
    return {"type": "FeatureCollection", "features": [_feature(row) for row in rows]}
```

In `backend/src/overwatch/api/main.py`, include both routers after the aois one:

```python
from overwatch.api import aois, detections, jobs

app.include_router(aois.router)
app.include_router(jobs.router)
app.include_router(detections.router)
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec api pytest tests/test_api_jobs.py tests/test_api_detections.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/api/jobs.py backend/src/overwatch/api/detections.py backend/src/overwatch/api/main.py backend/tests/test_api_jobs.py backend/tests/test_api_detections.py
git commit -m "feat(phase-3): job submit/poll + GeoJSON detections endpoints"
```

---

### Task 11: Weekly re-check — pure due logic + beat schedule

**Files:**
- Create: `backend/src/overwatch/workers/recheck.py`
- Modify: `backend/src/overwatch/workers/tasks.py` (add `enqueue_due_rechecks`)
- Modify: `backend/src/overwatch/workers/celery_app.py` (beat schedule)
- Test: `backend/tests/test_recheck.py`

**Interfaces:**
- Consumes: `latest_succeeded_job`, `stamp_checked`, `list_aois`, `create_job`, `dispatch_detection_job`, `Scene.captured_at`.
- Produces: pure `is_due(cadence_days, last_checked_at, now) -> bool` and `recheck_windows(last_after_capture: date, today: date) -> RecheckWindows | None` (`RecheckWindows(before: tuple[date, date], after: tuple[date, date])`); task `overwatch.enqueue_due_rechecks() -> int` (number submitted); beat entry running it daily at 03:00 UTC.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_recheck.py`:

```python
"""Re-check due logic (pure) + the enqueue task."""

from datetime import UTC, date, datetime, timedelta

import pytest
from shapely.geometry import box
from sqlalchemy.orm import Session

from overwatch.db.aois import get_aoi, upsert_aoi
from overwatch.db.jobs import create_job, mark_succeeded, set_scene
from overwatch.db.scenes import upsert_scene
from overwatch.imagery.models import SceneMeta
from overwatch.workers import tasks
from overwatch.workers.recheck import is_due, recheck_windows

NOW = datetime(2026, 7, 7, 3, 0, tzinfo=UTC)


def test_is_due_matrix() -> None:
    assert is_due(7, None, NOW) is True  # cadence set, never checked
    assert is_due(None, None, NOW) is False  # no cadence -> never due
    assert is_due(7, NOW - timedelta(days=8), NOW) is True
    assert is_due(7, NOW - timedelta(days=3), NOW) is False


def test_recheck_windows_shape() -> None:
    windows = recheck_windows(date(2026, 6, 20), date(2026, 7, 7))
    assert windows.before == (date(2026, 6, 20), date(2026, 6, 21))
    assert windows.after == (date(2026, 6, 21), date(2026, 7, 7))
    assert recheck_windows(date(2026, 7, 7), date(2026, 7, 7)) is None  # nothing newer possible


def test_enqueue_submits_only_for_due_aois_with_history(
    db_session: Session, clean_t3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_detection_job", dispatched.append)

    geom = box(0, 0, 0.01, 0.01)
    # due, with a successful prior job
    ready_id = upsert_aoi(
        db_session, slug="t3-rc-ready", name="R", vertical="forest", geometry=geom, cadence_days=7
    )
    meta = SceneMeta(
        stac_id="t3-rc-scene",
        collection="sentinel-2-l2a",
        captured_at=datetime(2026, 6, 20, tzinfo=UTC),
        cloud_pct=1.0,
        epsg=32643,
        assets={},
    )
    scene_id = upsert_scene(db_session, meta, "t3-rc-ready", geom, 1.0)
    prior = create_job(db_session, ready_id, {})
    set_scene(db_session, prior.id, "after", scene_id)
    mark_succeeded(db_session, prior.id, detection_count=3)
    # due but no history -> skipped
    upsert_aoi(
        db_session, slug="t3-rc-bare", name="B", vertical="port", geometry=geom, cadence_days=7
    )
    # no cadence -> never due
    upsert_aoi(db_session, slug="t3-rc-off", name="O", vertical="flood", geometry=geom)
    db_session.commit()

    assert tasks.enqueue_due_rechecks() == 1
    assert len(dispatched) == 1

    db_session.expire_all()
    assert get_aoi(db_session, "t3-rc-ready").last_checked_at is not None
    assert get_aoi(db_session, "t3-rc-bare").last_checked_at is None

    assert tasks.enqueue_due_rechecks() == 0  # freshly stamped -> no longer due


def test_beat_schedule_registered() -> None:
    from overwatch.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["enqueue-due-rechecks"]
    assert entry["task"] == "overwatch.enqueue_due_rechecks"
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_recheck.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.workers.recheck'`.

- [ ] **Step 3: Implement**

`backend/src/overwatch/workers/recheck.py`:

```python
"""Weekly re-check due logic — pure and unit-tested (design doc §4)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class RecheckWindows:
    before: tuple[date, date]
    after: tuple[date, date]


def is_due(cadence_days: int | None, last_checked_at: datetime | None, now: datetime) -> bool:
    if cadence_days is None:
        return False
    if last_checked_at is None:
        return True
    return last_checked_at + timedelta(days=cadence_days) <= now


def recheck_windows(last_after_capture: date, today: date) -> RecheckWindows | None:
    """Baseline = the previous run's after scene (exact day); search window = everything newer."""
    day_after = last_after_capture + timedelta(days=1)
    if day_after >= today:
        return None
    return RecheckWindows(
        before=(last_after_capture, day_after),
        after=(day_after, today),
    )
```

Append to `backend/src/overwatch/workers/tasks.py` (imports: add `from datetime import UTC, datetime`, `from overwatch.db.aois import list_aois` merged with the existing `stamp_checked` import, `from overwatch.db.jobs import create_job, latest_succeeded_job` merged into the existing jobs import, and `from overwatch.workers.recheck import is_due, recheck_windows`):

```python
@celery_app.task(name="overwatch.enqueue_due_rechecks")
def enqueue_due_rechecks() -> int:
    """Daily beat tick: submit a detection job per due AOI with a prior baseline."""
    now = datetime.now(UTC)
    submitted = 0
    with session_scope() as session:
        for aoi in list_aois(session):
            if not is_due(aoi.cadence_days, aoi.last_checked_at, now):
                continue
            baseline = latest_succeeded_job(session, aoi.id)
            if baseline is None:
                logger.info("recheck skip %s: no successful job to baseline from", aoi.slug)
                continue
            capture = session.get(Scene, baseline.after_scene_id).captured_at.date()
            windows = recheck_windows(capture, now.date())
            if windows is None:
                logger.info("recheck skip %s: baseline capture is today", aoi.slug)
                continue
            params = {
                "before": {
                    "start": windows.before[0].isoformat(),
                    "end": windows.before[1].isoformat(),
                },
                "after": {
                    "start": windows.after[0].isoformat(),
                    "end": windows.after[1].isoformat(),
                },
            }
            job = create_job(session, aoi.id, params)
            stamp_checked(session, aoi.id, now)
            session.commit()  # visible to the worker before dispatch
            dispatch_detection_job(str(job.id))
            submitted += 1
    return submitted
```

In `backend/src/overwatch/workers/celery_app.py`, add the beat schedule (import `crontab` at top):

```python
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "enqueue-due-rechecks": {
        "task": "overwatch.enqueue_due_rechecks",
        "schedule": crontab(hour=3, minute=0),  # daily tick; per-AOI cadence_days decides
    },
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker compose exec api pytest tests/test_recheck.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Restart beat, check the schedule loads**

Run: `docker compose restart worker beat && docker compose logs beat --tail 20`
Expected: beat starts clean, schedule includes `enqueue-due-rechecks`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/workers/recheck.py backend/src/overwatch/workers/tasks.py backend/src/overwatch/workers/celery_app.py backend/tests/test_recheck.py
git commit -m "feat(phase-3): weekly re-check via daily beat tick + pure due logic"
```

---

### Task 12: Verification gate (live), docs, push

**Files:**
- Modify: `PROGRESS.md`, this plan (append evidence)

**Interfaces:** none — this is the roadmap gate: *submit AOI via API → detections queryable by spatial predicate → re-run yields zero duplicate rows → job failure path retries visibly.*

- [ ] **Step 1: Full suite + lint in-container**

Run: `docker compose exec api pytest -q && docker compose exec api ruff check . && docker compose exec api ruff format --check .`
Expected: all green (record exact test count).

- [ ] **Step 2: Migrate + seed the live DB**

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m overwatch.db.seed
docker compose exec api python -m overwatch.db.seed   # second run: same ids printed (idempotent)
```

- [ ] **Step 3: Live pipeline — submit Vizhinjam via the API and poll**

```bash
docker compose restart worker beat   # ensure workers run current code
docker compose exec api python - <<'PY'
import json, time, urllib.request

BASE = "http://localhost:8000"
body = json.dumps({
    "before": {"start": "2021-02-01", "end": "2021-02-28"},
    "after": {"start": "2025-02-01", "end": "2025-02-28"},
}).encode()
req = urllib.request.Request(
    f"{BASE}/aois/vizhinjam/jobs", data=body, headers={"Content-Type": "application/json"}
)
job_id = json.loads(urllib.request.urlopen(req).read())["job_id"]
print("job:", job_id)
for _ in range(300):  # poll ~2s, generous ceiling for two COG ingests
    job = json.loads(urllib.request.urlopen(f"{BASE}/jobs/{job_id}").read())
    print(job["status"], job["stage"], "attempts=", job["attempts"])
    if job["status"] in ("succeeded", "failed"):
        print(json.dumps(job, indent=2))
        break
    time.sleep(2)
PY
```

Expected: stages walk `ingest_before → ingest_after → detect`, terminal `succeeded` with `detection_count > 0` (exact count depends on which scenes the gate selects within the windows; the known 2021-02-12/2025-02-11 pair gave 9).

- [ ] **Step 4: Spatial predicate query + idempotent re-run**

```bash
docker compose exec api python - <<'PY'
import json, time, urllib.request

BASE = "http://localhost:8000"
url = f"{BASE}/aois/vizhinjam/detections?intersects=76.960,8.355,77.010,8.395&change_type=construction"
first = json.loads(urllib.request.urlopen(url).read())["features"]
print("features:", len(first), "largest m2:", max(f["properties"]["area_m2"] for f in first))

body = json.dumps({
    "before": {"start": "2021-02-01", "end": "2021-02-28"},
    "after": {"start": "2025-02-01", "end": "2025-02-28"},
}).encode()
req = urllib.request.Request(
    f"{BASE}/aois/vizhinjam/jobs", data=body, headers={"Content-Type": "application/json"}
)
job_id = json.loads(urllib.request.urlopen(req).read())["job_id"]
while True:
    job = json.loads(urllib.request.urlopen(f"{BASE}/jobs/{job_id}").read())
    if job["status"] in ("succeeded", "failed"):
        break
    time.sleep(2)
second = json.loads(urllib.request.urlopen(url).read())["features"]
print("re-run status:", job["status"], "features after re-run:", len(second))
assert len(second) == len(first), "DUPLICATES!"
print("zero duplicate rows: OK")
PY
```

Expected: same feature count before/after the re-run (replace-set proven live, on top of the unit proof).

- [ ] **Step 5: Failure path — visible retries then structured failure**

Run the worker against an unreachable STAC endpoint, submit, watch attempts climb:

```bash
docker compose stop worker
docker compose run --rm --no-deps -d --name overwatch-broken-worker -e OVERWATCH_STAC_API_URL=http://127.0.0.1:9/does-not-exist worker
# submit a job (same submit snippet as Step 3), then poll GET /jobs/{id}:
# expected: attempts increments 1..4 across backoff retries, then status=failed,
# error.code == "task_failed" with the connection error message.
docker stop overwatch-broken-worker          # remove the ad-hoc worker (--rm cleans it up)
docker compose up -d worker                  # restore the real worker
```

Also verify fast-fail (no retries): submit `{"before": {"start": "2015-01-01", "end": "2015-01-05"}, ...}` (pre-Sentinel-2 coverage) → quick `failed` with `error.code == "no_usable_scene"`.

- [ ] **Step 6: Beat sanity**

```bash
docker compose exec api python -c "from overwatch.workers.celery_app import celery_app; print(celery_app.conf.beat_schedule)"
docker compose exec api python -c "from overwatch.workers.tasks import enqueue_due_rechecks; print('submitted:', enqueue_due_rechecks())"
```

Expected: schedule prints the daily entry; direct call returns `0` (showcase AOIs have no cadence set) — set `cadence_days=7` on one AOI via SQL and re-run to see `1` if you want the positive case live.

- [ ] **Step 7: Append evidence + update PROGRESS.md**

Append a `## Verification Gate — evidence (2026-MM-DD)` section to this plan with the actual outputs of Steps 1–6. Update `PROGRESS.md`: move Phase 3 into **Built & verified** with the verification notes, set **Current phase** to "Phase 3 complete, awaiting merge; next Phase 4", note any deviations discovered.

- [ ] **Step 8: Commit, push, hand over**

```bash
git add PROGRESS.md plans/2026-07-07-phase-3-persistence-api-jobs.md
git commit -m "docs(phase-3): verification evidence, PROGRESS update"
git push -u origin phase-3-persistence-api-jobs
```

End by giving the user the compare URL: `https://github.com/yash2484/Overwatch/compare/main...phase-3-persistence-api-jobs` (CI runs on the PR via the `pull_request` trigger; verify green before merging).

---

## Verification Gate — evidence (2026-07-09, all in-container)

Roadmap gate: *submit AOI via API → detections queryable by spatial predicate → re-run yields zero duplicate rows → job failure path retries visibly.* **All four met.**

### 1. Suite + lint
```
docker compose exec api pytest -q          -> 117 passed, 2 warnings in 7.37s
docker compose exec api ruff check .       -> All checks passed!
docker compose exec api ruff format --check .  -> 81 files already formatted
```
(76 at Phase-2 close → 117; +41 Phase-3 tests.)

### 2. Migrate + idempotent seed
```
alembic upgrade head            -> 0002 applied
python -m overwatch.db.seed     -> seeded 3 showcase aois: [6, 7, 8]
python -m overwatch.db.seed     -> seeded 3 showcase aois: [6, 7, 8]   (same ids, idempotent)
```

### 3. Live pipeline — API submit → Celery chain → PostGIS
`POST /aois/vizhinjam/jobs` with before 2021-02-01..28, after 2025-02-01..28 → **HTTP 202**, job `9b1bf77c…`.
Polling `GET /jobs/{id}` every 2 s:
```
[  0.0s] status=queued    stage=None           attempts=0
[  2.1s] status=running   stage=ingest_before  attempts=2
[ 88.7s] status=running   stage=ingest_after   attempts=3
[171.3s] status=running   stage=detect         attempts=4
[463.4s] status=succeeded stage=detect         attempts=4
         before_scene_id=5  after_scene_id=11  detection_count=12  error=null
```
Gate-selected scenes (cloud-ascending, SCL-verified):
`S2A_43PGK_20210212_2_L2A` usable 0.999, cloud 0.03% · `S2C_43PGK_20250211_0_L2A` usable 0.983, cloud 1.9%.

**Why attempts=4, not 3 (one per stage):** a genuine transient DNS failure inside the worker container
(`Failed to resolve earth-search.aws.element84.com`) raised `TransientIngestError` during `ingest_before`;
Celery retried after 1 s and the stage succeeded. The retry path proved itself unprompted, in production.

**Why 12 detections where Phase 2 recorded 9 (same dates):** the catalog holds two *reprocessings* of the
2021-02-12 acquisition. The Phase-2 CLI takes catalog order (`…_0_L2A`, cloud 0.1416%); the Phase-3 gate sorts
cloud-ascending and takes `…_2_L2A` (cloud 0.0313%). Both carry `dn_offset=0`, so this is **not** a BOA-harmonization
bug — different atmospheric reprocessing yields slightly different surface reflectance, hence a few more polygons.
Selection is deterministic (strict cloud ordering, no tie), and the job picks the cleaner scene. Not tuned; recorded as-is.

### 4. Spatial predicate + idempotent re-run
```
GET /aois/vizhinjam/detections?intersects=76.960,8.355,77.010,8.395&change_type=construction
  -> 12 construction features, largest area_m2 = 18,200, geometry Polygon (EPSG:4326), src_epsg 32643
GET …?intersects=70.0,1.0,70.1,1.1   -> 0 features   (disjoint-bbox negative control; ST_Intersects really filters)

re-run identical windows -> job b06cf5e4…: succeeded, scenes=(5,11), detection_count=12, 469s
features before re-run: 12   after re-run: 12   -> ZERO DUPLICATE ROWS
detection row pks 37,38,39… -> 49,50,51…        (replace-set genuinely deleted+reinserted, not a no-op)
```

### 5. Failure path
**Visible retries → structured failure.** Worker run against an unreachable STAC endpoint
(`OVERWATCH_STAC_API_URL=http://127.0.0.1:9/does-not-exist`):
```
[0.0s] status=queued   stage=None          attempts=0
[2.0s] status=running  stage=ingest_before attempts=2
[4.0s] status=failed   stage=ingest_before attempts=4     (1 initial + max_retries=3)
error: {"code": "task_failed", "detail": {"task": "overwatch.ingest_scene"},
        "message": "scene search/read failed: … Connection refused"}
```
**Fast-fail, no wasted retries.** Pre-Sentinel-2 window (2015-01-01..05), real worker:
```
[10.1s] status=failed stage=ingest_before attempts=1
error: {"code": "no_usable_scene", "message": "no scene ≥70% usable in 2015-01-01..2015-01-05 after widening"}
```

### 6. Beat
```
beat_schedule: {'enqueue-due-rechecks': {task: 'overwatch.enqueue_due_rechecks',
                                         schedule: <crontab: 0 3 * * *>}}
no cadence set        -> submitted: 0
cadence_days=7 on vizhinjam -> first tick  -> submitted: 1
  recheck params: before 2025-02-11..2025-02-12 (last after-scene capture),
                  after  2025-02-12..2026-07-09 (everything newer)
  last_checked_at stamped: True
second tick (stamped) -> submitted: 0
```
(Dispatch stubbed for this check so due-selection/params/stamping were exercised without a second 8-minute
detection run; the real dispatch path is covered by §3, §4 and the API tests. DB restored to `cadence_days=NULL`.)

### 7. Final DB state
`aois=3  jobs=4  detections=12  scenes=8`

### Deviations from the plan, and why
1. **Task 5** — the plan's `session: Session = Depends(get_session)` trips ruff `B008`. Used
   `SessionDep = Annotated[Session, Depends(get_session)]`; behavior identical.
2. **Task 9** — the plan's retry test expected `celery.exceptions.Retry` from a direct call. Wrong: a direct call sets
   `request.called_directly`, and Celery's `retry()` then re-raises the original exception without retrying at all.
   Replaced with `.apply()`, which proves `attempts` climbs 1→4 and lands a structured `task_failed` — a stronger assertion.
   Kept a second test pinning the direct-call behavior.
3. **Task 9 (infra, not in the plan)** — `worker`/`beat` compose services had **no source bind-mount and no
   `OVERWATCH_DATABASE_URL`**. They silently ran the Phase-0 baked image and could not reach Postgres, so new tasks never
   registered. Both now mount `./backend/src` and depend on `postgis`.
4. **Task 12 (infra, not in the plan)** — `api` ran uvicorn without `--reload` despite the mounted source, so new routers
   404'd until a restart. Added `--reload --reload-dir /app/src` to the dev compose command.
5. **Task 1 / Task 6 (bugs found and fixed at the root)** — alembic's `fileConfig` disabled app loggers when migrations ran
   in-process; and the `clean_t3`/`db_session` fixture teardown order deadlocked cross-session. Both in `CONTEXT.md`.

### 8. Live AOI CRUD + 500 km² cap (against the running API)
```
POST /aois  (1°×1° box, ~12,300 km²)
  -> 422 {"error": {"code": "aoi_too_large",
                    "message": "AOI area 12308.8 km² exceeds the 500 km² cap",
                    "detail": {"area_km2": 12308.778361469453, "max_km2": 500.0}}}
POST /aois  (0.05°×0.05° box)   -> 201, area_km2 = 30.77
DELETE /aois/gate-ok            -> 204
```

### Re-verification immediately before push (fresh commands, 2026-07-09)
```
pytest -q                  -> 117 passed, 2 warnings in 7.89s   (exit 0)
ruff check .               -> All checks passed!
ruff format --check .      -> 81 files already formatted
alembic current            -> 0002 (head)
celery inspect registered  -> 4 overwatch tasks
GET /openapi.json          -> 6 paths: /aois, /aois/{slug}, /aois/{slug}/detections,
                                       /aois/{slug}/jobs, /health, /jobs/{job_id}
```
