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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
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
