"""create news_articles, aoi toponym term arrays, evidence_links.article_id

Additive only (Phase 5 design §5). Gate 1 is the TOPONYM gate, not a spatial one:
GDELT exposes no article geotag (design §2.2) and its geocoder is centroid-based by
GDELT's own documentation, so there is deliberately NO geometry column on this table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

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
            UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("after_scene_id", sa.BigInteger, sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("seendate", sa.DateTime(timezone=True), nullable=False),
        # Which terms/keywords admitted this article — every citation is auditable.
        sa.Column("gates_passed", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # The exact GDELT query string that retrieved it.
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Natural key -> idempotent re-fusion, same convention as scenes/detections.
        sa.UniqueConstraint(
            "aoi_id", "after_scene_id", "url", name="uq_news_articles_aoi_scene_url"
        ),
    )
    op.create_index("ix_news_articles_pair", "news_articles", ["aoi_id", "after_scene_id"])

    # Toponym gate inputs. Null/empty place_terms -> fusion is skipped for that AOI.
    op.add_column("aois", sa.Column("place_terms", ARRAY(sa.Text), nullable=True))
    op.add_column("aois", sa.Column("region_terms", ARRAY(sa.Text), nullable=True))

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
    op.drop_index("ix_news_articles_pair", table_name="news_articles")
    op.drop_table("news_articles")
