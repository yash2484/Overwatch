"""Tests for overwatch.briefs.prompt — the Anthropic message builder (Phase 4, Task 6).

Pure string-building tests: no LLM calls, no network, no DB. Covers the first-turn
user message (AOI/pair/stats/detections), the detection-cap truncation behavior
(largest-by-area survive, true totals still reported, a warning is logged), the
feedback turns appended per AttemptFailure, and the verbatim SYSTEM_PROMPT content.

Phase 5 adds the SOURCES block: news articles rendered with their ids, plus the rules
the model must obey when citing them. Those rules are not decoration — the validator's
Gate 4 enforces every one of them, so the prompt has to state them or the model is being
set up to fail.
"""

import logging
from datetime import date

from overwatch.briefs.models import (
    ArticleRow,
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
    # Assert the exact labeled field the prompt renders (`vertical: port`), not a bare
    # substring check — `request.vertical` ("port") is also a substring of the AOI name
    # ("Vizhinjam International Seaport, Kerala"), so `request.vertical in content` would
    # pass even if the vertical field were never rendered at all.
    assert f"vertical: {request.vertical}" in content
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


def test_truncation_cap_is_read_from_settings_not_hardcoded(monkeypatch) -> None:
    # Proves the cap in `_select_for_prompt` is actually `settings.brief_max_prompt_detections`
    # read at call time, not a hardcoded `50`. If `prompt.py` were changed to `cap = 50`,
    # this test would still see all 6 detections serialized and FAIL the `== 3` assertions
    # below, whereas `test_truncation_keeps_50_largest_and_reports_true_totals` would keep
    # passing either way (it never varies the cap).
    #
    # `prompt.py` does `from overwatch.config import settings` then reads
    # `settings.brief_max_prompt_detections` at call time — that import binds the name
    # `settings` in `overwatch.briefs.prompt`'s namespace to the SAME `Settings` instance
    # held by `overwatch.config.settings` (not a copy), so patching the attribute on the
    # module-qualified object mutates the one instance both modules see.
    from overwatch.briefs import prompt as prompt_module

    monkeypatch.setattr(prompt_module.settings, "brief_max_prompt_detections", 3)

    # Non-monotonic areas: neither ascending nor descending in detection-id order, so a
    # naive "keep the first N" truncation (or the cap not applying at all) would produce a
    # different survivor set than "keep the 3 largest by area".
    areas = [400.0, 100.0, 600.0, 200.0, 500.0, 300.0]
    detections = [_detection(i + 1, "new_structure", area) for i, area in enumerate(areas)]
    request = _request(detections)

    messages = build_messages(request, [])
    content = messages[0]["content"]

    sorted_desc = sorted(detections, key=lambda d: d.area_m2, reverse=True)
    included, excluded = sorted_desc[:3], sorted_desc[3:]
    assert len(included) == 3
    assert len(excluded) == 3
    for d in included:
        assert f"id={d.id} type=" in content
    for d in excluded:
        assert f"id={d.id} type=" not in content


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


# --- Phase 5: the SOURCES block ----------------------------------------------------


def _user_turn(request: BriefRequest) -> str:
    """The first-turn user message — the whole prompt body the model reads."""
    return build_messages(request, [])[0]["content"]


def _article(id_: int = 99) -> ArticleRow:
    # The real Novo Progresso corpus article (design §4.4), same row the Gate-4
    # validator tests use — so prompt and validator are exercised against one story.
    return ArticleRow(
        id=id_,
        title="Brazilian authorities launch probe into Amazon largest single deforester",
        domain="news.mongabay.com",
        seendate=date(2023, 8, 11),
    )


def _request_with_articles() -> BriefRequest:
    request = _request([_detection(1, "vegetation_loss", 50_000.0)])
    request.articles = [_article()]
    return request


def test_system_prompt_declares_all_four_claim_types() -> None:
    # Phase 5 legalizes `reported` and `mixed` (validator._SUPPORTED_CLAIM_TYPES). If the
    # system prompt still said "use only observed and context" while the SOURCES block
    # below demanded `reported`, the prompt would contradict itself and the model would be
    # steered straight into a Gate-4 rejection.
    assert '"reported"' in SYSTEM_PROMPT
    assert '"mixed"' in SYSTEM_PROMPT
    assert 'Use only claim types "observed" and "context"' not in SYSTEM_PROMPT


def test_prompt_renders_articles_with_ids_and_the_reported_speech_rule() -> None:
    content = _user_turn(_request_with_articles())

    assert "SOURCES" in content
    assert "[99]" in content
    assert "news.mongabay.com" in content
    assert "2023-08-11" in content
    assert "Brazilian authorities launch probe" in content

    # The rules the model must obey have to be IN the prompt, not just in the validator.
    assert "reported" in content.lower()
    assert "may not" in content.lower() or "never" in content.lower()
    assert "article_evidence" in content
    assert "mixed" in content.lower()


def test_prompt_omits_the_sources_section_when_there_are_no_articles() -> None:
    request = _request_with_articles()
    request.articles = []
    content = _user_turn(request)

    assert "SOURCES" not in content
    # No sources => no article ids to cite => the source rules would be noise at best and
    # an invitation to invent citations at worst.
    assert "article_evidence" not in content


def test_articles_are_capped_at_the_configured_limit_and_truncation_is_logged(caplog) -> None:
    request = _request_with_articles()
    request.articles = [
        ArticleRow(
            id=i,
            title=f"Amazon deforestation report {i}",
            domain="d.com",
            seendate=date(2023, 8, 11),
        )
        for i in range(50)
    ]

    assert settings.fusion_max_prompt_articles == 10

    with caplog.at_level(logging.INFO, logger="overwatch.briefs.prompt"):
        content = _user_turn(request)

    # `articles_for_pair` returns chronological order and news_articles stores no score,
    # so the cap keeps the EARLIEST 10 — ids 0..9 in, 10..49 out. The bracketed form is
    # collision-safe: "[1]" is not a substring of "[10]".
    for i in range(10):
        assert f"[{i}]" in content
    for i in range(10, 50):
        assert f"[{i}]" not in content

    assert "mongabay.com" not in content  # the seed article was replaced outright
    assert "truncat" in caplog.text.lower()
    assert "50" in caplog.text and "10" in caplog.text


def test_article_cap_is_read_from_settings_not_hardcoded(monkeypatch) -> None:
    # Same guard as `test_truncation_cap_is_read_from_settings_not_hardcoded` does for
    # detections: if the cap were written as a literal `10`, the test above would still
    # pass and this one would fail.
    from overwatch.briefs import prompt as prompt_module

    monkeypatch.setattr(prompt_module.settings, "fusion_max_prompt_articles", 2)

    request = _request_with_articles()
    request.articles = [_article(id_=i) for i in range(5)]

    content = _user_turn(request)

    for i in range(2):
        assert f"[{i}]" in content
    for i in range(2, 5):
        assert f"[{i}]" not in content
