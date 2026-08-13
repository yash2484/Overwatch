"""Pure Pydantic contracts for LLM-generated intelligence briefs (Phase 4 design).

No I/O, no DB, no LLM calls here. This is the frozen interface the parallel lanes
(prompt/generation, validation, persistence wiring) build against — `BriefDraft` in
particular is passed to the Anthropic SDK as a structured-output schema, so it must
stay plain: no arbitrary types, no custom validators.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

ClaimType = Literal["observed", "context", "reported", "mixed"]


class ClaimDraft(BaseModel):
    text: str
    claim_type: ClaimType
    evidence: list[int] = []  # detection ids — OBSERVED (pixels)
    # news_article ids — REPORTED (journalism). Kept in a SEPARATE field from `evidence`
    # so the model structurally cannot conflate sensing with reporting (Phase 5 §6).
    article_evidence: list[int] = []


class BriefDraft(BaseModel):
    headline: str
    claims: list[ClaimDraft]


class Violation(BaseModel):
    code: str
    claim_seq: int | None = None
    message: str
    detail: dict[str, Any] | None = None


class DetectionRow(BaseModel):  # slim view for prompt + validator
    id: int
    change_type: str
    area_m2: float
    magnitude: float
    confidence: float


class ArticleRow(BaseModel):  # slim view for prompt + validator (Phase 5)
    id: int
    title: str
    domain: str
    seendate: date


class BriefRequest(BaseModel):
    aoi_name: str
    aoi_slug: str
    vertical: str
    before_scene_id: int
    after_scene_id: int
    before_date: date
    after_date: date
    detections: list[DetectionRow]
    articles: list[ArticleRow] = []  # Phase 5 — may be empty (fusion off / no survivors)


class AttemptFailure(BaseModel):
    draft: BriefDraft
    violations: list[Violation]


class BriefGeneration(BaseModel):
    draft: BriefDraft
    model: str
    usage: dict[str, int]  # input_tokens, output_tokens
