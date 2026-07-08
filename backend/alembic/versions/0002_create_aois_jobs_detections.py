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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
