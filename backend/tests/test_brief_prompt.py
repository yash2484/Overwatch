"""Tests for overwatch.briefs.prompt — the Anthropic message builder (Phase 4, Task 6).

Pure string-building tests: no LLM calls, no network, no DB. Covers the first-turn
user message (AOI/pair/stats/detections), the detection-cap truncation behavior
(largest-by-area survive, true totals still reported, a warning is logged), the
feedback turns appended per AttemptFailure, and the verbatim SYSTEM_PROMPT content.
"""

import logging
from datetime import date

from overwatch.briefs.models import (
    AttemptFailure,
    BriefDraft,
    BriefRequest,
    ClaimDraft,
    DetectionRow,
    Violation,
)
from overwatch.briefs.prompt import SYSTEM_PROMPT, build_messages
from overwatch.config import settings


def _detection(id_: int, change_type: str, area_m2: float) -> DetectionRow:
    return DetectionRow(
        id=id_, change_type=change_type, area_m2=area_m2, magnitude=0.5, confidence=0.75
    )


def _request(detections: list[DetectionRow]) -> BriefRequest:
    return BriefRequest(
        aoi_name="Vizhinjam International Seaport, Kerala",
        aoi_slug="vizhinjam",
        vertical="port",
        before_scene_id=101,
        after_scene_id=102,
        before_date=date(2026, 1, 1),
        after_date=date(2026, 2, 15),
        detections=detections,
    )


def test_first_message_is_single_user_turn_with_full_context_under_cap() -> None:
    detections = [
        _detection(1, "new_structure", 500.0),
        _detection(2, "vegetation_loss", 1200.0),
        _detection(3, "road_change", 300.0),
    ]
    request = _request(detections)

    messages = build_messages(request, [])

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]

    assert request.aoi_name in content
    assert request.vertical in content
    assert request.before_date.isoformat() in content
    assert request.after_date.isoformat() in content
    for d in detections:
        assert f"id={d.id} type=" in content


def test_first_message_detection_line_format_is_exact() -> None:
    detections = [_detection(7, "new_structure", 1234.5)]
    request = _request(detections)

    messages = build_messages(request, [])
    content = messages[0]["content"]

    assert "id=7 type=new_structure area_m2=1234 magnitude=0.500 confidence=0.75" in content


def test_truncation_keeps_50_largest_and_reports_true_totals(caplog) -> None:
    # Non-monotonic area ordering: (i * 17) % 60 is a permutation of 0..59 since
    # gcd(17, 60) == 1, so input order is neither ascending nor descending by area.
    types = ["new_structure", "vegetation_loss", "road_change"]
    detections = []
    for i in range(60):
        rank = (i * 17) % 60
        area = float((rank + 1) * 100)  # distinct areas, 100..6000
        detections.append(_detection(i + 1, types[i % 3], area))
    request = _request(detections)

    assert settings.brief_max_prompt_detections == 50

    with caplog.at_level(logging.WARNING, logger="overwatch.briefs.prompt"):
        messages = build_messages(request, [])

    content = messages[0]["content"]

    # True aggregate totals over ALL 60 detections, not just the serialized 50.
    total_area = sum(d.area_m2 for d in detections)
    assert "60 detections" in content
    assert f"{total_area:.0f}" in content
    for t in types:
        count = sum(1 for d in detections if d.change_type == t)
        assert f"{t}={count}" in content

    sorted_desc = sorted(detections, key=lambda d: d.area_m2, reverse=True)
    included, excluded = sorted_desc[:50], sorted_desc[50:]
    assert len(included) == 50
    assert len(excluded) == 10
    for d in included:
        assert f"id={d.id} type=" in content
    for d in excluded:
        assert f"id={d.id} type=" not in content

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "60" in caplog.text
    assert "50" in caplog.text


def test_one_failure_adds_assistant_and_user_turns() -> None:
    request = _request([_detection(1, "new_structure", 500.0)])
    draft = BriefDraft(
        headline="Bad headline",
        claims=[ClaimDraft(text="Unsupported claim", claim_type="observed", evidence=[])],
    )
    violations = [
        Violation(code="MISSING_EVIDENCE", claim_seq=0, message="Claim cites no detection ids"),
    ]
    failures = [AttemptFailure(draft=draft, violations=violations)]

    messages = build_messages(request, failures)

    assert len(messages) == 3
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]

    assistant_content = messages[1]["content"]
    assert "Bad headline" in assistant_content
    assert "Unsupported claim" in assistant_content

    feedback_content = messages[2]["content"]
    assert "Your previous draft failed validation. Fix ALL violations" in feedback_content
    assert "[MISSING_EVIDENCE]" in feedback_content
    assert "claim #0" in feedback_content
    assert "Claim cites no detection ids" in feedback_content


def test_two_failures_yield_five_messages_in_order() -> None:
    request = _request([_detection(1, "new_structure", 500.0)])
    draft1 = BriefDraft(headline="First attempt", claims=[])
    draft2 = BriefDraft(headline="Second attempt", claims=[])
    failures = [
        AttemptFailure(
            draft=draft1,
            violations=[Violation(code="HEADLINE_TOO_VAGUE", message="Too vague")],
        ),
        AttemptFailure(
            draft=draft2,
            violations=[Violation(code="INVENTED_DETECTION", message="Cites unknown id 99")],
        ),
    ]

    messages = build_messages(request, failures)

    assert len(messages) == 5
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert "First attempt" in messages[1]["content"]
    assert "[HEADLINE_TOO_VAGUE]" in messages[2]["content"]
    assert "Second attempt" in messages[3]["content"]
    assert "[INVENTED_DETECTION]" in messages[4]["content"]
    assert "Cites unknown id 99" in messages[4]["content"]


def test_system_prompt_contains_citation_and_no_quantities_rules() -> None:
    assert isinstance(SYSTEM_PROMPT, str)
    assert "cite the detection ids" in SYSTEM_PROMPT
    assert "no numbers, percentages, areas, or dates" in SYSTEM_PROMPT
    assert '"observed"' in SYSTEM_PROMPT
    assert '"context"' in SYSTEM_PROMPT
