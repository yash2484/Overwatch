"""Pydantic v2 boundary models for the Phase 3 API (design doc §3)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AoiCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    name: str = Field(min_length=1, max_length=200)
    vertical: Literal["port", "forest", "flood"]
    geometry: dict[str, Any]  # GeoJSON Polygon, validated against shapely in the endpoint
    cadence_days: int | None = Field(default=None, ge=1)


class AoiOut(BaseModel):
    slug: str
    name: str
    vertical: str
    geometry: dict[str, Any]
    cadence_days: int | None
    area_km2: float
    created_at: datetime


class DateWindow(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "DateWindow":
        if self.end < self.start:
            raise ValueError("window end is before start")
        return self


class JobSubmit(BaseModel):
    before: DateWindow
    after: DateWindow


class JobOut(BaseModel):
    id: UUID
    aoi_slug: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str | None
    attempts: int
    params: dict[str, Any]
    before_scene_id: int | None
    after_scene_id: int | None
    detection_count: int | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class BriefSubmit(BaseModel):
    before_scene_id: int | None = None
    after_scene_id: int | None = None

    @model_validator(mode="after")
    def _both_or_neither(self) -> "BriefSubmit":
        has_before = self.before_scene_id is not None
        has_after = self.after_scene_id is not None
        if has_before != has_after:
            raise ValueError("before_scene_id and after_scene_id must both be set or both omitted")
        return self


class ClaimOut(BaseModel):
    seq: int
    text: str
    claim_type: str
    detection_ids: list[int]


class BriefOut(BaseModel):
    id: int
    aoi_slug: str
    status: str
    attempts: int
    headline: str | None
    model: str | None
    usage: dict[str, Any]
    violations: list[Any] | None
    error: dict[str, Any] | None
    before_scene_id: int
    after_scene_id: int
    claims: list[ClaimOut]
    created_at: datetime
    updated_at: datetime
