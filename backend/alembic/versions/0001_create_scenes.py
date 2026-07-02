"""create scenes table

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "scenes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stac_id", sa.Text(), nullable=False),
        sa.Column("aoi_slug", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_pct", sa.Float(), nullable=False),
        sa.Column("usable_fraction", sa.Float(), nullable=True),
        sa.Column("epsg", sa.Integer(), nullable=False),
        sa.Column(
            "window_geom",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
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
        sa.UniqueConstraint("stac_id", "aoi_slug", name="uq_scenes_stac_id_aoi_slug"),
    )
    op.execute("CREATE INDEX ix_scenes_window_geom ON scenes USING gist (window_geom)")


def downgrade() -> None:
    op.drop_table("scenes")
