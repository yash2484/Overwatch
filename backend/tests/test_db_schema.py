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
