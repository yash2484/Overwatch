"""ORM models. scenes = Sentinel-2 scene metadata per AOI window (design spec §4)."""

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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
