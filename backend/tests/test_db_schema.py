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
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename IN ('aois', 'detections')"
            )
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


def test_briefs_tables_exist(migrated_db: None) -> None:
    insp = inspect(get_engine())
    for table in ("briefs", "brief_claims", "evidence_links"):
        assert insp.has_table(table), f"missing table {table}"
    brief_cols = {c["name"] for c in insp.get_columns("briefs")}
    assert {
        "id",
        "aoi_id",
        "before_scene_id",
        "after_scene_id",
        "status",
        "attempts",
        "headline",
        "model",
        "usage",
        "violations",
        "error",
        "created_at",
        "updated_at",
    } <= brief_cols
    link_cols = {c["name"] for c in insp.get_columns("evidence_links")}
    assert {"claim_id", "evidence_type", "detection_id"} <= link_cols


def test_news_articles_table_and_natural_key(migrated_db: None) -> None:
    insp = inspect(get_engine())
    assert insp.has_table("news_articles")
    cols = {c["name"] for c in insp.get_columns("news_articles")}
    assert {
        "id",
        "aoi_id",
        "job_id",
        "after_scene_id",
        "url",
        "title",
        "domain",
        "language",
        "seendate",
        "gates_passed",
        "query",
        "meta",
        "created_at",
    } <= cols
    # No geometry column: GDELT exposes no article geotag (Phase 5 design §2.2).
    assert "geom" not in cols
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("news_articles")}
    assert ("aoi_id", "after_scene_id", "url") in uniques


def test_aois_have_toponym_term_arrays(migrated_db: None) -> None:
    insp = inspect(get_engine())
    cols = {c["name"] for c in insp.get_columns("aois")}
    assert {"place_terms", "region_terms"} <= cols


def test_evidence_links_article_id_and_check(migrated_db: None) -> None:
    insp = inspect(get_engine())
    cols = {c["name"] for c in insp.get_columns("evidence_links")}
    assert "article_id" in cols
    checks = {c["name"] for c in insp.get_check_constraints("evidence_links")}
    assert "ck_evidence_links_article_id" in checks
