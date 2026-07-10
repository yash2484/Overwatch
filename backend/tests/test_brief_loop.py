"""Tests for overwatch.briefs.loop — the bounded generation/validation loop.

Uses FakeBriefGenerator plus a stub validator so these tests exercise loop control flow
(feedback threading, attempt counting, usage summation, terminal status) in isolation from
Lane A's real validator (briefs/validator.py) and Lane C's prompt module.
"""

from datetime import date

from overwatch.briefs.generator import FAKE_INPUT_TOKENS, FAKE_OUTPUT_TOKENS, FakeBriefGenerator
from overwatch.briefs.loop import run_brief_loop
from overwatch.briefs.models import BriefDraft, BriefRequest, ClaimDraft, Violation


def _draft(tag: str) -> BriefDraft:
    return BriefDraft(
        headline=f"Headline {tag}",
        claims=[ClaimDraft(text=f"Claim {tag}", claim_type="observed", evidence=[1])],
    )


def _req() -> BriefRequest:
    return BriefRequest(
        aoi_name="Test AOI",
        aoi_slug="test-aoi",
        vertical="port",
        before_scene_id=1,
        after_scene_id=2,
        before_date=date(2026, 1, 1),
        after_date=date(2026, 2, 1),
        detections=[],
    )


def _reject_first_n(n: int):
    calls = {"count": 0}

    def validate(draft: BriefDraft, request: BriefRequest) -> list[Violation]:
        calls["count"] += 1
        if calls["count"] <= n:
            return [Violation(code="unlinked_claim", claim_seq=0, message="no evidence")]
        return []

    return validate


def test_first_try_validates() -> None:
    gen = FakeBriefGenerator([_draft("A")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(0), max_attempts=3)
    assert result.status == "validated" and result.attempts == 1 and result.failures == []
    assert result.draft is not None
    assert result.draft.headline == "Headline A"
    assert result.model == "fake"
    assert result.usage == {"input_tokens": FAKE_INPUT_TOKENS, "output_tokens": FAKE_OUTPUT_TOKENS}
    assert gen.calls == [[]]


def test_feedback_flows_to_second_attempt() -> None:
    gen = FakeBriefGenerator([_draft("A"), _draft("B")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(1), max_attempts=3)
    assert result.status == "validated" and result.attempts == 2
    # attempt 2 saw attempt 1's violations
    assert gen.calls[1][0].violations[0].code == "unlinked_claim"
    assert result.usage["output_tokens"] == 2 * FAKE_OUTPUT_TOKENS  # summed
    assert result.usage["input_tokens"] == 2 * FAKE_INPUT_TOKENS
    assert result.draft is not None
    assert result.draft.headline == "Headline B"
    assert len(result.failures) == 1


def test_three_strikes_rejected_with_full_history() -> None:
    gen = FakeBriefGenerator([_draft("A"), _draft("B"), _draft("C")])
    result = run_brief_loop(gen, _req(), validate=_reject_first_n(99), max_attempts=3)
    assert result.status == "rejected" and result.attempts == 3
    assert len(result.failures) == 3 and result.draft is None
    assert result.usage["output_tokens"] == 3 * FAKE_OUTPUT_TOKENS
    # each failure records the draft that produced it, in attempt order
    assert [f.draft.headline for f in result.failures] == ["Headline A", "Headline B", "Headline C"]
    # attempt 3 was prompted with attempts 1 and 2's violations
    assert len(gen.calls[2]) == 2
