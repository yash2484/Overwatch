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
    """The observation window: CAPPED INTERVAL (design decision 3, revised 2026-07-12).

    Two earlier formulations were both wrong, and real data killed each:

    1. **The inherited spec** anchored on the whole before->after gap. Vizhinjam's real
       pair spans 1,460 days, so the "gate" was a ~4-year window that accepted nearly
       anything. Vacuous.
    2. **After-scene-anchored** (a 44-day band) fixed that but broke the forest AOI.
       Novo Progresso's real pair is 2023-07-30 -> 2024-07-24, so the band was
       2024-06-24..2024-08-07 — and a live GDELT query over it returned **zero
       articles**. The deforestation coverage (Aug-Sep 2023) lands when the clearing
       *happens*, spread across the interval, not near the after-scene.

    The fix keeps what each got right. News is admitted from the **observation interval**
    — the span over which the change actually accumulated — but that interval is **capped**
    at `max_lookback_days` so a multi-year baseline cannot become a multi-year news sweep:

        start = max(before_scene, after_scene - max_lookback_days) - lead_days
        end   = after_scene + lag_days

    Verified against all three real pairs:
      * Novo Progresso (360d gap): 2023-06-30..2024-08-07 — admits the Aug-2023 stories.
      * Vizhinjam     (1460d gap): 2023-12-08..2025-02-25 — ~14 months, NOT 4 years.
                                    The cap is what does that. Admits the Jun-2024 stories.
      * Porto Alegre    (33d gap): 2024-03-19..2024-06-04 — tight, because the event was.
    """

    start: datetime
    end: datetime

    @classmethod
    def around(
        cls,
        before_captured_at: datetime,
        after_captured_at: datetime,
        preset: FusionPreset,
    ) -> "FusionWindow":
        earliest = after_captured_at - timedelta(days=preset.max_lookback_days)
        interval_start = max(before_captured_at, earliest)
        return cls(
            start=interval_start - timedelta(days=preset.lead_days),
            end=after_captured_at + timedelta(days=preset.lag_days),
        )


class GateResult(BaseModel):
    """Why an article was admitted or rejected. Persisted so every citation is auditable."""

    passed: bool
    toponym: list[str] = Field(default_factory=list)  # matched place/region terms
    temporal: bool = False
    thematic: list[str] = Field(default_factory=list)  # matched vertical keywords
    reason: str | None = None  # the failing gate; set only when passed is False
