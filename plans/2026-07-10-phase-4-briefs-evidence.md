# Phase 4 — Briefs + Evidence Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Design authority:** `design-specs/2026-07-10-phase-4-briefs-evidence-design.md` (approved 2026-07-10). On conflict, the design spec wins.

**Goal:** LLM-generated intelligence briefs over stored detections, with a three-gate deterministic validator proving every claim traces to real rows — validated/rejected/stale lifecycle end to end.

**Architecture:** New `overwatch.briefs` package (pure Pydantic models, prompt builder, validator, generator protocol + Anthropic/Fake impls, generation loop) + migration 0003 (`briefs`/`brief_claims`/`evidence_links`) + brief repository + one Celery task + three endpoints. Detection replace-set gains stale-marking.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (sync), alembic, Celery, FastAPI, `anthropic` SDK (`messages.parse` structured output).

## Global Constraints

- **All Python runs in-container**: `docker compose exec api pytest ...`; never install deps on the Windows host. Docker Desktop must be started manually.
- **Workers do not hot-reload**: `docker compose restart worker beat` after touching `backend/src/overwatch/workers/`. The api service reloads itself (`--reload`).
- Celery `retry()` is a no-op when a task is called directly — **task tests must use `task.apply(...)`** (CONTEXT.md).
- DB test fixtures: cleanup must depend on the session fixture's consumer (`db_session` depends on the clean fixture) — see `backend/tests/conftest.py` pattern (`clean_t3`).
- Type hints everywhere (`X | None`, `list[str]`); Pydantic v2 at boundaries; `ruff check` + `ruff format` green before every commit.
- No sampling params (`temperature` etc.) on Anthropic calls — they 400 on current models.
- CI must never need the Anthropic key: every test uses `FakeBriefGenerator` or a mocked client.
- The Anthropic key enters `.env` only at Task 9 (user provides; never committed).
- Commit per task with `feat(phase-4): ...` / `test(phase-4): ...` prefixes.

**Execution mode (approved):** mixed. Tasks 1–3 sequential (shared files). Tasks 4, 5, 6 may run as **three parallel agents** — they create disjoint new files and consume only Task 3's frozen interfaces. Tasks 7–9 sequential. Review gate after each stage.

---

### Task 1: Migration 0003 + ORM models + deps/config

**Files:**
- Create: `backend/alembic/versions/0003_create_briefs_claims_evidence.py`
- Modify: `backend/src/overwatch/db/models.py` (append three classes)
- Modify: `backend/pyproject.toml` (add `anthropic`)
- Modify: `backend/src/overwatch/config.py` (three new Settings fields)
- Test: `backend/tests/test_db_schema.py` (append)

**Interfaces:**
- Consumes: `Base`, `Aoi`, `Scene`, `DetectionEvent` from `overwatch.db.models`.
- Produces: ORM classes `Brief`, `BriefClaim`, `EvidenceLink`; `Settings.anthropic_model: str = "claude-opus-4-8"`, `Settings.brief_max_attempts: int = 3`, `Settings.brief_max_prompt_detections: int = 50`.

- [ ] **Step 1: Add the dependency and settings**

In `backend/pyproject.toml` dependencies, after `"psycopg[binary]>=3.2",` add:

```toml
    "anthropic>=0.116",
```

In `backend/src/overwatch/config.py`, after `max_aoi_km2`:

```python
    anthropic_model: str = "claude-opus-4-8"  # design spec §3; override for cost via env
    brief_max_attempts: int = 3  # design spec §4 — bounded regeneration
    brief_max_prompt_detections: int = 50  # design spec §3 — prompt cap, truncation logged
```

Rebuild so the dep exists in-container: `docker compose build api worker beat && docker compose up -d api worker beat`

- [ ] **Step 2: Write the failing schema test**

Append to `backend/tests/test_db_schema.py`:

```python
def test_briefs_tables_exist(migrated_db: None) -> None:
    insp = sa.inspect(engine)
    for table in ("briefs", "brief_claims", "evidence_links"):
        assert insp.has_table(table), f"missing table {table}"
    brief_cols = {c["name"] for c in insp.get_columns("briefs")}
    assert {
        "id", "aoi_id", "before_scene_id", "after_scene_id", "status",
        "attempts", "headline", "model", "usage", "violations", "error",
        "created_at", "updated_at",
    } <= brief_cols
    link_cols = {c["name"] for c in insp.get_columns("evidence_links")}
    assert {"claim_id", "evidence_type", "detection_id"} <= link_cols
```

