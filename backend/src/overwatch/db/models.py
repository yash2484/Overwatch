"""ORM models. scenes = Sentinel-2 scene metadata per AOI window (design spec §4);
aois/jobs/detections = Phase 3 persistence (design doc 2026-07-07 §2)."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Scene(Base):
    """One Sentinel-2 scene's metadata for one AOI window.

    Natural key (stac_id, aoi_slug): usable fraction and window bounds are
    AOI-window-specific, so the same STAC scene may legitimately row once per AOI.
    """

    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("stac_id", "aoi_slug", name="uq_scenes_stac_id_aoi_slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stac_id: Mapped[str] = mapped_column(Text, nullable=False)
    aoi_slug: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_pct: Mapped[float] = mapped_column(Float, nullable=False)
    usable_fraction: Mapped[float | None] = mapped_column(Float)
    epsg: Mapped[int] = mapped_column(Integer, nullable=False)
    window_geom = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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


class Brief(Base):
    """One generated brief over a scene pair (Phase 4 design §2). Append-only history."""

    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aoi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aois.id", ondelete="CASCADE"), nullable=False
    )
    before_scene_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scenes.id"), nullable=False
    )
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
