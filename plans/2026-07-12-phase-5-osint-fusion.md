# Phase 5 — OSINT Fusion (GDELT) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist deterministic news correlations for an AOI's scene pair, and let a brief cite them without ever
letting journalism masquerade as sensing.

**Architecture:** Fusion is a Celery task downstream of detection. `GdeltDocProvider` (I/O) retrieves candidates with a
conjunctive GDELT query; a **pure, unit-tested three-gate AND scorer** (toponym ∧ temporal ∧ thematic) admits survivors;
a pure dedup collapses syndication; a replace-set persists to `news_articles`. The brief validator gains **Gate 4** — the
observed/reported wall. `FUSION_ENABLED=false` removes the task from the chain and 503s the endpoint.

**Tech Stack:** Python 3.12, FastAPI, Celery, SQLAlchemy 2.0 + GeoAlchemy2, Alembic, Pydantic v2, `httpx`, pytest, ruff.

**Design authority:** `design-specs/2026-07-12-phase-5-osint-fusion-design.md`. Read §2 (spike results) before touching
anything — two of the inherited design-spec assumptions are false and the whole gate design follows from that.

## Global Constraints

- **Never call Gate 1 "spatial".** It is the **toponym** gate. No column, function, variable, log line, or comment may
  use the word "spatial" for it. GDELT has no geotag (design §2.2); the geofence was measured and rejects 100% of our
  true positives (design §2.4).
- **Never `json.loads` a GDELT response without checking.** A **429 returns plaintext**, and a **200 can also return a
  plaintext error** (*"keywords were too short, too long or too common"*). Both are real, both were hit during the spike.
- **CI never touches the network.** All provider tests run against `FakeNewsProvider` replaying recorded fixtures.
- **Additive changes only.** No renaming existing columns/constants (PROJECT.md §6b). Migration 0004 only adds.
- **Existing repo conventions:** `X | None` not `Optional[X]`; `list[str]` not `List[str]`; full type hints on public
  functions; ruff line-length 100; `select=["E","F","I","UP","B","SIM"]`.
- **Workers do not hot-reload** (CONTEXT.md). After changing `overwatch/workers/*`, run
  `docker compose restart worker beat`.
- **All commands run in-container:** `docker compose exec -T api <cmd>`.

---

## File Structure

**Create:**
- `backend/alembic/versions/0004_create_news_articles.py` — migration (additive)
- `backend/src/overwatch/fusion/__init__.py`
- `backend/src/overwatch/fusion/models.py` — `RawArticle`, `FusionWindow`, `GateResult` (pure Pydantic)
- `backend/src/overwatch/fusion/presets.py` — per-vertical themes, keywords, window bounds
- `backend/src/overwatch/fusion/normalize.py` — casefold/diacritic-fold/word-boundary matching (pure)
- `backend/src/overwatch/fusion/scorer.py` — the three-gate AND scorer + dedup (pure, TDD centrepiece)
- `backend/src/overwatch/fusion/provider.py` — `NewsProvider` protocol, `GdeltDocProvider`, `FakeNewsProvider`
- `backend/src/overwatch/db/news.py` — `replace_articles`, `articles_for_pair`
- `backend/src/overwatch/api/fusion.py` — `POST /aois/{slug}/fusion`
- `backend/tests/fixtures/gdelt/*.json` — verbatim spike responses
- `backend/tests/test_fusion_normalize.py`, `test_fusion_scorer.py`, `test_fusion_dedup.py`,
  `test_fusion_provider.py`, `test_news_db.py`, `test_fusion_task.py`, `test_api_fusion.py`

**Modify:**
- `backend/src/overwatch/db/models.py` — `NewsArticle`; `Aoi.place_terms`/`region_terms`; `EvidenceLink.article_id`
- `backend/src/overwatch/aois.py` — place/region terms on the three showcase AOIs
- `backend/src/overwatch/db/aois.py` — `upsert_aoi` carries the term arrays
- `backend/src/overwatch/briefs/models.py` — `ArticleRow`; `BriefRequest.articles`
- `backend/src/overwatch/briefs/validator.py` — Gate 4; lift `_SUPPORTED_CLAIM_TYPES`
- `backend/src/overwatch/briefs/prompt.py` — render articles into the prompt
- `backend/src/overwatch/db/briefs.py` — `persist_validated` writes article evidence links
- `backend/src/overwatch/workers/tasks.py` — `fuse` task, chain wiring, `_build_brief_request` carries articles
- `backend/src/overwatch/api/main.py` — mount the fusion router
- `backend/src/overwatch/config.py` — fusion settings
- `backend/pyproject.toml` — add `httpx` to runtime deps (it is currently dev-only)

---

## Task 1: Migration 0004 + ORM models

**Files:**
- Create: `backend/alembic/versions/0004_create_news_articles.py`
- Modify: `backend/src/overwatch/db/models.py`
- Test: `backend/tests/test_db_schema.py`

**Interfaces:**
- Consumes: existing `Base`, `Aoi`, `EvidenceLink` from `overwatch.db.models`.
- Produces: `NewsArticle` ORM class; `Aoi.place_terms: list[str] | None`, `Aoi.region_terms: list[str] | None`;
  `EvidenceLink.article_id: int | None`.

- [ ] **Step 1: Write the failing schema test**

Append to `backend/tests/test_db_schema.py`:

