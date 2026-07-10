"""Contract tests for overwatch.briefs.models — the frozen Pydantic interface Tasks 4-8 build on.

These tests exist to discriminate: they check that round-tripping preserves field values
(not merely "no exception"), that invalid literals are rejected, that nested models survive
serialization, and that the mutable-default list trap (`evidence: list[int] = []`) does not
leak state between instances.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from overwatch.briefs.models import (
    AttemptFailure,
    BriefDraft,
    BriefGeneration,
    BriefRequest,
    ClaimDraft,
    DetectionRow,
    Violation,
)


def test_brief_draft_round_trips_through_json() -> None:
    draft = BriefDraft(
        headline="Vessel traffic increased at Vizhinjam terminal",
        claims=[
            ClaimDraft(
                text="New container stacking observed", claim_type="observed", evidence=[1, 2]
            ),
            ClaimDraft(text="Consistent with monsoon dredging reports", claim_type="reported"),
        ],
    )

    reloaded = BriefDraft.model_validate_json(draft.model_dump_json())

    assert reloaded.headline == draft.headline == "Vessel traffic increased at Vizhinjam terminal"
    assert len(reloaded.claims) == 2
    assert reloaded.claims[0].text == "New container stacking observed"
    assert reloaded.claims[0].claim_type == "observed"
    assert reloaded.claims[0].evidence == [1, 2]
    assert reloaded.claims[1].claim_type == "reported"
    assert reloaded.claims[1].evidence == []


def test_claim_draft_rejects_invalid_claim_type() -> None:
    with pytest.raises(ValidationError):
        ClaimDraft(text="x", claim_type="bogus")


def test_claim_draft_evidence_defaults_to_empty_list_not_shared() -> None:
    a = ClaimDraft(text="a", claim_type="context")
    b = ClaimDraft(text="b", claim_type="context")

    assert a.evidence == []
    assert b.evidence == []
    assert a.evidence is not b.evidence

    a.evidence.append(42)
    assert a.evidence == [42]
    assert b.evidence == []


def test_attempt_failure_serializes_with_nested_violations() -> None:
    draft = BriefDraft(
        headline="Unverified headline",
        claims=[ClaimDraft(text="Unsupported claim", claim_type="mixed", evidence=[])],
    )
    violations = [
        Violation(
            code="MISSING_EVIDENCE",
            claim_seq=0,
            message="Claim cites no detection ids",
            detail={"claim_text": "Unsupported claim"},
        ),
        Violation(code="HEADLINE_TOO_VAGUE", message="Headline lacks a concrete change"),
    ]
    failure = AttemptFailure(draft=draft, violations=violations)

    reloaded = AttemptFailure.model_validate_json(failure.model_dump_json())

    assert reloaded.draft.headline == "Unverified headline"
    assert len(reloaded.violations) == 2
    assert reloaded.violations[0].code == "MISSING_EVIDENCE"
    assert reloaded.violations[0].claim_seq == 0
    assert reloaded.violations[0].detail == {"claim_text": "Unsupported claim"}
    assert reloaded.violations[1].code == "HEADLINE_TOO_VAGUE"
    assert reloaded.violations[1].claim_seq is None


def test_detection_row_round_trips() -> None:
    row = DetectionRow(
        id=7, change_type="new_structure", area_m2=1234.5, magnitude=0.82, confidence=0.91
    )

    reloaded = DetectionRow.model_validate_json(row.model_dump_json())

    assert reloaded.id == 7
    assert reloaded.change_type == "new_structure"
    assert reloaded.area_m2 == pytest.approx(1234.5)
    assert reloaded.magnitude == pytest.approx(0.82)
    assert reloaded.confidence == pytest.approx(0.91)


def test_brief_request_round_trips_with_dates_and_detections() -> None:
    request = BriefRequest(
        aoi_name="Vizhinjam International Seaport, Kerala",
        aoi_slug="vizhinjam",
        vertical="port",
        before_scene_id=101,
        after_scene_id=102,
        before_date=date(2026, 1, 1),
        after_date=date(2026, 2, 1),
        detections=[
            DetectionRow(
                id=1, change_type="new_structure", area_m2=500.0, magnitude=0.5, confidence=0.7
            ),
        ],
    )

    reloaded = BriefRequest.model_validate_json(request.model_dump_json())

    assert reloaded.aoi_slug == "vizhinjam"
    assert reloaded.before_date == date(2026, 1, 1)
    assert reloaded.after_date == date(2026, 2, 1)
    assert len(reloaded.detections) == 1
    assert reloaded.detections[0].change_type == "new_structure"


def test_brief_generation_round_trips_with_usage() -> None:
    draft = BriefDraft(headline="Headline", claims=[])
    generation = BriefGeneration(
        draft=draft, model="claude-opus-4-6", usage={"input_tokens": 512, "output_tokens": 128}
    )

    reloaded = BriefGeneration.model_validate_json(generation.model_dump_json())

    assert reloaded.model == "claude-opus-4-6"
    assert reloaded.usage == {"input_tokens": 512, "output_tokens": 128}
    assert reloaded.draft.headline == "Headline"