(Match the file's existing import style — it already imports `sqlalchemy as sa` and the engine.)

- [ ] **Step 3: Run to verify it fails**

Run: `docker compose exec api pytest tests/test_db_schema.py -v`
Expected: FAIL — `missing table briefs`.

- [ ] **Step 4: Write migration 0003**

`backend/alembic/versions/0003_create_briefs_claims_evidence.py`:

```python
"""create briefs, brief_claims, evidence_links

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "briefs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "aoi_id",
            sa.BigInteger,
            sa.ForeignKey("aois.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("before_scene_id", sa.BigInteger, sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column("after_scene_id", sa.BigInteger, sa.ForeignKey("scenes.id"), nullable=False),
        # generating | validated | rejected | failed | stale (design spec §1.1, §1.6)
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("headline", sa.Text, nullable=True),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("usage", JSONB, nullable=False, server_default="{}"),
        sa.Column("violations", JSONB, nullable=True),
        sa.Column("error", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_briefs_aoi_created", "briefs", ["aoi_id", sa.text("created_at DESC")])
    op.create_index("ix_briefs_pair", "briefs", ["aoi_id", "before_scene_id", "after_scene_id"])

    op.create_table(
        "brief_claims",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "brief_id",
            sa.BigInteger,
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        # observed | context | reported | mixed — full Phase 5 enum now (design spec §1.7)
        sa.Column("claim_type", sa.Text, nullable=False),
        sa.UniqueConstraint("brief_id", "seq", name="uq_brief_claims_brief_seq"),
    )

    op.create_table(
        "evidence_links",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "claim_id",
            sa.BigInteger,
            sa.ForeignKey("brief_claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.Text, nullable=False),  # detection | article
        sa.Column(
            "detection_id",
            sa.BigInteger,
            sa.ForeignKey("detections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "evidence_type != 'detection' OR detection_id IS NOT NULL",
            name="ck_evidence_links_detection_id",
        ),
    )
    op.create_index("ix_evidence_links_claim", "evidence_links", ["claim_id"])
    op.create_index("ix_evidence_links_detection", "evidence_links", ["detection_id"])


def downgrade() -> None:
    op.drop_table("evidence_links")
    op.drop_table("brief_claims")
    op.drop_table("briefs")
```

- [ ] **Step 5: Append ORM classes**

Append to `backend/src/overwatch/db/models.py` (imports for `BigInteger`, `Integer`, `Text`, `DateTime`, `ForeignKey`, `JSONB`, `func`, `UniqueConstraint`, `CheckConstraint` — extend the existing import lines):

```python
class Brief(Base):
    """One generated brief over a scene pair (Phase 4 design §2). Append-only history."""

    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aoi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aois.id", ondelete="CASCADE"), nullable=False
    )
    before_scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scenes.id"), nullable=False)
    after_scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scenes.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    headline: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    violations: Mapped[list[Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BriefClaim(Base):
    __tablename__ = "brief_claims"
    __table_args__ = (UniqueConstraint("brief_id", "seq", name="uq_brief_claims_brief_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    brief_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("briefs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(Text, nullable=False)


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (
        CheckConstraint(
            "evidence_type != 'detection' OR detection_id IS NOT NULL",
            name="ck_evidence_links_detection_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brief_claims.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False)
    detection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("detections.id", ondelete="CASCADE")
    )
```

- [ ] **Step 6: Migrate + run tests**

Run: `docker compose exec api alembic upgrade head && docker compose exec api pytest tests/test_db_schema.py -v`
Expected: `alembic current` at 0003; test PASSES.

- [ ] **Step 7: Lint + commit**

Run: `docker compose exec api ruff check . && docker compose exec api ruff format .`

```bash
git add backend/alembic/versions/0003_create_briefs_claims_evidence.py backend/src/overwatch/db/models.py backend/pyproject.toml backend/src/overwatch/config.py backend/tests/test_db_schema.py
git commit -m "feat(phase-4): briefs/brief_claims/evidence_links schema (migration 0003) + anthropic dep"
```

---

### Task 2: Brief repository + staleness on detection replace-set

**Files:**
- Create: `backend/src/overwatch/db/briefs.py`
- Modify: `backend/src/overwatch/db/detections.py` (`replace_detections` gains stale-marking)
- Test: `backend/tests/test_briefs_db.py`

**Interfaces:**
- Consumes: ORM `Brief`/`BriefClaim`/`EvidenceLink` (Task 1); existing `replace_detections(...)`.
- Produces (exact signatures — Tasks 7/8 depend on these):

```python
def create_brief(session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int) -> Brief  # status="generating"
def get_brief(session: Session, brief_id: int) -> Brief | None
def latest_validated_brief(session: Session, aoi_id: int) -> Brief | None
def claims_with_evidence(session: Session, brief_id: int) -> list[tuple[BriefClaim, list[EvidenceLink]]]
def persist_validated(session: Session, brief_id: int, *, headline: str, claims: list[tuple[str, str, list[int]]], model: str, usage: dict[str, int], attempts: int, failures: list[dict]) -> None
def mark_rejected(session: Session, brief_id: int, *, failures: list[dict], attempts: int, model: str | None, usage: dict[str, int]) -> None
def mark_failed(session: Session, brief_id: int, *, code: str, message: str) -> None
def mark_stale_briefs(session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int) -> int
def detection_rows_for_pair(session: Session, *, aoi_id: int, before_scene_id: int, after_scene_id: int) -> list[DetectionEvent]
```

`persist_validated` claims tuples are `(text, claim_type, detection_ids)` in seq order; it inserts `BriefClaim` rows (seq = index) and one `EvidenceLink(evidence_type="detection")` per id, sets `headline/model/usage/attempts/violations=failures/status="validated"`. All mutators bump `updated_at` via `func.now()`.

- [ ] **Step 1: Write failing repo tests**

`backend/tests/test_briefs_db.py` — use existing `db_session` fixture. Helpers: insert an AOI + two scenes + a job + detections via the same helper style as `backend/tests/test_detections_db.py` (copy its `_mk_aoi`/scene-insert helpers if not importable). Tests:

```python
def test_create_and_get_brief(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    brief = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    assert brief.status == "generating" and brief.attempts == 0
    assert get_brief(db_session, brief.id).id == brief.id
    assert get_brief(db_session, 999_999) is None


def test_persist_validated_writes_claims_and_links(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    det_ids = _seed_detections(db_session, aoi_id, before_id, after_id, n=2)
    brief = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    persist_validated(
        db_session, brief.id, headline="H",
        claims=[("obs claim", "observed", det_ids), ("ctx claim", "context", [])],
        model="claude-opus-4-8", usage={"input_tokens": 10, "output_tokens": 5},
        attempts=1, failures=[],
    )
    got = get_brief(db_session, brief.id)
    assert got.status == "validated" and got.headline == "H"
    pairs = claims_with_evidence(db_session, brief.id)
    assert [c.seq for c, _ in pairs] == [0, 1]
    assert sorted(link.detection_id for link in pairs[0][1]) == sorted(det_ids)
    assert pairs[1][1] == []


def test_latest_validated_brief_skips_non_validated(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    rejected = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    mark_rejected(db_session, rejected.id, failures=[{"violations": []}], attempts=3, model="m", usage={})
    old = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    persist_validated(db_session, old.id, headline="old", claims=[("c", "context", [])],
                      model="m", usage={}, attempts=1, failures=[])
    new = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    persist_validated(db_session, new.id, headline="new", claims=[("c", "context", [])],
                      model="m", usage={}, attempts=1, failures=[])
    assert latest_validated_brief(db_session, aoi_id).id == new.id


def test_replace_detections_marks_validated_briefs_stale(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    det_ids = _seed_detections(db_session, aoi_id, before_id, after_id, n=1)
    brief = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    persist_validated(db_session, brief.id, headline="H",
                      claims=[("c", "observed", det_ids)], model="m",
                      usage={}, attempts=1, failures=[])
    job_id = _seed_job(db_session, aoi_id)
    replace_detections(db_session, aoi_id=aoi_id, job_id=job_id,
                       before_scene_id=before_id, after_scene_id=after_id, detections=[])
    assert get_brief(db_session, brief.id).status == "stale"
    # evidence links cascade away with the deleted detections
    assert claims_with_evidence(db_session, brief.id)[0][1] == []


def test_replace_detections_leaves_other_pairs_and_statuses_alone(db_session: Session) -> None:
    aoi_id, before_id, after_id = _seed_pair(db_session)
    other_before, other_after = _seed_scene(db_session, aoi_id), _seed_scene(db_session, aoi_id)
    rejected_same_pair = create_brief(db_session, aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id)
    mark_rejected(db_session, rejected_same_pair.id, failures=[], attempts=3, model="m", usage={})
    validated_other_pair = create_brief(db_session, aoi_id=aoi_id, before_scene_id=other_before, after_scene_id=other_after)
    persist_validated(db_session, validated_other_pair.id, headline="H", claims=[("c", "context", [])],
                      model="m", usage={}, attempts=1, failures=[])
    job_id = _seed_job(db_session, aoi_id)
    replace_detections(db_session, aoi_id=aoi_id, job_id=job_id,
                       before_scene_id=before_id, after_scene_id=after_id, detections=[])
    assert get_brief(db_session, rejected_same_pair.id).status == "rejected"
    assert get_brief(db_session, validated_other_pair.id).status == "validated"
```

(`_seed_pair`/`_seed_scene`/`_seed_job`/`_seed_detections` are small module-local helpers following `test_detections_db.py`'s seeding style — write them at the top of the file.) Also extend `conftest.py`'s cleanup DELETE list with `evidence_links, brief_claims, briefs` **before** `detections` (FK order), following the existing `clean_t3` pattern.

- [ ] **Step 2: Run to verify failure**

Run: `docker compose exec api pytest tests/test_briefs_db.py -v`
Expected: FAIL — `ModuleNotFoundError: overwatch.db.briefs`.

- [ ] **Step 3: Implement `db/briefs.py`**

Implement every signature from the Interfaces block. Notes: `latest_validated_brief` = `select(Brief).where(aoi_id=..., status=="validated").order_by(Brief.created_at.desc()).limit(1)`; `mark_stale_briefs` = `update(Brief).where(pair match, status=="validated").values(status="stale", updated_at=func.now())` returning rowcount; `detection_rows_for_pair` = `select(DetectionEvent).where(pair match).order_by(DetectionEvent.area_m2.desc())`.

- [ ] **Step 4: Wire stale-marking into `replace_detections`**

In `backend/src/overwatch/db/detections.py`, at the **top** of `replace_detections` (before the DELETE, same transaction):

```python
    from overwatch.db.briefs import mark_stale_briefs

    mark_stale_briefs(
        session, aoi_id=aoi_id, before_scene_id=before_scene_id, after_scene_id=after_scene_id
    )
```

(Top-level import if no circularity — `briefs.py` must not import `detections.py`.)

- [ ] **Step 5: Run tests, lint, commit**

Run: `docker compose exec api pytest tests/test_briefs_db.py tests/test_detections_db.py -v` → all PASS; ruff clean.

```bash
git add backend/src/overwatch/db/briefs.py backend/src/overwatch/db/detections.py backend/tests/test_briefs_db.py backend/tests/conftest.py
git commit -m "feat(phase-4): brief repository + stale-marking on detection replace-set"
```

---

### Task 3: `briefs` package Pydantic contracts (frozen interface for the parallel lanes)

**Files:**
- Create: `backend/src/overwatch/briefs/__init__.py` (empty)
- Create: `backend/src/overwatch/briefs/models.py`
- Test: `backend/tests/test_brief_models.py`

**Interfaces:**
- Produces (Tasks 4–8 all consume these — **do not rename after this task lands**):

```python
ClaimType = Literal["observed", "context", "reported", "mixed"]

class ClaimDraft(BaseModel):
    text: str
    claim_type: ClaimType
    evidence: list[int] = []          # detection ids

class BriefDraft(BaseModel):
    headline: str
    claims: list[ClaimDraft]

class Violation(BaseModel):
    code: str
    claim_seq: int | None = None
    message: str
    detail: dict[str, Any] | None = None

class DetectionRow(BaseModel):        # slim view for prompt + validator
    id: int
    change_type: str
    area_m2: float
    magnitude: float
    confidence: float

class BriefRequest(BaseModel):
    aoi_name: str
    aoi_slug: str
    vertical: str
    before_scene_id: int
    after_scene_id: int
    before_date: date
    after_date: date
    detections: list[DetectionRow]

class AttemptFailure(BaseModel):
    draft: BriefDraft
    violations: list[Violation]

class BriefGeneration(BaseModel):
    draft: BriefDraft
    model: str
    usage: dict[str, int]             # input_tokens, output_tokens
```

- [ ] **Step 1: Failing test** — round-trip: `BriefDraft.model_validate_json(draft.model_dump_json())`; `ClaimDraft(claim_type="bogus")` raises `ValidationError`; `AttemptFailure` serializes with nested violations.
- [ ] **Step 2: Run** `docker compose exec api pytest tests/test_brief_models.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `models.py` exactly per the Interfaces block.
- [ ] **Step 4: Run → PASS; lint.**
- [ ] **Step 5: Commit** — `git add backend/src/overwatch/briefs backend/tests/test_brief_models.py && git commit -m "feat(phase-4): briefs package contracts (drafts, violations, request)"`

---

> **Stage 2 — Tasks 4, 5, 6 may run in PARALLEL** (three agents). Disjoint files; all consume only Task 3's frozen contracts. None imports another lane's module.

### Task 4 (Lane A): Validator — three deterministic gates

**Files:**
- Create: `backend/src/overwatch/briefs/validator.py`
- Test: `backend/tests/test_brief_validator.py`

**Interfaces:**
- Consumes: Task 3 models.
- Produces: `def validate_brief(draft: BriefDraft, request: BriefRequest) -> list[Violation]` — empty list = valid. Violation codes (exact strings, Task 7 stores them verbatim): `empty_brief`, `blank_claim`, `unsupported_claim_type`, `unlinked_claim`, `unknown_evidence_id`, `quantified_context_claim`, `area_mismatch`, `date_mismatch`.

- [ ] **Step 1: Failing tests — one family per gate** (`_req()` helper builds a `BriefRequest` with detections id=1 (area 12_000.0) and id=2 (area 6_200.0), dates 2021-02-12 / 2025-02-11):

```python
def test_valid_brief_passes() -> None:
    draft = BriefDraft(headline="H", claims=[
        ClaimDraft(text="Construction added about 18,200 m² between 2021-02-12 and 2025-02-11.",
                   claim_type="observed", evidence=[1, 2]),
        ClaimDraft(text="Vizhinjam is a deepwater transshipment port.", claim_type="context"),
    ])
    assert validate_brief(draft, _req()) == []

def test_structural_gates() -> None:
    assert any(v.code == "empty_brief" for v in validate_brief(BriefDraft(headline="H", claims=[]), _req()))
    draft = BriefDraft(headline="H", claims=[ClaimDraft(text="  ", claim_type="context")])
    assert any(v.code == "blank_claim" for v in validate_brief(draft, _req()))
    draft = BriefDraft(headline="H", claims=[ClaimDraft(text="News says so.", claim_type="reported")])
    assert any(v.code == "unsupported_claim_type" for v in validate_brief(draft, _req()))  # Phase 4

def test_gate1_linkage() -> None:
    draft = BriefDraft(headline="H", claims=[ClaimDraft(text="Something changed.", claim_type="observed")])
    assert any(v.code == "unlinked_claim" and v.claim_seq == 0 for v in validate_brief(draft, _req()))
    draft = BriefDraft(headline="H", claims=[ClaimDraft(text="x", claim_type="observed", evidence=[999])])
    assert any(v.code == "unknown_evidence_id" for v in validate_brief(draft, _req()))

def test_gate2_context_hygiene() -> None:
    for text in ("Cleared 5,000 m² of land.", "About 40% of the port.", "Work began on 2023-05-01."):
        draft = BriefDraft(headline="H", claims=[ClaimDraft(text=text, claim_type="context")])
        assert any(v.code == "quantified_context_claim" for v in validate_brief(draft, _req())), text

def test_gate3_area_within_10pct_passes_outside_fails() -> None:
    ok = BriefDraft(headline="H", claims=[ClaimDraft(text="Roughly 12,500 m² of new surface.",
                                                     claim_type="observed", evidence=[1])])  # 12,000 ±10%
    assert validate_brief(ok, _req()) == []
    bad = BriefDraft(headline="H", claims=[ClaimDraft(text="Roughly 50,000 m² of new surface.",
                                                      claim_type="observed", evidence=[1])])
    assert any(v.code == "area_mismatch" for v in validate_brief(bad, _req()))

def test_gate3_km2_and_ha_units_normalize() -> None:
    ok = BriefDraft(headline="H", claims=[ClaimDraft(text="About 0.012 km² changed.",
                                                     claim_type="observed", evidence=[1])])
    assert validate_brief(ok, _req()) == []

def test_gate3_date_mismatch() -> None:
    bad = BriefDraft(headline="H", claims=[ClaimDraft(text="Captured on 2020-01-01.",
                                                      claim_type="observed", evidence=[1])])
    assert any(v.code == "date_mismatch" for v in validate_brief(bad, _req()))
    ok = BriefDraft(headline="H", claims=[ClaimDraft(text="Between February 2021 and February 2025.",
                                                     claim_type="observed", evidence=[1])])
    assert validate_brief(ok, _req()) == []
```

- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implement `validator.py`.** Implementation notes (keep pure — no I/O):
  - Quantity regex: `_AREA_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(m²|m2|sq\s?m|km²|km2|ha|hectares?)", re.I)`; percent `r"\d[\d,.]*\s*%"`; ISO date `r"\d{4}-\d{2}-\d{2}"`; month-name `r"(January|February|...|December)\s+\d{4}"` (full 12 months).
  - Unit → m²: `km²*1e6`, `ha*1e4`, else 1. Strip commas before `float()`.
  - Gate 3 area: for each observed claim, every area figure must be within ±10% of `sum(area_m2 of linked detections)`; if a claim quotes an area but links resolve to zero detections it is already an `unlinked_claim`. Tolerance: `abs(value - total) <= 0.10 * total`.
  - Gate 3 dates: each ISO date must equal `before_date` or `after_date` exactly; each month-name match must equal either date's (month, year).
  - Gate 2 fires when a `context` claim contains any area/percent/date pattern.
  - Structural: `unsupported_claim_type` for `reported`/`mixed` (Phase 4 rule — Phase 5 lifts it).
- [ ] **Step 4: Run → PASS; lint.**
- [ ] **Step 5: Commit** — `feat(phase-4): three-gate brief validator (linkage, context hygiene, numeric consistency)`

---

### Task 5 (Lane B): Generators + generation loop

**Files:**
- Create: `backend/src/overwatch/briefs/generator.py`
- Create: `backend/src/overwatch/briefs/loop.py`
- Test: `backend/tests/test_brief_generator.py`, `backend/tests/test_brief_loop.py`

**Interfaces:**
- Consumes: Task 3 models; `overwatch.briefs.prompt.build_messages(request, failures) -> list[dict]` and `SYSTEM_PROMPT` (Task 6 — for THIS task's tests, monkeypatch or import guard is unnecessary: `generator.py` imports `prompt` lazily inside `AnthropicBriefGenerator.generate` so Lane B's tests of Fake + loop never touch it; the Anthropic unit test stubs `build_messages`).
- Produces:

```python
class BriefGenerator(Protocol):
    def generate(self, request: BriefRequest, failures: list[AttemptFailure]) -> BriefGeneration: ...

FAKE_INPUT_TOKENS = 100   # module constants — every Fake call reports this usage
FAKE_OUTPUT_TOKENS = 50

class FakeBriefGenerator:
    def __init__(self, drafts: list[BriefDraft], model: str = "fake") -> None: ...
    # returns drafts in order (raises AssertionError if exhausted);
    # records .calls: list[list[AttemptFailure]] (the feedback each call received);
    # every BriefGeneration.usage == {"input_tokens": FAKE_INPUT_TOKENS, "output_tokens": FAKE_OUTPUT_TOKENS}

class TransientBriefError(Exception): ...
class PermanentBriefError(Exception):
    def __init__(self, code: str, message: str) -> None: ...

class AnthropicBriefGenerator:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None) -> None: ...

class LoopResult(BaseModel):
    status: Literal["validated", "rejected"]
    draft: BriefDraft | None
    failures: list[AttemptFailure]
    attempts: int
    model: str | None
    usage: dict[str, int]              # summed across attempts

def run_brief_loop(generator: BriefGenerator, request: BriefRequest, *,
                   validate: Callable[[BriefDraft, BriefRequest], list[Violation]],
                   max_attempts: int) -> LoopResult
```

- [ ] **Step 1: Failing loop tests** (stub validator — no dependency on Lane A):

```python
def _reject_first_n(n: int):
    calls = {"count": 0}
    def validate(draft: BriefDraft, request: BriefRequest) -> list[Violation]:
        calls["count"] += 1
        if calls["count"] <= n:
            return [Violation(code="unlinked_claim", claim_seq=0, message="no evidence")]
        return []
    return validate

def test_first_try_validates() -> None:
    gen = FakeBriefGenerator([_draft("A")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(0), max_attempts=3)
    assert result.status == "validated" and result.attempts == 1 and result.failures == []

def test_feedback_flows_to_second_attempt() -> None:
    gen = FakeBriefGenerator([_draft("A"), _draft("B")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(1), max_attempts=3)
    assert result.status == "validated" and result.attempts == 2
    assert gen.calls[1][0].violations[0].code == "unlinked_claim"  # attempt 2 saw attempt 1's violations
    assert result.usage["output_tokens"] == 2 * FAKE_OUTPUT_TOKENS  # summed

def test_three_strikes_rejected_with_full_history() -> None:
    gen = FakeBriefGenerator([_draft("A"), _draft("B"), _draft("C")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(99), max_attempts=3)
    assert result.status == "rejected" and result.attempts == 3
    assert len(result.failures) == 3 and result.draft is None
```

Plus Anthropic unit tests (mock client object; no network): `parsed_output` returned → `BriefGeneration` with usage extracted; `stop_reason == "refusal"` → `PermanentBriefError("brief_refused", ...)`; `parsed_output is None` → `PermanentBriefError("brief_parse_failed", ...)`; `anthropic.RateLimitError`/`APIConnectionError`/5xx `APIStatusError` → re-raised as `TransientBriefError`; `anthropic.AuthenticationError` → `PermanentBriefError("anthropic_auth", ...)`. Build the mock with `unittest.mock.MagicMock()` shaped like the SDK response (`.parsed_output`, `.usage.input_tokens`, `.usage.output_tokens`, `.stop_reason`, `.model`).

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** `AnthropicBriefGenerator.generate`:

```python
def generate(self, request: BriefRequest, failures: list[AttemptFailure]) -> BriefGeneration:
    from overwatch.briefs.prompt import SYSTEM_PROMPT, build_messages  # lazy: lane isolation

    try:
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=build_messages(request, failures),
            output_format=BriefDraft,
        )
    except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
        raise TransientBriefError(str(exc)) from exc
    except anthropic.AuthenticationError as exc:
        raise PermanentBriefError("anthropic_auth", str(exc)) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise TransientBriefError(str(exc)) from exc
        raise PermanentBriefError("anthropic_bad_request", str(exc)) from exc
    if resp.stop_reason == "refusal":
        raise PermanentBriefError("brief_refused", "model refused the request")
    if resp.parsed_output is None:
        raise PermanentBriefError("brief_parse_failed", "no parseable structured output")
    return BriefGeneration(
        draft=resp.parsed_output,
        model=resp.model,
        usage={"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
    )
```

Default client: `anthropic.Anthropic(api_key=settings.anthropic_api_key)`; default model `settings.anthropic_model`. No `temperature` anywhere. `run_brief_loop` accumulates usage per attempt and appends `AttemptFailure(draft, violations)` on each failed validation.

- [ ] **Step 4: Run → PASS; lint.**
- [ ] **Step 5: Commit** — `feat(phase-4): BriefGenerator protocol, Anthropic/Fake impls, bounded generation loop`

---

### Task 6 (Lane C): Prompt builder

**Files:**
- Create: `backend/src/overwatch/briefs/prompt.py`
- Test: `backend/tests/test_brief_prompt.py`

**Interfaces:**
- Consumes: Task 3 models; `settings.brief_max_prompt_detections`.
- Produces: `SYSTEM_PROMPT: str`; `def build_messages(request: BriefRequest, failures: list[AttemptFailure]) -> list[dict[str, str]]`.

- [ ] **Step 1: Failing tests:**
  - First message is `role="user"` and contains AOI name, vertical, both ISO dates, and every detection id when under the cap.
  - **Truncation**: 60 detections → only the 50 largest by `area_m2` serialized; message contains aggregate stats naming the true total count (`"60 detections"`), total area, per-change-type counts; `caplog` records a truncation warning (`logging.getLogger("overwatch.briefs.prompt")`).
  - **Feedback rendering**: one `AttemptFailure` → messages gain `assistant` turn (the draft's JSON) + `user` turn containing each violation code and message; two failures → 5 messages total (user, asst, user, asst, user).
  - `SYSTEM_PROMPT` contains the citation instruction ("cite detections by id") and the context-claim rule ("no quantities").
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** SYSTEM_PROMPT (verbatim start point — tune only if the live gate demands):

```python
SYSTEM_PROMPT = """You are an imagery analyst writing an intelligence brief about satellite-detected \
change in one area of interest, comparing a BEFORE scene and an AFTER scene.

Rules you must follow exactly:
- Every claim of type "observed" must cite the detection ids that support it in its evidence list, \
and any quantity you state must come from those detections' recorded values (areas in m²; dates are \
the two capture dates provided).
- Claims of type "context" give background only and must contain no numbers, percentages, areas, or dates.
- Use only claim types "observed" and "context".
- Never invent detections, quantities, or dates. If the data does not support a statement, do not make it.
- Write 3-8 claims, ordered for reading: headline finding first, context last."""
```

User message body: AOI block (name, slug, vertical), pair block (scene ids + ISO dates), aggregate stats block, then `DETECTIONS (largest first):` with one line per row: `id=<id> type=<change_type> area_m2=<area:.0f> magnitude=<mag:.3f> confidence=<conf:.2f>`. Feedback user turn: `"Your previous draft failed validation. Fix ALL violations and return a corrected brief:"` + one line per violation: `- [<code>] claim #<seq>: <message>`.

- [ ] **Step 4: Run → PASS; lint.**
- [ ] **Step 5: Commit** — `feat(phase-4): brief prompt builder with detection cap + structured feedback`

> **Stage 2 merge gate:** all three lanes green together — `docker compose exec api pytest tests/test_brief_validator.py tests/test_brief_generator.py tests/test_brief_loop.py tests/test_brief_prompt.py -v` — then code review before Stage 3.

---

### Task 7: Celery task `generate_brief`

**Files:**
- Modify: `backend/src/overwatch/workers/tasks.py`
- Test: `backend/tests/test_brief_task.py`

**Interfaces:**
- Consumes: Task 2 repo functions; Tasks 4–6 modules; existing `celery_app`, `session_scope`.
- Produces: `celery_app.task(name="overwatch.generate_brief")`; module-level `def get_brief_generator() -> BriefGenerator` (monkeypatch seam, mirrors existing `get_provider()`); `def dispatch_brief(brief_id: int) -> None` (`.delay` wrapper, mirrors `dispatch_detection_job`).

- [ ] **Step 1: Failing tests** (all via `task.apply(args=[brief_id])` — CONTEXT.md rule; monkeypatch `get_brief_generator`):
  - Happy path: Fake validates first try → row `validated`, claims + links persisted, `model`/`usage`/`attempts=1` stored.
  - Rejection: Fake that always draws an `unlinked_claim` violation (draft with an evidence-free observed claim, real `validate_brief`) → after 3 attempts row is `rejected`, `violations` JSONB holds 3 attempt entries each with code `unlinked_claim` — **this is the roadmap's headline negative test**.
  - Transient: generator raises `TransientBriefError` → task retries (attempts climb via Celery retry, `max_retries=3`) then row `failed` with `error.code == "task_failed"`.
  - Permanent: generator raises `PermanentBriefError("anthropic_auth", ...)` → row `failed` fast with `error.code == "anthropic_auth"`, no retries.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** in `workers/tasks.py`:

```python
_BRIEF_RETRY = {
    "bind": True,
    "autoretry_for": (TransientBriefError,),
    "retry_backoff": True,
    "retry_backoff_max": 60,
    "retry_jitter": True,
    "max_retries": 3,
}


def get_brief_generator() -> BriefGenerator:
    return AnthropicBriefGenerator()


def dispatch_brief(brief_id: int) -> None:
    generate_brief.delay(brief_id)


@celery_app.task(name="overwatch.generate_brief", **_BRIEF_RETRY)
def generate_brief(self: Task, brief_id: int) -> None:
    with session_scope() as session:
        brief = get_brief(session, brief_id)
        if brief is None or brief.status not in ("generating",):
            return
        request = _build_brief_request(session, brief)   # loads AOI, scene dates, detection rows
    try:
        result = run_brief_loop(
            get_brief_generator(), request,
            validate=validate_brief, max_attempts=settings.brief_max_attempts,
        )
    except PermanentBriefError as exc:
        with session_scope() as session:
            mark_failed(session, brief_id, code=exc.code, message=str(exc))
        return
    # TransientBriefError propagates -> Celery autoretry; on exhaustion the
    # task's on_failure marks the brief failed with code "task_failed"
    with session_scope() as session:
        if result.status == "validated":
            persist_validated(session, brief_id, headline=result.draft.headline,
                              claims=[(c.text, c.claim_type, c.evidence) for c in result.draft.claims],
                              model=result.model, usage=result.usage,
                              attempts=result.attempts,
                              failures=[f.model_dump(mode="json") for f in result.failures])
        else:
            mark_rejected(session, brief_id,
                          failures=[f.model_dump(mode="json") for f in result.failures],
                          attempts=result.attempts, model=result.model, usage=result.usage)
```

`_build_brief_request`: AOI via `session.get(Aoi, ...)`; scene dates via `session.get(Scene, ...).captured_at.date()`; detections via `detection_rows_for_pair` mapped into `DetectionRow`. On-failure hook: follow the existing `JobTask` pattern — give the task a small `BriefTask` base whose `on_failure` marks the brief `failed` with `{"code": "task_failed", "message": str(exc)}` (mirror `JobTask` in the same file).

- [ ] **Step 4: Run tests → PASS; lint. Restart workers** (`docker compose restart worker beat`) and verify registration: `docker compose exec worker celery -A overwatch.workers.celery_app inspect registered | grep generate_brief`.
- [ ] **Step 5: Commit** — `feat(phase-4): generate_brief celery task — loop, retries, structured failure`

---

### Task 8: API endpoints

**Files:**
- Create: `backend/src/overwatch/api/briefs.py`
- Modify: `backend/src/overwatch/api/schemas.py` (add `BriefSubmit`, `ClaimOut`, `BriefOut`)
- Modify: `backend/src/overwatch/api/main.py` (include router)
- Test: `backend/tests/test_api_briefs.py`

**Interfaces:**
- Consumes: `SessionDep`, `require_aoi` (from `overwatch.api.aois`), `ApiError`, repo functions (Task 2), `latest_succeeded_job` (existing), `dispatch_brief` (Task 7), `settings.anthropic_api_key`.
- Produces:
  - `POST /aois/{slug}/briefs` body `BriefSubmit {before_scene_id: int | None = None, after_scene_id: int | None = None}` (model_validator: both-or-neither) → 202 `{"brief_id": <int>}`. Guards in order: 404 `aoi_not_found` (via `require_aoi`); 422 `briefs_unconfigured` when `not settings.anthropic_api_key`; explicit pair used as-is, else `latest_succeeded_job` → 409 `no_baseline_run` if none. Commit before dispatch (same rule as job submit).
  - `GET /briefs/{brief_id}` → `BriefOut {id, aoi_slug, status, attempts, headline, model, usage, violations, error, before_scene_id, after_scene_id, claims: list[ClaimOut], created_at, updated_at}`; `ClaimOut {seq, text, claim_type, detection_ids: list[int]}` (claims populated only when validated/stale). 404 `brief_not_found`.
  - `GET /aois/{slug}/brief` → latest validated `BriefOut`; 404 `no_validated_brief`.

- [ ] **Step 1: Failing tests** (existing TestClient pattern from `test_api_jobs.py`; monkeypatch `dispatch_brief` to a no-op recorder, monkeypatch `settings.anthropic_api_key` to `"test-key"` where needed):
  - submit defaults to latest succeeded job's pair; explicit pair honored; 409 when no succeeded job; 422 when key unset; 404 unknown slug; body with only one scene id → FastAPI 422 validation envelope.
  - poll returns claims + detection ids for a validated brief (seed via repo helpers); rejected brief exposes `violations`; unknown id → 404 `brief_not_found`.
  - latest endpoint returns the newest validated; 404 `no_validated_brief` when only rejected exist.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** router + schemas; register in `main.py` (`app.include_router(briefs.router)`), tag `briefs`.
- [ ] **Step 4: Run full suite** — `docker compose exec api pytest -q` → ALL green (117 + Phase 4 additions); lint.
- [ ] **Step 5: Commit** — `feat(phase-4): brief submit/poll/latest endpoints with guards`

---

### Task 9: Verification gate (live), docs, push

**Files:**
- Modify: `PROGRESS.md`, `plans/2026-07-10-phase-4-briefs-evidence.md` (append evidence), `CONTEXT.md` (if new gotchas)

- [ ] **Step 1: Full suite + lint in-container** — `pytest -q`, `ruff check .`, `ruff format --check .` → record counts.
- [ ] **Step 2: User provides the Anthropic key** → user adds `OVERWATCH_ANTHROPIC_API_KEY=...` to `.env` (never via chat, never committed) → `docker compose restart api worker beat`.
- [ ] **Step 3: Live happy path** — `POST /aois/vizhinjam/briefs {}` → 202; poll `GET /briefs/{id}` to `validated`; record headline + claims. SQL proof every link resolves to the exact pair:

```sql
SELECT count(*) FROM evidence_links el
JOIN brief_claims bc ON bc.id = el.claim_id
JOIN briefs b ON b.id = bc.brief_id
LEFT JOIN detections d ON d.id = el.detection_id
 AND d.aoi_id = b.aoi_id
 AND d.before_scene_id = b.before_scene_id
 AND d.after_scene_id = b.after_scene_id
WHERE b.id = <brief_id> AND d.id IS NULL;
-- expected: 0
```

- [ ] **Step 4: Rejected path surfaced** — confirm a rejected brief (from the Task 7 test DB run or a live forced run) returns violations via `GET /briefs/{id}`.
- [ ] **Step 5: Staleness live** — re-submit the detection job for the same windows (Phase 3 flow) → after it succeeds, the validated brief's status is `stale`; generate a fresh brief against the new rows → `validated`.
- [ ] **Step 6: Hygiene** — `git grep -iI "sk-ant"` → empty; `git status` shows `.env` untracked.
- [ ] **Step 7: Docs + push** — append evidence to this plan's "Verification Gate — evidence" section; update `PROGRESS.md` (Built & verified entry + Last verified working); `CONTEXT.md` for any new gotcha; commit `docs(phase-4): verification evidence`; push branch; give compare URL `https://github.com/yash2484/Overwatch/compare/main...phase-4-briefs-evidence`. CI green before asking for merge.

---

## Verification Gate — evidence

(Appended at Task 9 execution.)