```python
def test_news_articles_table_and_natural_key(db_session):
    insp = inspect(db_session.get_bind())
    cols = {c["name"] for c in insp.get_columns("news_articles")}
    assert cols >= {
        "id", "aoi_id", "job_id", "after_scene_id", "url", "title", "domain",
        "language", "seendate", "gates_passed", "query", "meta", "created_at",
    }
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("news_articles")}
    assert ("aoi_id", "after_scene_id", "url") in uniques


def test_aois_have_term_arrays(db_session):
    insp = inspect(db_session.get_bind())
    cols = {c["name"] for c in insp.get_columns("aois")}
    assert {"place_terms", "region_terms"} <= cols


def test_evidence_links_article_id_and_check(db_session):
    insp = inspect(db_session.get_bind())
    cols = {c["name"] for c in insp.get_columns("evidence_links")}
    assert "article_id" in cols
    checks = {c["name"] for c in insp.get_check_constraints("evidence_links")}
    assert "ck_evidence_links_article_id" in checks
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_db_schema.py -v`
Expected: FAIL — `NoSuchTableError: news_articles`.

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0004_create_news_articles.py`:

```python
"""news_articles + aoi term arrays + evidence_links.article_id (Phase 5 design §5).

Additive only. Gate 1 is the TOPONYM gate — GDELT exposes no geotag (design §2.2),
so there is deliberately no geometry column here.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "aoi_id",
            sa.BigInteger,
            sa.ForeignKey("aois.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "after_scene_id", sa.BigInteger, sa.ForeignKey("scenes.id"), nullable=False
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("seendate", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "gates_passed",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column(
            "meta", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "aoi_id", "after_scene_id", "url", name="uq_news_articles_aoi_scene_url"
        ),
    )
    op.create_index(
        "ix_news_articles_aoi_scene", "news_articles", ["aoi_id", "after_scene_id"]
    )

    op.add_column("aois", sa.Column("place_terms", postgresql.ARRAY(sa.Text), nullable=True))
    op.add_column("aois", sa.Column("region_terms", postgresql.ARRAY(sa.Text), nullable=True))

    op.add_column(
        "evidence_links",
        sa.Column(
            "article_id",
            sa.BigInteger,
            sa.ForeignKey("news_articles.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_evidence_links_article_id",
        "evidence_links",
        "evidence_type != 'article' OR article_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_evidence_links_article_id", "evidence_links", type_="check")
    op.drop_column("evidence_links", "article_id")
    op.drop_column("aois", "region_terms")
    op.drop_column("aois", "place_terms")
    op.drop_index("ix_news_articles_aoi_scene", table_name="news_articles")
    op.drop_table("news_articles")
```

- [ ] **Step 4: Add the ORM models**

In `backend/src/overwatch/db/models.py`, add `ARRAY` to the `sqlalchemy.dialects.postgresql` import
(`from sqlalchemy.dialects.postgresql import ARRAY, JSONB`), add two columns to `Aoi` (place them after `vertical`):

```python
    place_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    region_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
```

add `article_id` to `EvidenceLink` and extend its `__table_args__` with the new CHECK:

```python
    article_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_articles.id", ondelete="CASCADE")
    )
```

```python
        CheckConstraint(
            "evidence_type != 'article' OR article_id IS NOT NULL",
            name="ck_evidence_links_article_id",
        ),
```

and append the new model at the end of the file:

```python
class NewsArticle(Base):
    """One GDELT article that passed all three gates (Phase 5 design §5).

    Gate 1 is the TOPONYM gate, not a spatial one: GDELT exposes no geotag (design §2.2),
    which is why this table holds no geometry.
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint(
            "aoi_id", "after_scene_id", "url", name="uq_news_articles_aoi_scene_url"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aoi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aois.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    after_scene_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scenes.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    seendate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gates_passed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 5: Migrate and run the tests**

Run:
```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic current
docker compose exec -T api pytest tests/test_db_schema.py -v
```
Expected: `alembic current` → `0004 (head)`; all schema tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0004_create_news_articles.py backend/src/overwatch/db/models.py backend/tests/test_db_schema.py
git commit -m "feat(phase-5): migration 0004 — news_articles, AOI term arrays, article evidence links"
```

---

## Task 2: Fusion presets + AOI terms + settings

**Files:**
- Create: `backend/src/overwatch/fusion/__init__.py`, `backend/src/overwatch/fusion/presets.py`,
  `backend/src/overwatch/fusion/models.py`
- Modify: `backend/src/overwatch/aois.py`, `backend/src/overwatch/db/aois.py`,
  `backend/src/overwatch/config.py`, `backend/pyproject.toml`
- Test: `backend/tests/test_fusion_presets.py`, `backend/tests/test_seed.py`

**Interfaces:**
- Produces:
  - `FusionPreset(vertical, themes: list[str], keywords: list[str], lead_days: int, lag_days: int)`
  - `FUSION_PRESETS: dict[str, FusionPreset]` keyed by `"port" | "forest" | "flood"`
  - `RawArticle(url, title, domain, language, seendate: datetime)`
  - `FusionWindow(start: datetime, end: datetime)` with `FusionWindow.around(after_captured_at, preset)`
  - `GateResult(passed: bool, toponym: list[str], temporal: bool, thematic: list[str], reason: str | None)`
  - `upsert_aoi(..., place_terms: list[str] | None = None, region_terms: list[str] | None = None)`
  - `settings.gdelt_api_url`, `settings.gdelt_max_records`, `settings.gdelt_min_interval_s`,
    `settings.fusion_languages`, `settings.fusion_max_prompt_articles`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_fusion_presets.py`:

```python
from datetime import UTC, datetime

import pytest

from overwatch.aois import SHOWCASE_AOIS
from overwatch.fusion.models import FusionWindow
from overwatch.fusion.presets import FUSION_PRESETS


def test_every_vertical_has_a_fusion_preset():
    assert set(FUSION_PRESETS) == {"port", "forest", "flood"}


@pytest.mark.parametrize("vertical", ["port", "forest", "flood"])
def test_presets_carry_verified_gdelt_themes_and_keywords(vertical):
    preset = FUSION_PRESETS[vertical]
    assert preset.themes, "themes drive GDELT retrieval"
    assert preset.keywords, "keywords are the thematic gate"
    assert preset.lead_days == 30
    assert preset.lag_days == 14


def test_flood_themes_are_the_literal_verified_identifiers():
    # design §2.6 — pulled from the live LOOKUP-GKGTHEMES.TXT, not invented.
    assert "NATURAL_DISASTER_FLOOD" in FUSION_PRESETS["flood"].themes


def test_window_anchors_on_the_after_scene_not_the_pair():
    # design decision 3: a 3-year scene gap must NOT produce a 3-year window.
    after = datetime(2024, 5, 20, tzinfo=UTC)
    window = FusionWindow.around(after, FUSION_PRESETS["flood"])
    assert window.start == datetime(2024, 4, 20, tzinfo=UTC)
    assert window.end == datetime(2024, 6, 3, tzinfo=UTC)
    assert (window.end - window.start).days == 44


def test_showcase_aois_carry_terms():
    assert SHOWCASE_AOIS["vizhinjam"].place_terms == ["Vizhinjam"]
    # design §2.5: titles say "Amazon", never "Novo Progresso" — the corroboration
    # list must contain the regional names that actually appear in titles.
    assert "Amazon" in SHOWCASE_AOIS["novo-progresso"].region_terms
    assert "Rio Grande do Sul" in SHOWCASE_AOIS["porto-alegre"].region_terms
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_fusion_presets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overwatch.fusion'`.

- [ ] **Step 3: Create the fusion models**

Create `backend/src/overwatch/fusion/__init__.py` (empty file).

Create `backend/src/overwatch/fusion/models.py`:

```python
"""Pure contracts for OSINT fusion (Phase 5 design §4). No I/O, no DB."""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from overwatch.fusion.presets import FusionPreset


class RawArticle(BaseModel):
    """One GDELT DOC 2.0 artlist record. These are ALL the fields DOC returns
    (design §2.2) — note the conspicuous absence of any coordinate."""

    url: str
    title: str
    domain: str
    language: str
    seendate: datetime
    socialimage: str = ""
    sourcecountry: str = ""  # publisher registration country — NEVER a geo proxy (design §2.3)


class FusionWindow(BaseModel):
    """Observation window, anchored on the AFTER scene (design decision 3)."""

    start: datetime
    end: datetime

    @classmethod
    def around(cls, after_captured_at: datetime, preset: FusionPreset) -> "FusionWindow":
        return cls(
            start=after_captured_at - timedelta(days=preset.lead_days),
            end=after_captured_at + timedelta(days=preset.lag_days),
        )


class GateResult(BaseModel):
    """Why an article was admitted or rejected — persisted for auditability."""

    passed: bool
    toponym: list[str] = Field(default_factory=list)  # matched place/region terms
    temporal: bool = False
    thematic: list[str] = Field(default_factory=list)  # matched vertical keywords
    reason: str | None = None  # set only when passed is False
```

- [ ] **Step 4: Create the presets**

Create `backend/src/overwatch/fusion/presets.py`:

```python
"""Per-vertical fusion presets (Phase 5 design §4.2).

Theme identifiers are LITERAL and VERIFIED against the live GDELT taxonomy
(LOOKUP-GKGTHEMES.TXT) during the 2026-07-12 spike — not invented. Corpus counts
in comments are from that pull.

`themes` narrow RETRIEVAL (recall control, enforced by GDELT against full text).
`keywords` are the thematic GATE (precision control, enforced by our pure scorer
against the title). Two different jobs — see design §4.1.
"""

from pydantic import BaseModel, Field


class FusionPreset(BaseModel):
    vertical: str
    themes: list[str] = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    lead_days: int = 30  # design §4.2 — window starts before the after-scene
    lag_days: int = 14  # ...and ends after it


FUSION_PRESETS: dict[str, FusionPreset] = {
    "port": FusionPreset(
        vertical="port",
        themes=[
            "MARITIME",  # 55.0M
            "NEW_CONSTRUCTION",  # 6.9M
            "WB_1803_TRANSPORT_INFRASTRUCTURE",  # 73.5M
        ],
        keywords=[
            "port", "seaport", "terminal", "berth", "shipping", "cargo",
            "container", "harbour", "harbor", "vessel", "transshipment",
        ],
    ),
    "forest": FusionPreset(
        vertical="forest",
        themes=[
            "ENV_DEFORESTATION",  # 722k
            "ENV_FORESTRY",  # 3.6M
        ],
        keywords=[
            # "deforest" is a STEM: it must match "deforester" and "deforestation",
            # which is how the Mongabay and Rio Times demo articles pass (design §4.4).
            "deforest", "desmatamento", "logging", "clearing", "cleared",
            "forest", "rainforest", "illegal",
        ],
    ),
    "flood": FusionPreset(
        vertical="flood",
        themes=[
            "NATURAL_DISASTER_FLOOD",  # 6.5M
            "NATURAL_DISASTER_FLOODING",  # 6.2M
            "EVACUATION",  # 12.3M
        ],
        keywords=[
            "flood", "inundat", "evacuat", "deluge", "submerged",
            "rainfall", "water level",
        ],
    ),
}
```

- [ ] **Step 5: Add terms to the showcase AOIs**

In `backend/src/overwatch/aois.py`, add two fields to the AOI dataclass/model
(`place_terms: list[str]` and `region_terms: list[str]`, both defaulting to `[]`), then set them on the three
showcase entries:

```python
    # vizhinjam
    place_terms=["Vizhinjam"],
    region_terms=["Thiruvananthapuram", "Kerala"],

    # novo-progresso
    # design §2.5: ZERO of the four real articles say "Novo Progresso" in the title —
    # they all say "Amazon". The strict term still gates RETRIEVAL against full text.
    place_terms=["Novo Progresso"],
    region_terms=["Amazon", "Amazônia", "Amazonia", "Pará", "Para", "BR-163"],

    # porto-alegre
    # "Porto Alegre" is an ambiguous toponym (there is one in Portugal); the region
    # terms are what the real headlines actually carry.
    place_terms=["Porto Alegre"],
    region_terms=["Rio Grande do Sul", "Guaíba", "Guaiba"],
```

- [ ] **Step 6: Carry the terms through `upsert_aoi`**

In `backend/src/overwatch/db/aois.py`, extend `upsert_aoi`'s signature with
`place_terms: list[str] | None = None, region_terms: list[str] | None = None`, add both to `.values(...)`, and add both
to the `on_conflict_do_update` `set_={...}` dict so re-seeding refreshes them.

Then in `backend/src/overwatch/db/seed.py`, pass `place_terms=aoi.place_terms, region_terms=aoi.region_terms` to the
`upsert_aoi` call.

- [ ] **Step 7: Add the settings**

In `backend/src/overwatch/config.py`, append to `Settings`:

```python
    gdelt_api_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_max_records: int = 250  # DOC 2.0 hard cap
    gdelt_min_interval_s: float = 6.0  # spike: ≥5s documented; 429s below that (design §2.6)
    fusion_languages: list[str] = ["English"]  # v0.1 — filter on the record's own field
    fusion_max_prompt_articles: int = 10  # prompt-size discipline, carried from Phase 4
```

- [ ] **Step 8: Add httpx as a runtime dependency**

In `backend/pyproject.toml`, move `"httpx>=0.27"` from `[project.optional-dependencies].dev` into the main
`dependencies` list (the provider needs it at runtime, not just in tests). Leave it out of `dev` — it is inherited.

Then rebuild: `docker compose up -d --build api worker beat`

- [ ] **Step 9: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_presets.py tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/src/overwatch/fusion/ backend/src/overwatch/aois.py backend/src/overwatch/db/aois.py backend/src/overwatch/db/seed.py backend/src/overwatch/config.py backend/pyproject.toml backend/tests/test_fusion_presets.py
git commit -m "feat(phase-5): fusion presets with verified GDELT themes, AOI toponym terms, settings"
```

---

## Task 3: Text normalization (pure)

**Files:**
- Create: `backend/src/overwatch/fusion/normalize.py`
- Test: `backend/tests/test_fusion_normalize.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str` — casefold, strip diacritics, collapse whitespace
  - `match_terms(text: str, terms: list[str]) -> list[str]` — word-boundary matches, returns the matched terms
  - `match_stems(text: str, stems: list[str]) -> list[str]` — prefix matches at a word boundary

**Why two matchers:** toponyms need **whole-word** matching (`Para` must not fire on `Paraguay`), but thematic keywords
need **stem/prefix** matching (`deforest` must fire on `deforester` and `deforestation` — this is exactly how the two
Novo Progresso demo articles pass, design §4.4).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_fusion_normalize.py`:

```python
from overwatch.fusion.normalize import match_stems, match_terms, normalize


def test_normalize_casefolds_and_strips_diacritics():
    assert normalize("Pará") == "para"
    assert normalize("Amazônia") == "amazonia"
    assert normalize("  Rio  Grande   do Sul ") == "rio grande do sul"


def test_match_terms_is_diacritic_insensitive_both_directions():
    assert match_terms("Deforestation in Pará rises", ["Para"]) == ["Para"]
    assert match_terms("Deforestation in Para rises", ["Pará"]) == ["Pará"]


def test_match_terms_respects_word_boundaries():
    # The bug this prevents: "Para" firing on "Paraguay".
    assert match_terms("Flooding hits Paraguay", ["Para"]) == []
    assert match_terms("Deforestation in Para state", ["Para"]) == ["Para"]


def test_match_terms_handles_multiword_terms():
    assert match_terms(
        "Brazil Rio Grande Do Sul May Have More Record Level Flooding",
        ["Rio Grande do Sul"],
    ) == ["Rio Grande do Sul"]


def test_match_terms_returns_every_match_in_input_order():
    assert match_terms("Novo Progresso, Pará", ["Pará", "Novo Progresso"]) == [
        "Pará",
        "Novo Progresso",
    ]


def test_match_stems_matches_prefixes_at_a_word_boundary():
    # The real demo articles: "deforester" and "deforestation" must both hit "deforest".
    assert match_stems("Amazon largest single deforester", ["deforest"]) == ["deforest"]
    assert match_stems("Amazon deforestation falls 66%", ["deforest"]) == ["deforest"]
    assert match_stems("Record level flooding", ["flood"]) == ["flood"]
    assert match_stems("Evacuations ordered", ["evacuat"]) == ["evacuat"]


def test_match_stems_does_not_match_mid_word():
    # A stem must start a word — "flood" must not fire inside "backflooded"? It should
    # not fire on an unrelated word that merely contains the letters.
    assert match_stems("The reflooding of memories", ["flood"]) == []


def test_match_stems_hyphenated_terms():
    assert match_terms("Trucks on the BR-163 highway", ["BR-163"]) == ["BR-163"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_fusion_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: overwatch.fusion.normalize`.

- [ ] **Step 3: Implement**

Create `backend/src/overwatch/fusion/normalize.py`:

```python
"""Pure text normalization + matching for the fusion gates (Phase 5 design §4.2).

Two matchers, deliberately different:
  - `match_terms`  — WHOLE-WORD. Toponyms. Prevents "Para" firing on "Paraguay".
  - `match_stems`  — PREFIX at a word start. Thematic keywords. Lets "deforest" fire on
    "deforester"/"deforestation", which is how the Novo Progresso demo articles pass.
"""

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold, strip diacritics (Pará -> para), collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE_RE.sub(" ", stripped.casefold()).strip()


def match_terms(text: str, terms: list[str]) -> list[str]:
    """Whole-word, diacritic-insensitive matches. Returns the ORIGINAL terms that hit."""
    haystack = normalize(text)
    hits: list[str] = []
    for term in terms:
        needle = normalize(term)
        if not needle:
            continue
        # \b is unreliable next to non-word chars (e.g. the hyphen in "BR-163"), so
        # bound the match on explicit non-word-or-edge lookarounds instead.
        pattern = rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])"
        if re.search(pattern, haystack):
            hits.append(term)
    return hits


def match_stems(text: str, stems: list[str]) -> list[str]:
    """Prefix matches anchored at a word start. Returns the ORIGINAL stems that hit."""
    haystack = normalize(text)
    hits: list[str] = []
    for stem in stems:
        needle = normalize(stem)
        if not needle:
            continue
        # Anchored at a word start, open-ended at the tail: "deforest" -> "deforester".
        pattern = rf"(?<![0-9a-z]){re.escape(needle)}"
        if re.search(pattern, haystack):
            hits.append(stem)
    return hits
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_normalize.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/fusion/normalize.py backend/tests/test_fusion_normalize.py
git commit -m "feat(phase-5): pure diacritic-folding term/stem matchers for the fusion gates"
```

---

## Task 4: The three-gate scorer (pure — this phase's TDD centrepiece)

**Files:**
- Create: `backend/src/overwatch/fusion/scorer.py`
- Test: `backend/tests/test_fusion_scorer.py`

**Interfaces:**
- Consumes: `RawArticle`, `FusionWindow`, `GateResult` (Task 2); `match_terms`, `match_stems` (Task 3);
  `FusionPreset` (Task 2).
- Produces: `score_article(article, place_terms, region_terms, window, preset, languages) -> GateResult`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_fusion_scorer.py`. **The dry-run cases from design §4.4 are the real corpus — use the actual
titles, not invented ones.**

```python
from datetime import UTC, datetime

import pytest

from overwatch.fusion.models import FusionWindow, RawArticle
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.scorer import score_article

FOREST_WINDOW = FusionWindow(
    start=datetime(2023, 8, 6, tzinfo=UTC), end=datetime(2023, 9, 19, tzinfo=UTC)
)
FOREST_PLACE = ["Novo Progresso"]
FOREST_REGION = ["Amazon", "Amazônia", "Pará", "BR-163"]


def article(title: str, *, seendate: datetime, language: str = "English", domain: str = "x.com"):
    return RawArticle(
        url=f"https://{domain}/a", title=title, domain=domain,
        language=language, seendate=seendate,
    )


def score_forest(art):
    return score_article(
        art,
        place_terms=FOREST_PLACE,
        region_terms=FOREST_REGION,
        window=FOREST_WINDOW,
        preset=FUSION_PRESETS["forest"],
        languages=["English"],
    )


# --- The real demo corpus (design §4.4) -------------------------------------------

def test_mongabay_deforester_article_passes():
    result = score_forest(
        article(
            "Brazilian authorities launch probe into Amazon largest single deforester",
            seendate=datetime(2023, 8, 11, 1, 30, tzinfo=UTC),
        )
    )
    assert result.passed
    assert result.toponym == ["Amazon"]  # NOT "Novo Progresso" — the title never says it
    assert result.thematic == ["deforest"]  # the stem fires on "deforester"


def test_rio_times_hectares_cleared_article_passes():
    result = score_forest(
        article(
            "Major Amazon deforester arrested in Brazil : 6 , 500 hectares cleared",
            seendate=datetime(2023, 8, 4, 14, 45, tzinfo=UTC),
        )
    )
    assert result.passed


def test_carrefour_cattle_article_is_rejected_no_thematic_keyword():
    # Real article, correctly rejected: "devastator"/"cattle" are not in the allowlist.
    # Conservative by construction — better to cite nothing than cite garbage.
    result = score_forest(
        article(
            "How the Amazon greatest devastator sold cattle to a Carrefour supplier",
            seendate=datetime(2023, 8, 29, tzinfo=UTC),
        )
    )
    assert not result.passed
    assert result.reason == "thematic"


# --- Adversarial negatives (design §4.4) ------------------------------------------

def test_amazon_prime_day_is_rejected_this_is_why_the_AND_matters():
    result = score_forest(
        article("Amazon Prime Day deals announced", seendate=datetime(2023, 8, 15, tzinfo=UTC))
    )
    assert not result.passed
    assert result.reason == "thematic"  # toponym passed on "Amazon"!


def test_off_place_article_is_rejected():
    result = score_forest(
        article("Severe deforestation hits Indonesia", seendate=datetime(2023, 8, 15, tzinfo=UTC))
    )
    assert not result.passed
    assert result.reason == "toponym"


def test_out_of_window_article_is_rejected():
    result = score_forest(
        article(
            "Amazon deforestation falls 66%",
            seendate=datetime(2024, 3, 1, tzinfo=UTC),  # 6 months late
        )
    )
    assert not result.passed
    assert result.reason == "temporal"


# --- Boundaries -------------------------------------------------------------------

@pytest.mark.parametrize(
    "seendate,expected",
    [
        (datetime(2023, 8, 6, tzinfo=UTC), True),    # exactly on window start — inclusive
        (datetime(2023, 9, 19, tzinfo=UTC), True),   # exactly on window end — inclusive
        (datetime(2023, 8, 5, 23, 59, tzinfo=UTC), False),
        (datetime(2023, 9, 19, 0, 1, tzinfo=UTC), False),
    ],
)
def test_temporal_gate_boundaries_are_inclusive(seendate, expected):
    result = score_forest(article("Amazon deforestation report", seendate=seendate))
    assert result.passed is expected


def test_non_english_is_rejected_by_the_language_precondition():
    result = score_forest(
        article(
            "Desmatamento na Amazônia cai",
            seendate=datetime(2023, 8, 15, tzinfo=UTC),
            language="Portuguese",
        )
    )
    assert not result.passed
    assert result.reason == "language"


def test_gate_result_records_why_it_passed_for_audit():
    result = score_forest(
        article("Amazon deforestation falls 66% in July", seendate=datetime(2023, 8, 5, tzinfo=UTC))
    )
    assert result.passed
    assert result.toponym and result.thematic and result.temporal
    assert result.reason is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_fusion_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError: overwatch.fusion.scorer`.

- [ ] **Step 3: Implement the scorer**

Create `backend/src/overwatch/fusion/scorer.py`:

```python
"""The three-gate AND relevance scorer (Phase 5 design §4.2). Pure — no I/O, no DB.

Gate 1 is the TOPONYM gate, NOT a spatial one. GDELT exposes no geotag (design §2.2) and
the GKG geofence was measured and rejects 100% of our true positives (design §2.4).

Two-layer conjunction (design §4.1): GDELT's query already enforced the STRICT place term
against the article's full text. This scorer corroborates against the only thing the DOC
record exposes — the title — using a GENEROUS term list that includes regional names,
because titles routinely omit the specific place (design §2.5).
"""

from overwatch.fusion.models import FusionWindow, GateResult, RawArticle
from overwatch.fusion.normalize import match_stems, match_terms
from overwatch.fusion.presets import FusionPreset


def score_article(
    article: RawArticle,
    *,
    place_terms: list[str],
    region_terms: list[str],
    window: FusionWindow,
    preset: FusionPreset,
    languages: list[str],
) -> GateResult:
    """All gates must pass (AND). The first failure short-circuits and is recorded."""
    # Precondition: language. We filter on the record's OWN field rather than GDELT's
    # unverified `sourcelang:` operator (design decision 7).
    if article.language not in languages:
        return GateResult(passed=False, reason="language")

    if not article.url.startswith(("http://", "https://")):
        return GateResult(passed=False, reason="url")

    # Gate 1 — TOPONYM. Whole-word match against place ∪ region terms.
    toponym = match_terms(article.title, [*place_terms, *region_terms])
    if not toponym:
        return GateResult(passed=False, reason="toponym")

    # Gate 2 — TEMPORAL. Inclusive on both bounds, anchored on the AFTER scene.
    temporal = window.start <= article.seendate <= window.end
    if not temporal:
        return GateResult(passed=False, toponym=toponym, reason="temporal")

    # Gate 3 — THEMATIC. Stem match, so "deforest" fires on "deforester".
    thematic = match_stems(article.title, preset.keywords)
    if not thematic:
        return GateResult(
            passed=False, toponym=toponym, temporal=True, reason="thematic"
        )

    return GateResult(passed=True, toponym=toponym, temporal=True, thematic=thematic)
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_scorer.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/fusion/scorer.py backend/tests/test_fusion_scorer.py
git commit -m "feat(phase-5): three-gate AND relevance scorer, TDD against the real spiked corpus"
```

---

## Task 5: Dedup (pure)

**Files:**
- Modify: `backend/src/overwatch/fusion/scorer.py`
- Test: `backend/tests/test_fusion_dedup.py`

**Interfaces:**
- Produces: `dedupe(articles: list[RawArticle], domain_rank: list[str]) -> list[tuple[RawArticle, list[str]]]` —
  returns `(survivor, suppressed_urls)` pairs.

**Why:** two of the six real Porto Alegre results are the same Reuters wire carried by `usnews.com` and `yahoo.com`
(design §2.5 / §4.3). Without dedup, syndication inflates the citation count and one story masquerades as corroboration.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_fusion_dedup.py`:

```python
from datetime import UTC, datetime

from overwatch.fusion.models import RawArticle
from overwatch.fusion.scorer import dedupe

RANK = ["reuters.com", "usnews.com", "yahoo.com"]


def art(title, domain, day):
    return RawArticle(
        url=f"https://{domain}/{day}", title=title, domain=domain,
        language="English", seendate=datetime(2024, 5, day, tzinfo=UTC),
    )


def test_syndicated_wire_story_collapses_to_one_survivor():
    # The real case: usnews + yahoo carrying the same Reuters piece (design §2.5).
    a = art("Brazil Rio Grande Do Sul May Have More Record Level Flooding", "usnews.com", 12)
    b = art("Brazil Rio Grande do Sul may have more record level flooding", "yahoo.com", 12)
    survivors = dedupe([a, b], domain_rank=RANK)
    assert len(survivors) == 1
    survivor, suppressed = survivors[0]
    assert survivor.domain == "usnews.com"  # ranks above yahoo
    assert suppressed == ["https://yahoo.com/12"]


def test_dedup_is_case_and_punctuation_insensitive():
    a = art("Major Amazon deforester arrested : 6 , 500 hectares cleared", "a.com", 4)
    b = art("Major Amazon deforester arrested: 6,500 hectares cleared", "b.com", 4)
    assert len(dedupe([a, b], domain_rank=RANK)) == 1


def test_distinct_stories_are_both_kept():
    a = art("Amazon deforestation falls 66% in July", "a.com", 5)
    b = art("Brazilian authorities launch probe into Amazon deforester", "b.com", 11)
    assert len(dedupe([a, b], domain_rank=RANK)) == 2


def test_unranked_domains_tiebreak_on_earliest_seendate():
    a = art("Same headline", "unknown-a.com", 20)
    b = art("Same headline", "unknown-b.com", 12)
    survivor, _ = dedupe([a, b], domain_rank=RANK)[0]
    assert survivor.domain == "unknown-b.com"  # earlier seendate wins
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_fusion_dedup.py -v`
Expected: FAIL — `ImportError: cannot import name 'dedupe'`.

- [ ] **Step 3: Implement**

Append to `backend/src/overwatch/fusion/scorer.py`:

```python
import re

_PUNCT_RE = re.compile(r"[^0-9a-z ]+")


def _title_key(title: str) -> str:
    """Collapse a title to a comparison key: normalized, punctuation-free, single-spaced.

    "Brazil Rio Grande Do Sul May Have More Record Level Flooding" and its lowercase
    yahoo syndication collapse to the same key.
    """
    return _WHITESPACE_RE.sub(" ", _PUNCT_RE.sub(" ", normalize(title))).strip()


def dedupe(
    articles: list[RawArticle], *, domain_rank: list[str]
) -> list[tuple[RawArticle, list[str]]]:
    """Collapse syndicated copies. Returns (survivor, suppressed_urls) per story.

    Winner: highest-ranked domain; ties (and unranked domains) break on earliest seendate.
    Suppressed URLs are returned rather than discarded so the dedup is visible in the
    persisted row's meta, not silent (design §4.3).
    """
    groups: dict[str, list[RawArticle]] = {}
    for article in articles:
        groups.setdefault(_title_key(article.title), []).append(article)

    def rank(article: RawArticle) -> tuple[int, float]:
        try:
            domain_score = domain_rank.index(article.domain)
        except ValueError:
            domain_score = len(domain_rank)  # unranked sorts last
        return (domain_score, article.seendate.timestamp())

    out: list[tuple[RawArticle, list[str]]] = []
    for group in groups.values():
        winner, *losers = sorted(group, key=rank)
        out.append((winner, [a.url for a in losers]))
    return out
```

Add `normalize` and `_WHITESPACE_RE` to the module's imports:
`from overwatch.fusion.normalize import _WHITESPACE_RE, match_stems, match_terms, normalize`

> If ruff objects to importing the private `_WHITESPACE_RE`, promote it in `normalize.py` to a public
> `WHITESPACE_RE` and update both modules. Do not duplicate the regex.

- [ ] **Step 4: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_dedup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/fusion/scorer.py backend/src/overwatch/fusion/normalize.py backend/tests/test_fusion_dedup.py
git commit -m "feat(phase-5): pure syndication dedup — one wire story cites once, not twice"
```

---

## Task 6: NewsProvider — protocol, GDELT impl, fake

**Files:**
- Create: `backend/src/overwatch/fusion/provider.py`, `backend/tests/fixtures/gdelt/vizhinjam_2024.json`,
  `backend/tests/fixtures/gdelt/rate_limited.txt`, `backend/tests/fixtures/gdelt/keyword_error.txt`
- Test: `backend/tests/test_fusion_provider.py`

**Interfaces:**
- Consumes: `RawArticle` (Task 2), `settings` (Task 2).
- Produces:
  - `NewsProvider` protocol with `search(query: str, start: datetime, end: datetime) -> list[RawArticle]`
  - `GdeltDocProvider` (real), `FakeNewsProvider(articles: list[RawArticle])` (CI)
  - `build_query(place_term: str, preset: FusionPreset) -> str`
  - `TransientFusionError` — raised on 429/5xx/network, so Celery autoretries.

- [ ] **Step 1: Capture the fixtures**

`backend/tests/fixtures/gdelt/vizhinjam_2024.json` — paste the **verbatim** spike response:

```json
{"articles": [
 {"url": "https://www.thehindu.com/news/national/kerala/customs-grants-approval-to-vizhinjam-international-seaport/article68293772.ece",
  "url_mobile": "", "title": "Customs grants approval to Vizhinjam International Seaport",
  "seendate": "20240615T170000Z", "socialimage": "https://www.thehindu.com/theme/images/og-image.png",
  "domain": "thehindu.com", "language": "English", "sourcecountry": "India"},
 {"url": "https://www.mathrubhumi.com/news/kerala/as-trolling-restrictions-removed-vizhinjam-going-for-fresh-start-1.9700465",
  "url_mobile": "", "title": "ട്രോളിങ് നിയന്ത്രണം നീങ്ങി ; വിഴിഞ്ഞം തീരത്ത് ആവേശം , vizhinjam , fish",
  "seendate": "20240706T093000Z", "socialimage": "",
  "domain": "mathrubhumi.com", "language": "Malayalam", "sourcecountry": "India"},
 {"url": "https://www.thehindu.com/news/national/kerala/upcoming-vadhavan-port-may-cast-a-shadow-on-vizhinjam-ports-prospects/article68312603.ece",
  "url_mobile": "", "title": "Upcoming Vadhavan port may cast a shadow on Vizhinjam port prospects",
  "seendate": "20240620T154500Z", "socialimage": "",
  "domain": "thehindu.com", "language": "English", "sourcecountry": "India"},
 {"url": "https://www.thehindubusinessline.com/economy/logistics/vizhinjam-beckons-shipping-lines-as-delay-hit-cargo-handling-at-colombo-port/article68405686.ece",
  "url_mobile": "", "title": "Vizhinjam beckons shipping lines as delay hit cargo handling at Colombo Port",
  "seendate": "20240715T103000Z", "socialimage": "",
  "domain": "thehindubusinessline.com", "language": "English", "sourcecountry": "India"}
]}
```

`backend/tests/fixtures/gdelt/rate_limited.txt` — the **actual 429 body** (plaintext, not JSON):

```
Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com for larger queries. All high-traffic users should switch to our ngrams dataset: https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/.
```

`backend/tests/fixtures/gdelt/keyword_error.txt` — a **200** whose body is a plaintext error:

```
One or more of your keywords were too short, too long or too common: (locationcc:br)
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_fusion_provider.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.provider import (
    FakeNewsProvider,
    GdeltDocProvider,
    TransientFusionError,
    build_query,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"
START = datetime(2024, 6, 15, tzinfo=UTC)
END = datetime(2024, 8, 15, tzinfo=UTC)


def test_build_query_is_conjunctive_place_and_themes():
    q = build_query("Vizhinjam", FUSION_PRESETS["port"])
    assert '"Vizhinjam"' in q
    assert "theme:MARITIME" in q
    assert " OR " in q  # themes are OR-ed inside the AND-ed group
    assert q.startswith('"Vizhinjam" (')


def _provider_with(handler) -> GdeltDocProvider:
    return GdeltDocProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parses_a_real_artlist_response():
    body = (FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    articles = provider.search("q", START, END)
    assert len(articles) == 4
    first = articles[0]
    assert first.domain == "thehindu.com"
    assert first.language == "English"
    # seendate must parse from GDELT's compact form, not ISO.
    assert first.seendate == datetime(2024, 6, 15, 17, 0, tzinfo=UTC)


def test_429_plaintext_body_raises_transient_and_does_not_json_decode():
    body = (FIXTURES / "rate_limited.txt").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(429, text=body))
    with pytest.raises(TransientFusionError, match="rate"):
        provider.search("q", START, END)


def test_200_with_plaintext_keyword_error_returns_empty_not_a_crash():
    body = (FIXTURES / "keyword_error.txt").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    assert provider.search("q", START, END) == []


def test_empty_200_body_returns_empty():
    provider = _provider_with(lambda req: httpx.Response(200, text=""))
    assert provider.search("q", START, END) == []


def test_5xx_raises_transient_so_celery_retries():
    provider = _provider_with(lambda req: httpx.Response(503, text="upstream down"))
    with pytest.raises(TransientFusionError):
        provider.search("q", START, END)


def test_network_error_raises_transient():
    def boom(request):
        raise httpx.ConnectError("dns")

    provider = _provider_with(boom)
    with pytest.raises(TransientFusionError):
        provider.search("q", START, END)


def test_fake_provider_replays_fixtures_offline():
    body = json.loads((FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8"))
    provider = FakeNewsProvider.from_artlist(body)
    assert len(provider.search("anything", START, END)) == 4
```

- [ ] **Step 3: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_fusion_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: overwatch.fusion.provider`.

- [ ] **Step 4: Implement**

Create `backend/src/overwatch/fusion/provider.py`:

```python
"""GDELT DOC 2.0 retrieval (Phase 5 design §6). The ONLY I/O in the fusion path.

Hard-won facts from the 2026-07-12 spike — do not "simplify" these away:
  * GEO 2.0 is a 404. DOC 2.0 is the only surface (design §2.1).
  * A 429 body is PLAINTEXT, not JSON. Never json.loads() blind (design §2.6).
  * A 200 can ALSO carry a plaintext error ("keywords were too short/long/common").
  * ≥5 s between requests is the documented ask; we default to 6 s.
"""

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from overwatch.config import settings
from overwatch.fusion.models import RawArticle
from overwatch.fusion.presets import FusionPreset

logger = logging.getLogger(__name__)

_GDELT_TS = "%Y%m%d%H%M%S"


class TransientFusionError(Exception):
    """Rate limit / 5xx / network. Safe to retry with backoff."""


class NewsProvider(Protocol):
    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]: ...


def build_query(place_term: str, preset: FusionPreset) -> str:
    """Conjunctive: the STRICT place term AND any of the vertical's themes.

    GDELT matches the quoted term against the article's FULL TEXT — which is strictly
    more than the title our scorer can see (design §4.1). This is layer one of the
    two-layer conjunction; the pure scorer is layer two.
    """
    themes = " OR ".join(f"theme:{t}" for t in preset.themes)
    return f'"{place_term}" ({themes})'


def _parse_seendate(raw: str) -> datetime:
    """GDELT's compact stamp: '20240615T170000Z' — not ISO-8601."""
    return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _to_articles(payload: dict[str, Any]) -> list[RawArticle]:
    out: list[RawArticle] = []
    for row in payload.get("articles", []):
        try:
            out.append(
                RawArticle(
                    url=row["url"],
                    title=row["title"].strip(),
                    domain=row["domain"],
                    language=row["language"],
                    seendate=_parse_seendate(row["seendate"]),
                    socialimage=row.get("socialimage", ""),
                    sourcecountry=row.get("sourcecountry", ""),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("skipping malformed GDELT row: %s", exc)
    return out


class GdeltDocProvider:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            wait = settings.gdelt_min_interval_s - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]:
        self._throttle()
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": settings.gdelt_max_records,
            "startdatetime": start.astimezone(UTC).strftime(_GDELT_TS),
            "enddatetime": end.astimezone(UTC).strftime(_GDELT_TS),
        }
        try:
            response = self._client.get(settings.gdelt_api_url, params=params)
        except httpx.HTTPError as exc:
            raise TransientFusionError(f"GDELT request failed: {exc}") from exc

        if response.status_code == 429:
            # The body here is PLAINTEXT. Do not parse it as JSON.
            raise TransientFusionError(f"GDELT rate limited: {response.text[:120]!r}")
        if response.status_code >= 500:
            raise TransientFusionError(f"GDELT {response.status_code}")
        if response.status_code != 200:
            logger.warning("GDELT %s: %s", response.status_code, response.text[:200])
            return []

        body = response.text.strip()
        if not body or not body.startswith("{"):
            # A 200 with a plaintext error body ("keywords were too short, too long or
            # too common") is a real GDELT response, not an exception. No results.
            if body:
                logger.info("GDELT returned a plaintext notice: %s", body[:200])
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning("GDELT returned undecodable JSON: %s", body[:200])
            return []
        return _to_articles(payload)


class FakeNewsProvider:
    """Replays recorded fixtures. CI never touches the network."""

    def __init__(self, articles: list[RawArticle]) -> None:
        self._articles = articles

    @classmethod
    def from_artlist(cls, payload: dict[str, Any]) -> "FakeNewsProvider":
        return cls(_to_articles(payload))

    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]:
        return list(self._articles)
```

- [ ] **Step 5: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_provider.py -v`
Expected: all PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/fusion/provider.py backend/tests/fixtures/gdelt/ backend/tests/test_fusion_provider.py
git commit -m "feat(phase-5): GDELT DOC provider — plaintext 429/200 handling, throttle, offline fake"
```

---

## Task 7: Article persistence (replace-set + stale flip)

**Files:**
- Create: `backend/src/overwatch/db/news.py`
- Test: `backend/tests/test_news_db.py`

**Interfaces:**
- Consumes: `NewsArticle` (Task 1), `RawArticle`/`GateResult` (Task 2), `mark_stale_briefs` (existing, `db/briefs.py`).
- Produces:
  - `replace_articles(session, *, aoi_id, job_id, before_scene_id, after_scene_id, admitted) -> int`
    where `admitted: list[tuple[RawArticle, GateResult, list[str], str]]` is `(article, gates, suppressed_urls, query)`
  - `articles_for_pair(session, *, aoi_id, after_scene_id) -> list[NewsArticle]`

**Why it takes `before_scene_id` when the table has none:** the **stale flip** is keyed on the full
`(aoi, before, after)` brief pair — a brief is scoped to a pair, so re-fusing must demote briefs over that exact pair,
mirroring `replace_detections` (design §5).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_news_db.py`:

```python
from datetime import UTC, datetime

from overwatch.db.models import Brief, NewsArticle
from overwatch.db.news import articles_for_pair, replace_articles
from overwatch.fusion.models import GateResult, RawArticle


def _admitted(url: str, title: str = "Amazon deforestation report"):
    art = RawArticle(
        url=url, title=title, domain="mongabay.com", language="English",
        seendate=datetime(2023, 8, 11, tzinfo=UTC),
    )
    gates = GateResult(passed=True, toponym=["Amazon"], temporal=True, thematic=["deforest"])
    return (art, gates, [], '"Novo Progresso" (theme:ENV_DEFORESTATION)')


def test_replace_articles_persists_and_records_gates(db_session, seeded_pair):
    aoi_id, job_id, before_id, after_id = seeded_pair
    n = replace_articles(
        db_session, aoi_id=aoi_id, job_id=job_id, before_scene_id=before_id,
        after_scene_id=after_id, admitted=[_admitted("https://a.com/1")],
    )
    assert n == 1
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert rows[0].gates_passed["toponym"] == ["Amazon"]
    assert rows[0].query.startswith('"Novo Progresso"')


def test_rerun_is_idempotent_zero_duplicates(db_session, seeded_pair):
    aoi_id, job_id, before_id, after_id = seeded_pair
    args = dict(
        aoi_id=aoi_id, job_id=job_id, before_scene_id=before_id, after_scene_id=after_id,
        admitted=[_admitted("https://a.com/1")],
    )
    replace_articles(db_session, **args)
    replace_articles(db_session, **args)
    assert len(articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)) == 1


def test_suppressed_duplicates_are_visible_in_meta(db_session, seeded_pair):
    aoi_id, job_id, before_id, after_id = seeded_pair
    art, gates, _, query = _admitted("https://usnews.com/x")
    replace_articles(
        db_session, aoi_id=aoi_id, job_id=job_id, before_scene_id=before_id,
        after_scene_id=after_id, admitted=[(art, gates, ["https://yahoo.com/x"], query)],
    )
    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    assert rows[0].meta["duplicates"] == ["https://yahoo.com/x"]


def test_refusing_flips_validated_briefs_on_that_pair_to_stale(db_session, seeded_pair):
    aoi_id, job_id, before_id, after_id = seeded_pair
    brief = Brief(
        aoi_id=aoi_id, before_scene_id=before_id, after_scene_id=after_id,
        status="validated", attempts=1, usage={},
    )
    db_session.add(brief)
    db_session.flush()
    replace_articles(
        db_session, aoi_id=aoi_id, job_id=job_id, before_scene_id=before_id,
        after_scene_id=after_id, admitted=[_admitted("https://a.com/1")],
    )
    db_session.refresh(brief)
    assert brief.status == "stale"
```

> `seeded_pair` is a new fixture: add it to `backend/tests/conftest.py` returning
> `(aoi_id, job_id, before_scene_id, after_scene_id)` for a seeded AOI + succeeded job + two scenes. Follow the
> existing pattern in `test_detections_db.py` / `test_briefs_db.py` — reuse their setup helpers rather than
> reinventing them.

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_news_db.py -v`
Expected: FAIL — `ModuleNotFoundError: overwatch.db.news`.

- [ ] **Step 3: Implement**

Create `backend/src/overwatch/db/news.py`:

```python
"""News-article persistence — replace-set on (aoi, after_scene) (Phase 5 design §5).

Mirrors `replace_detections`: the scorer is deterministic, so the pair is the natural
key. Re-fusing rewrites identical rows — zero duplicates — and demotes any validated
brief over that pair to `stale` first, so a brief can never keep a dangling article_id.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from overwatch.db.briefs import mark_stale_briefs
from overwatch.db.models import NewsArticle
from overwatch.fusion.models import GateResult, RawArticle

Admitted = tuple[RawArticle, GateResult, list[str], str]


def replace_articles(
    session: Session,
    *,
    aoi_id: int,
    job_id: str | uuid.UUID,
    before_scene_id: int,
    after_scene_id: int,
    admitted: list[Admitted],
) -> int:
    """Replace this pair's article set. `admitted` is (article, gates, suppressed, query)."""
    # Demote validated briefs over this exact pair BEFORE deleting the articles they
    # cite — same transaction, same discipline as replace_detections.
    mark_stale_briefs(
        session, aoi_id=aoi_id, before_scene_id=before_scene_id, after_scene_id=after_scene_id
    )
    session.execute(
        delete(NewsArticle).where(
            NewsArticle.aoi_id == aoi_id,
            NewsArticle.after_scene_id == after_scene_id,
        )
    )
    for article, gates, suppressed, query in admitted:
        session.add(
            NewsArticle(
                aoi_id=aoi_id,
                job_id=uuid.UUID(str(job_id)),
                after_scene_id=after_scene_id,
                url=article.url,
                title=article.title,
                domain=article.domain,
                language=article.language,
                seendate=article.seendate,
                gates_passed=gates.model_dump(mode="json", exclude={"passed", "reason"}),
                query=query,
                meta={
                    "socialimage": article.socialimage,
                    "sourcecountry": article.sourcecountry,
                    "duplicates": suppressed,
                },
            )
        )
    session.flush()
    return len(admitted)


def articles_for_pair(
    session: Session, *, aoi_id: int, after_scene_id: int
) -> list[NewsArticle]:
    return list(
        session.scalars(
            select(NewsArticle)
            .where(
                NewsArticle.aoi_id == aoi_id,
                NewsArticle.after_scene_id == after_scene_id,
            )
            .order_by(NewsArticle.seendate, NewsArticle.id)
        )
    )
```

- [ ] **Step 4: Run the tests**

Run: `docker compose exec -T api pytest tests/test_news_db.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/db/news.py backend/tests/test_news_db.py backend/tests/conftest.py
git commit -m "feat(phase-5): article replace-set persistence with stale-brief flip"
```

---

## Task 8: Validator Gate 4 — the observed/reported wall

**Files:**
- Modify: `backend/src/overwatch/briefs/models.py`, `backend/src/overwatch/briefs/validator.py`
- Test: `backend/tests/test_brief_validator.py`

**Interfaces:**
- Consumes: existing `BriefDraft`, `BriefRequest`, `Violation`, `_has_quantity` (all in place from Phase 4).
- Produces:
  - `ArticleRow(id: int, title: str, domain: str, seendate: date)` in `briefs/models.py`
  - `BriefRequest.articles: list[ArticleRow] = []`
  - `ClaimDraft.article_evidence: list[int] = []` — article ids, kept **separate** from `evidence` (detection ids) so
    the LLM structurally cannot conflate the two.
  - New violation codes: `unsupported_claim_type` (existing, now narrower), `unlinked_reported_claim`,
    `observational_framing_on_reported_claim`, `quantified_reported_claim`, `article_evidence_on_observed_claim`,
    `unknown_article_id`, `mixed_claim_missing_side`.

**This is the phase's trust boundary. It must be negative-tested.**

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brief_validator.py`:

```python
from datetime import date

from overwatch.briefs.models import ArticleRow, BriefDraft, BriefRequest, ClaimDraft, DetectionRow
from overwatch.briefs.validator import validate_brief


def _request_with_articles():
    return BriefRequest(
        aoi_name="Novo Progresso", aoi_slug="novo-progresso", vertical="forest",
        before_scene_id=1, after_scene_id=2,
        before_date=date(2023, 6, 1), after_date=date(2023, 9, 5),
        detections=[
            DetectionRow(id=10, change_type="vegetation_loss", area_m2=50_000.0,
                         magnitude=0.4, confidence=0.8)
        ],
        articles=[
            ArticleRow(id=99, title="Amazon deforester probe", domain="mongabay.com",
                       seendate=date(2023, 8, 11))
        ],
    )


def _codes(draft):
    return {v.code for v in validate_brief(draft, _request_with_articles())}


def test_reported_claim_with_reported_framing_is_valid():
    draft = BriefDraft(
        headline="h",
        claims=[
            ClaimDraft(
                text="Regional news reports that authorities opened a deforestation probe.",
                claim_type="reported", evidence=[], article_evidence=[99],
            )
        ],
    )
    assert validate_brief(draft, _request_with_articles()) == []


def test_article_only_claim_with_OBSERVATIONAL_framing_is_rejected():
    # THE headline negative test: journalism must never masquerade as sensing.
    draft = BriefDraft(
        headline="h",
        claims=[
            ClaimDraft(
                text="Imagery confirms that authorities opened a deforestation probe.",
                claim_type="reported", evidence=[], article_evidence=[99],
            )
        ],
    )
    assert "observational_framing_on_reported_claim" in _codes(draft)


def test_article_only_claim_carrying_a_QUANTITY_is_rejected():
    # Articles are not sensing. "6,500 hectares" in a reported claim is a violation
    # even though a real article says exactly that.
    draft = BriefDraft(
        headline="h",
        claims=[
            ClaimDraft(
                text="Regional news reports 6,500 hectares were cleared.",
                claim_type="reported", evidence=[], article_evidence=[99],
            )
        ],
    )
    assert "quantified_reported_claim" in _codes(draft)


def test_reported_claim_with_no_article_link_is_rejected():
    draft = BriefDraft(
        headline="h",
        claims=[ClaimDraft(text="Regional news reports a probe.", claim_type="reported")],
    )
    assert "unlinked_reported_claim" in _codes(draft)


def test_reported_claim_citing_an_unknown_article_id_is_rejected():
    draft = BriefDraft(
        headline="h",
        claims=[
            ClaimDraft(text="Regional news reports a probe.", claim_type="reported",
                       article_evidence=[12345])
        ],
    )
    assert "unknown_article_id" in _codes(draft)


def test_observed_claim_may_not_carry_article_evidence():
    draft = BriefDraft(
        headline="h",
        claims=[
            ClaimDraft(text="Clearing of 50,000 m² is visible.", claim_type="observed",
                       evidence=[10], article_evidence=[99])
        ],
    )
    assert "article_evidence_on_observed_claim" in _codes(draft)


def test_mixed_claim_needs_both_sides():
    only_detection = BriefDraft(
        headline="h",
        claims=[ClaimDraft(text="Clearing is visible and reported.", claim_type="mixed",
                           evidence=[10])],
    )
    assert "mixed_claim_missing_side" in _codes(only_detection)

    both = BriefDraft(
        headline="h",
        claims=[ClaimDraft(text="Clearing is visible and locally reported.",
                           claim_type="mixed", evidence=[10], article_evidence=[99])],
    )
    assert validate_brief(both, _request_with_articles()) == []


def test_phase_4_gates_still_hold():
    # Regression: the Phase-4 behaviour must not change.
    draft = BriefDraft(
        headline="h",
        claims=[ClaimDraft(text="Clearing is visible.", claim_type="observed", evidence=[])],
    )
    assert "unlinked_claim" in _codes(draft)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_brief_validator.py -v`
Expected: FAIL — `ArticleRow` does not exist; `BriefRequest` has no `articles`.

- [ ] **Step 3: Extend the models**

In `backend/src/overwatch/briefs/models.py`:

```python
class ArticleRow(BaseModel):  # slim view for prompt + validator
    id: int
    title: str
    domain: str
    seendate: date
```

Add to `ClaimDraft` (keep `evidence` exactly as-is — additive only):

```python
    article_evidence: list[int] = []  # news_article ids — kept SEPARATE from `evidence`
```

Add to `BriefRequest`:

```python
    articles: list[ArticleRow] = []
```

- [ ] **Step 4: Implement Gate 4**

In `backend/src/overwatch/briefs/validator.py`:

Replace the `_SUPPORTED_CLAIM_TYPES` constant and its comment:

```python
# Phase 5 lifts Phase 4's restriction: `reported` and `mixed` are now supported, gated
# by Gate 4 (the observed/reported wall). All four claim types are legal.
_SUPPORTED_CLAIM_TYPES = frozenset({"observed", "context", "reported", "mixed"})

# Gate 4 (Phase 5 design §6) — a claim backed ONLY by articles is REPORTED SPEECH.
# It must be framed as such, and it may carry no quantities: journalism is not sensing.
_REPORTED_FRAMING_RE = re.compile(
    r"\b(reports?|reported|reportedly|according to|regional news|local media|"
    r"press reports?|news outlets?|coverage indicates)\b",
    re.IGNORECASE,
)
_OBSERVATIONAL_FRAMING_RE = re.compile(
    r"\b(imagery (?:shows|confirms|reveals)|satellite (?:shows|confirms|reveals)|"
    r"we observe[d]?|detected|is visible|analysis shows|the data shows)\b",
    re.IGNORECASE,
)
```

Then inside `validate_brief`'s per-claim loop, add `known_article_ids` near `known_ids`:

```python
    known_article_ids = {a.id for a in request.articles}
```

and insert these branches **after** the `context` branch and **before** the existing `observed` block:

```python
        if claim.claim_type in ("reported", "mixed"):
            unknown_articles = [
                aid for aid in claim.article_evidence if aid not in known_article_ids
            ]
            for aid in unknown_articles:
                violations.append(
                    Violation(
                        code="unknown_article_id",
                        claim_seq=seq,
                        message=f"Claim cites article id {aid}, which is not a known article.",
                        detail={"article_id": aid},
                    )
                )

        if claim.claim_type == "mixed":
            if not claim.evidence or not claim.article_evidence:
                violations.append(
                    Violation(
                        code="mixed_claim_missing_side",
                        claim_seq=seq,
                        message=(
                            "A 'mixed' claim must cite at least one detection AND at least "
                            "one article."
                        ),
                    )
                )
            continue

        if claim.claim_type == "reported":
            if not claim.article_evidence:
                violations.append(
                    Violation(
                        code="unlinked_reported_claim",
                        claim_seq=seq,
                        message="Reported claim cites no article evidence.",
                    )
                )
            if _OBSERVATIONAL_FRAMING_RE.search(text) or not _REPORTED_FRAMING_RE.search(text):
                violations.append(
                    Violation(
                        code="observational_framing_on_reported_claim",
                        claim_seq=seq,
                        message=(
                            "A claim backed only by news articles must use reported-speech "
                            "framing (e.g. 'regional news reports…'), never observational "
                            "framing. Journalism is not sensing."
                        ),
                    )
                )
            if _has_quantity(text):
                violations.append(
                    Violation(
                        code="quantified_reported_claim",
                        claim_seq=seq,
                        message=(
                            "A claim backed only by news articles may not carry a quantity. "
                            "Only detections carry measured figures."
                        ),
                    )
                )
            continue
```

Finally, at the top of the existing `observed` block, reject article links on an observed claim:

```python
        # claim.claim_type == "observed"
        if claim.article_evidence:
            violations.append(
                Violation(
                    code="article_evidence_on_observed_claim",
                    claim_seq=seq,
                    message=(
                        "An 'observed' claim may not cite article evidence — use 'mixed'."
                    ),
                )
            )
```

Also update the module docstring: it currently says "Three gates"; make it four and describe the wall.

- [ ] **Step 5: Run the tests**

Run: `docker compose exec -T api pytest tests/test_brief_validator.py -v`
Expected: all PASS, **including the pre-existing Phase-4 tests** (regression guard).

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/briefs/models.py backend/src/overwatch/briefs/validator.py backend/tests/test_brief_validator.py
git commit -m "feat(phase-5): validator gate 4 — the observed/reported wall, negative-tested"
```

---

## Task 9: Prompt + persistence carry articles

**Files:**
- Modify: `backend/src/overwatch/briefs/prompt.py`, `backend/src/overwatch/db/briefs.py`,
  `backend/src/overwatch/workers/tasks.py` (`_build_brief_request` only)
- Test: `backend/tests/test_brief_prompt.py`, `backend/tests/test_briefs_db.py`

**Interfaces:**
- Consumes: `ArticleRow` (Task 8), `articles_for_pair` (Task 7).
- Produces: `persist_validated(..., claims: list[tuple[str, str, list[int], list[int]]])` — the claim tuple gains a
  **fourth** element, `article_ids`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brief_prompt.py`:

```python
def test_prompt_renders_articles_with_ids_and_the_reported_speech_rule():
    request = _request_with_articles()  # reuse the helper from test_brief_validator
    prompt = build_prompt(request)
    assert "[99]" in prompt
    assert "mongabay.com" in prompt
    assert "reported" in prompt.lower()
    # The rule the model must obey has to be IN the prompt, not just in the validator.
    assert "may not" in prompt.lower() or "never" in prompt.lower()


def test_prompt_omits_the_sources_section_when_there_are_no_articles():
    request = _request_with_articles()
    request.articles = []
    assert "SOURCES" not in build_prompt(request)


def test_articles_are_capped_and_truncation_is_logged(caplog):
    request = _request_with_articles()
    request.articles = [
        ArticleRow(id=i, title=f"Amazon deforestation report {i}", domain="d.com",
                   seendate=date(2023, 8, 11))
        for i in range(50)
    ]
    with caplog.at_level("INFO"):
        prompt = build_prompt(request)
    assert prompt.count("mongabay.com") == 0
    assert "truncat" in caplog.text.lower()
```

Append to `backend/tests/test_briefs_db.py`:

```python
def test_persist_validated_writes_article_evidence_links(db_session, seeded_pair):
    aoi_id, _job_id, before_id, after_id = seeded_pair
    # ... create a brief + a NewsArticle row (id captured as article_id), then:
    persist_validated(
        db_session, brief_id,
        headline="h",
        claims=[("Regional news reports a probe.", "reported", [], [article_id])],
        model="m", usage={}, attempts=1, failures=[],
    )
    claims = claims_with_evidence(db_session, brief_id)
    links = claims[0][1]
    assert [link.evidence_type for link in links] == ["article"]
    assert links[0].article_id == article_id
    assert links[0].detection_id is None
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose exec -T api pytest tests/test_brief_prompt.py tests/test_briefs_db.py -v`
Expected: FAIL.

- [ ] **Step 3: Extend the prompt**

In `backend/src/overwatch/briefs/prompt.py`, after the detections block, render a sources block (only when
`request.articles` is non-empty), capped at `settings.fusion_max_prompt_articles` with a logged truncation — mirroring
the Phase-4 detection cap exactly:

```python
    if request.articles:
        shown = request.articles[: settings.fusion_max_prompt_articles]
        if len(request.articles) > len(shown):
            logger.info(
                "brief prompt: truncated %d articles to %d",
                len(request.articles), len(shown),
            )
        lines.append("\nSOURCES (news articles — REPORTED, not observed):")
        for a in shown:
            lines.append(f"  [{a.id}] {a.seendate.isoformat()} {a.domain}: {a.title}")
        lines.append(
            "\nRULES FOR SOURCES:\n"
            "  - A claim supported ONLY by articles MUST use claim_type 'reported', MUST cite "
            "its article ids in `article_evidence`, and MUST be phrased as reported speech "
            "(e.g. 'Regional news reports that…').\n"
            "  - Such a claim may NEVER use observational framing ('imagery confirms…') and "
            "may NEVER carry a quantity. Only detections carry measured figures.\n"
            "  - Use 'mixed' only when a claim cites BOTH a detection id and an article id."
        )
```

- [ ] **Step 4: Extend persistence**

In `backend/src/overwatch/db/briefs.py`, change `persist_validated`'s `claims` parameter type to
`list[tuple[str, str, list[int], list[int]]]` (text, claim_type, detection_ids, article_ids) and, alongside the existing
detection `EvidenceLink` loop, add:

```python
        for article_id in article_ids:
            session.add(
                EvidenceLink(
                    claim_id=claim.id,
                    evidence_type="article",
                    article_id=article_id,
                )
            )
```

- [ ] **Step 5: Wire the task**

In `backend/src/overwatch/workers/tasks.py`, in `_build_brief_request`, load the articles and pass them:

```python
    from overwatch.db.news import articles_for_pair  # add to the module's imports

    articles = articles_for_pair(
        session, aoi_id=brief.aoi_id, after_scene_id=brief.after_scene_id
    )
```

and add to the returned `BriefRequest(...)`:

```python
        articles=[
            ArticleRow(
                id=a.id, title=a.title, domain=a.domain, seendate=a.seendate.date()
            )
            for a in articles
        ],
```

Then update the `persist_validated` call in `generate_brief` to pass the fourth tuple element:

```python
                claims=[
                    (c.text, c.claim_type, c.evidence, c.article_evidence)
                    for c in result.draft.claims
                ],
```

- [ ] **Step 6: Run the tests**

Run: `docker compose exec -T api pytest tests/test_brief_prompt.py tests/test_briefs_db.py tests/test_brief_task.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/overwatch/briefs/prompt.py backend/src/overwatch/db/briefs.py backend/src/overwatch/workers/tasks.py backend/tests/
git commit -m "feat(phase-5): briefs read, prompt, and cite news articles as reported evidence"
```

---

## Task 10: The `fuse` task + chain wiring + kill-switch

**Files:**
- Modify: `backend/src/overwatch/workers/tasks.py`
- Test: `backend/tests/test_fusion_task.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces: `fuse(job_id: str)` Celery task registered as `overwatch.fuse`; `get_news_provider()` factory (monkeypatched
  in tests); `dispatch_fusion_job(job_id)`; `dispatch_detection_job` now appends `fuse` when `settings.fusion_enabled`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_fusion_task.py`:

```python
import json
from pathlib import Path

from overwatch.db.news import articles_for_pair
from overwatch.fusion.provider import FakeNewsProvider
from overwatch.workers import tasks

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"


def test_chain_includes_fuse_when_fusion_enabled(monkeypatch):
    monkeypatch.setattr(tasks.settings, "fusion_enabled", True)
    captured = {}
    monkeypatch.setattr(
        tasks, "chain", lambda *sigs: type("C", (), {"apply_async": lambda s: captured.update(n=len(sigs))})()
    )
    tasks.dispatch_detection_job("00000000-0000-0000-0000-000000000000")
    assert captured["n"] == 4  # ingest, ingest, detect, fuse


def test_chain_excludes_fuse_when_fusion_disabled(monkeypatch):
    monkeypatch.setattr(tasks.settings, "fusion_enabled", False)
    captured = {}
    monkeypatch.setattr(
        tasks, "chain", lambda *sigs: type("C", (), {"apply_async": lambda s: captured.update(n=len(sigs))})()
    )
    tasks.dispatch_detection_job("00000000-0000-0000-0000-000000000000")
    assert captured["n"] == 3


def test_fuse_persists_only_gate_passing_articles(db_session, seeded_forest_job, monkeypatch):
    """The Malayalam article must be dropped by the language precondition; the
    non-thematic one by Gate 3. Only real survivors reach the DB."""
    body = json.loads((FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(tasks, "get_news_provider", lambda: FakeNewsProvider.from_artlist(body))
    job_id, aoi_id, after_id = seeded_forest_job  # a PORT aoi + succeeded job, in-window

    tasks.fuse.apply(args=(str(job_id),))

    rows = articles_for_pair(db_session, aoi_id=aoi_id, after_scene_id=after_id)
    titles = [r.title for r in rows]
    assert len(rows) == 3  # 4 in, 1 Malayalam dropped
    assert all("English" == r.language for r in rows)
    assert any("Customs grants approval" in t for t in titles)


def test_fuse_is_a_noop_when_the_aoi_has_no_place_terms(db_session, seeded_pair, monkeypatch, caplog):
    # An AOI with no terms cannot be gated. Skip and say so — never guess.
    ...
    assert "no place_terms" in caplog.text
```

> `seeded_forest_job` is a new conftest fixture: a **port**-vertical AOI (so the Vizhinjam fixture's themes/keywords
> apply) with `place_terms=["Vizhinjam"]`, a succeeded job, and an after-scene captured **inside** the fixture's
> `seendate` range (2024-06-15..2024-07-15) — e.g. `captured_at = 2024-07-01`, which puts the 44-day window at
> 2024-06-01..2024-07-15 and admits all three English articles.

- [ ] **Step 2: Run and watch fail**

Run: `docker compose exec -T api pytest tests/test_fusion_task.py -v`
Expected: FAIL — `AttributeError: module 'overwatch.workers.tasks' has no attribute 'fuse'`.

- [ ] **Step 3: Implement**

In `backend/src/overwatch/workers/tasks.py`, add imports:

```python
from overwatch.db.news import articles_for_pair, replace_articles
from overwatch.fusion.models import FusionWindow
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.provider import (
    GdeltDocProvider,
    NewsProvider,
    TransientFusionError,
    build_query,
)
from overwatch.fusion.scorer import dedupe, score_article
```

Change `dispatch_detection_job`:

```python
def dispatch_detection_job(job_id: str) -> None:
    signatures = [
        ingest_scene.si(job_id, "before"),
        ingest_scene.si(job_id, "after"),
        run_detection.si(job_id),
    ]
    if settings.fusion_enabled:
        signatures.append(fuse.si(job_id))
    chain(*signatures).apply_async()


def dispatch_fusion_job(job_id: str) -> None:
    fuse.delay(job_id)


def get_news_provider() -> NewsProvider:
    """Module-level factory so tests can monkeypatch the provider."""
    return GdeltDocProvider()
```

Add the retry profile and the task:

```python
_FUSION_RETRY = {
    "base": JobTask,
    "bind": True,
    "autoretry_for": (TransientFusionError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
}

# Domain preference for syndication dedup — wires rank above the outlets that carry them.
_DOMAIN_RANK = [
    "reuters.com", "apnews.com", "bbc.co.uk", "thehindu.com", "thehindubusinessline.com",
    "news.mongabay.com", "riotimesonline.com", "usnews.com", "yahoo.com",
]


@celery_app.task(name="overwatch.fuse", **_FUSION_RETRY)
def fuse(self: Task, job_id: str) -> int:
    """Correlate news against this job's AFTER scene (Phase 5 design §6).

    A GDELT failure fails ONLY this task — ingestion, detection and briefs are already
    done by the time it runs, and a brief simply has no news section.
    """
    with session_scope() as session:
        job = get_job(session, job_id)
        if job is None or job.after_scene_id is None:
            raise JobFailure(f"job {job_id} has no after scene to anchor fusion on")
        aoi = session.get(Aoi, job.aoi_id)
        aoi_id, vertical, slug = aoi.id, aoi.vertical, aoi.slug
        place_terms = list(aoi.place_terms or [])
        region_terms = list(aoi.region_terms or [])
        before_id, after_id = job.before_scene_id, job.after_scene_id
        after_captured_at = session.get(Scene, after_id).captured_at

    if not place_terms:
        logger.info("fusion skip %s: no place_terms configured on the AOI", slug)
        return 0

    preset = FUSION_PRESETS[vertical]
    window = FusionWindow.around(after_captured_at, preset)
    query = build_query(place_terms[0], preset)  # STRICT term — full-text, GDELT-side

    candidates = get_news_provider().search(query, window.start, window.end)

    admitted_raw = []
    for candidate in candidates:
        gates = score_article(
            candidate,
            place_terms=place_terms,
            region_terms=region_terms,
            window=window,
            preset=preset,
            languages=settings.fusion_languages,
        )
        if gates.passed:
            admitted_raw.append((candidate, gates))

    survivors = dedupe([a for a, _ in admitted_raw], domain_rank=_DOMAIN_RANK)
    gates_by_url = {a.url: g for a, g in admitted_raw}
    admitted = [
        (article, gates_by_url[article.url], suppressed, query)
        for article, suppressed in survivors
    ]

    with session_scope() as session:
        count = replace_articles(
            session,
            aoi_id=aoi_id,
            job_id=job_id,
            before_scene_id=before_id,
            after_scene_id=after_id,
            admitted=admitted,
        )
    logger.info(
        "job %s: %d/%d articles admitted for %s (query=%s)",
        job_id, count, len(candidates), slug, query,
    )
    return count
```

- [ ] **Step 4: Restart the workers (they do not hot-reload)**

Run:
```bash
docker compose restart worker beat
docker compose exec -T api celery -A overwatch.workers.celery_app inspect registered
```
Expected: `overwatch.fuse` appears in the list.

- [ ] **Step 5: Run the tests**

Run: `docker compose exec -T api pytest tests/test_fusion_task.py tests/test_tasks.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/overwatch/workers/tasks.py backend/tests/test_fusion_task.py backend/tests/conftest.py
git commit -m "feat(phase-5): fuse celery task, chain wiring, FUSION_ENABLED kill-switch"
```

---

## Task 11: `POST /aois/{slug}/fusion` endpoint

**Files:**
- Create: `backend/src/overwatch/api/fusion.py`
- Modify: `backend/src/overwatch/api/main.py`
- Test: `backend/tests/test_api_fusion.py`

**Interfaces:**
- Consumes: `require_aoi`, `SessionDep` (`api/aois.py`), `ApiError` (`api/errors.py`),
  `latest_succeeded_job` (`db/jobs.py`), `dispatch_fusion_job` (Task 10).
- Produces: `POST /aois/{slug}/fusion` → `202 {"job_id": "<uuid>"}`.

**Guard order matters** (mirrors the Phase-4 brief endpoint's discipline): kill-switch **first** — a disabled server must
never leak a 409 about a missing baseline before reporting that fusion is off at all.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_fusion.py`:

```python
def test_fusion_disabled_returns_503_before_any_other_guard(client, monkeypatch):
    monkeypatch.setattr("overwatch.api.fusion.settings.fusion_enabled", False)
    r = client.post("/aois/does-not-exist/fusion")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "fusion_disabled"


def test_unknown_aoi_returns_404(client):
    r = client.post("/aois/nope/fusion")
    assert r.status_code == 404


def test_aoi_without_a_succeeded_job_returns_409(client, seeded_aoi_no_jobs):
    r = client.post(f"/aois/{seeded_aoi_no_jobs}/fusion")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "no_baseline_run"


def test_aoi_without_place_terms_returns_409(client, seeded_aoi_no_terms):
    r = client.post(f"/aois/{seeded_aoi_no_terms}/fusion")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "fusion_unconfigured"


def test_happy_path_returns_202_and_dispatches(client, seeded_pair, monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "overwatch.api.fusion.dispatch_fusion_job", lambda jid: dispatched.append(jid)
    )
    r = client.post("/aois/novo-progresso/fusion")
    assert r.status_code == 202
    assert "job_id" in r.json()
    assert dispatched == [r.json()["job_id"]]
```

- [ ] **Step 2: Run and watch fail**

Run: `docker compose exec -T api pytest tests/test_api_fusion.py -v`
Expected: FAIL — 404 on the route itself (not mounted).

- [ ] **Step 3: Implement**

Create `backend/src/overwatch/api/fusion.py`:

```python
"""Fusion backfill endpoint (Phase 5 design §6).

Guard order mirrors the brief endpoint's: the kill-switch is checked FIRST, so a server
with fusion disabled reports that plainly instead of leaking a 409 about a missing
baseline it would never have used anyway.
"""

from fastapi import APIRouter

from overwatch.api.aois import SessionDep, require_aoi
from overwatch.api.errors import ApiError
from overwatch.config import settings
from overwatch.db.jobs import latest_succeeded_job
from overwatch.workers.tasks import dispatch_fusion_job

router = APIRouter(tags=["fusion"])


@router.post("/aois/{slug}/fusion", status_code=202)
def submit_fusion(slug: str, session: SessionDep) -> dict[str, str]:
    if not settings.fusion_enabled:
        raise ApiError(503, "fusion_disabled", "fusion is disabled on this server")
    aoi = require_aoi(session, slug)
    if not aoi.place_terms:
        raise ApiError(
            409,
            "fusion_unconfigured",
            f"AOI {slug!r} has no place_terms; fusion cannot be gated without them",
        )
    baseline = latest_succeeded_job(session, aoi.id)
    if baseline is None:
        raise ApiError(409, "no_baseline_run", f"no succeeded job for AOI {slug!r}")
    job_id = str(baseline.id)
    dispatch_fusion_job(job_id)
    return {"job_id": job_id}
```

In `backend/src/overwatch/api/main.py`, add `fusion` to the import and
`app.include_router(fusion.router)` after the briefs router.

- [ ] **Step 4: Run the tests**

Run: `docker compose exec -T api pytest tests/test_api_fusion.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/overwatch/api/fusion.py backend/src/overwatch/api/main.py backend/tests/test_api_fusion.py
git commit -m "feat(phase-5): POST /aois/{slug}/fusion backfill endpoint with kill-switch guard"
```

---

## Task 12: Verification gate

**Files:** none (verification only). Record evidence in `PROGRESS.md`.

**This task produces no code. It produces PROOF.** Per `superpowers:verification-before-completion`: run the command,
read the output, *then* claim. No claim without a pasted output.

- [ ] **Step 1: Full non-live gate**

```bash
docker compose exec -T api pytest -q
docker compose exec -T api ruff check .
docker compose exec -T api ruff format --check .
docker compose exec -T api alembic current
docker compose exec -T api celery -A overwatch.workers.celery_app inspect registered | grep fuse
```
Expected: all tests pass; ruff clean; `alembic current` → `0004 (head)`; `overwatch.fuse` registered.

- [ ] **Step 2: Live gate — real GDELT, all three AOIs**

```bash
docker compose exec -T api python -m overwatch.db.seed
curl -s -X POST localhost:8000/aois/novo-progresso/fusion | tee /dev/stderr
sleep 20
curl -s "localhost:8000/aois/novo-progresso/brief" | python -m json.tool
```

Then the **SQL join proof** — every citation resolves to a real row:

```bash
docker compose exec -T postgis psql -U overwatch -d overwatch -c "
SELECT b.id AS brief, bc.seq, bc.claim_type, n.domain, n.title, n.gates_passed
FROM briefs b
JOIN brief_claims bc ON bc.brief_id = b.id
JOIN evidence_links el ON el.claim_id = bc.id AND el.evidence_type = 'article'
JOIN news_articles n ON n.id = el.article_id
WHERE b.status = 'validated';"
```
Expected: ≥1 row, each showing which terms/keywords admitted the article.

- [ ] **Step 3: Negative test — an irrelevant article is demonstrably rejected**

```bash
docker compose exec -T api python -c "
from datetime import UTC, datetime
from overwatch.fusion.models import FusionWindow, RawArticle
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.scorer import score_article
w = FusionWindow(start=datetime(2023,8,6,tzinfo=UTC), end=datetime(2023,9,19,tzinfo=UTC))
a = RawArticle(url='https://x.com/1', title='Amazon Prime Day deals announced',
               domain='x.com', language='English', seendate=datetime(2023,8,15,tzinfo=UTC))
r = score_article(a, place_terms=['Novo Progresso'], region_terms=['Amazon'], window=w,
                  preset=FUSION_PRESETS['forest'], languages=['English'])
print('passed:', r.passed, '| toponym:', r.toponym, '| rejected_by:', r.reason)
"
```
Expected: `passed: False | toponym: ['Amazon'] | rejected_by: thematic`
**This is the money shot:** the toponym gate fired on "Amazon", and the AND still rejected it.

- [ ] **Step 4: Kill-switch, both ways**

```bash
OVERWATCH_FUSION_ENABLED=false docker compose exec -T api python -c "
from overwatch.config import Settings
print('enabled:', Settings().fusion_enabled)"
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/aois/novo-progresso/fusion
```
Expected: with the flag off → `503`; on → `202`.

- [ ] **Step 5: Idempotency + stale flip**

Re-run fusion on the same AOI, then:
```bash
docker compose exec -T postgis psql -U overwatch -d overwatch -c "
SELECT count(*) AS articles FROM news_articles;
SELECT id, status FROM briefs ORDER BY id DESC LIMIT 3;"
```
Expected: article count **unchanged** (zero duplicates); the previously-`validated` brief on that pair is now `stale`.

- [ ] **Step 6: Update PROGRESS.md and commit**

Record every command above **with its actual output** under "Last verified working". Nothing is done without a
verification note.

```bash
git add PROGRESS.md
git commit -m "docs(phase-5): verification evidence — gates, negative test, kill-switch, idempotency"
```

---

## Self-Review

**Spec coverage:** §2 spike → Tasks 2/6 (verified themes, plaintext handling) + CONTEXT.md. §3 decisions 1–8 → Tasks
2 (3, 7), 4 (1, 2), 5 (8), 8 (5), 10 (6), 11 (6). §4 scorer → Tasks 3–5. §5 data model → Task 1. §6 components → Tasks
6, 10, 11, 8. §7 testing → every task is TDD; §8 gate → Task 12. **No uncovered requirement.**

**Type consistency:** `GateResult` fields (`passed`, `toponym`, `temporal`, `thematic`, `reason`) are used identically in
Tasks 4, 7, 10. `Admitted = (RawArticle, GateResult, list[str], str)` matches `replace_articles` in Task 7 and its
construction in Task 10. `persist_validated`'s claim tuple is 4-wide in both Task 9's definition and its Task 9 call
site. `score_article` is keyword-only in its definition (Task 4) and every call (Tasks 10, 12).

**Known follow-up:** `dedupe` is applied *after* scoring, so `gates_by_url` (Task 10) assumes URLs are unique within one
GDELT response. They are — the natural key relies on the same property.
