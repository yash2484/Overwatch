"""Pure contracts for OSINT fusion (Phase 5 design §4). No I/O, no DB, no LLM."""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from overwatch.fusion.presets import FusionPreset


class RawArticle(BaseModel):
    """One GDELT DOC 2.0 artlist record.

    These are ALL the fields DOC returns (design §2.2) — note the conspicuous absence of
    any coordinate. `sourcecountry` is the PUBLISHER'S REGISTRATION COUNTRY, not the
    story's location (Mongabay's Amazon/Para piece returns "Indonesia"). It is carried
    for provenance only and must NEVER be used as a geographic proxy (design §2.3).
    """

    url: str
    title: str
    domain: str
    language: str
    seendate: datetime
    socialimage: str = ""
    sourcecountry: str = ""


class FusionWindow(BaseModel):
    """Observation window, anchored on the AFTER scene (design decision 3).

    The inherited spec anchored on the whole before->after scene gap, which for Vizhinjam
    is ~3 years — a "gate" that accepts nearly everything. This is a ~44-day band around
    when the change was actually observed.
    """

    start: datetime
    end: datetime

    @classmethod
    def around(cls, after_captured_at: datetime, preset: FusionPreset) -> "FusionWindow":
        return cls(
            start=after_captured_at - timedelta(days=preset.lead_days),
            end=after_captured_at + timedelta(days=preset.lag_days),
        )


class GateResult(BaseModel):
    """Why an article was admitted or rejected. Persisted so every citation is auditable."""

    passed: bool
    toponym: list[str] = Field(default_factory=list)  # matched place/region terms
    temporal: bool = False
    thematic: list[str] = Field(default_factory=list)  # matched vertical keywords
    reason: str | None = None  # the failing gate; set only when passed is False
