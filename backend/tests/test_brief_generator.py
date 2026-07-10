"""Tests for overwatch.briefs.generator — Fake and Anthropic BriefGenerator implementations.

The Anthropic tests inject a stand-in `overwatch.briefs.prompt` module into `sys.modules`
before calling `generate()`, so they exercise `AnthropicBriefGenerator`'s lazy import without
depending on the real prompt module (built by a parallel lane) or the network. The SDK client
itself is a MagicMock shaped like the real response object — no network calls, ever.
"""

import sys
import types
from datetime import date
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from overwatch.briefs.generator import (
    FAKE_INPUT_TOKENS,
    FAKE_OUTPUT_TOKENS,
    AnthropicBriefGenerator,
    FakeBriefGenerator,
    PermanentBriefError,
    TransientBriefError,
)
from overwatch.briefs.models import AttemptFailure, BriefDraft, BriefRequest, ClaimDraft, Violation

_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


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


@pytest.fixture(autouse=True)
def _stub_prompt_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Install a fake overwatch.briefs.prompt in sys.modules so the lazy import in
    AnthropicBriefGenerator.generate() resolves without touching the real module or disk.
    """
    fake_module = types.ModuleType("overwatch.briefs.prompt")
    fake_module.SYSTEM_PROMPT = "SYSTEM PROMPT"
    fake_module.build_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])
    monkeypatch.setitem(sys.modules, "overwatch.briefs.prompt", fake_module)
    return fake_module


def _mock_client(resp: MagicMock | None = None, side_effect: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.messages.parse.side_effect = side_effect
    else:
        client.messages.parse.return_value = resp
    return client


# ---------------------------------------------------------------------------
# FakeBriefGenerator
# ---------------------------------------------------------------------------


def test_fake_generator_returns_drafts_in_order() -> None:
    drafts = [_draft("A"), _draft("B")]
    gen = FakeBriefGenerator(drafts)

    first = gen.generate(_req(), [])
    second = gen.generate(_req(), [])

    assert first.draft is drafts[0]
    assert second.draft is drafts[1]


def test_fake_generator_raises_assertion_error_when_exhausted() -> None:
    gen = FakeBriefGenerator([_draft("A")])
    gen.generate(_req(), [])
    with pytest.raises(AssertionError):
        gen.generate(_req(), [])


def test_fake_generator_records_calls_feedback_history() -> None:
    gen = FakeBriefGenerator([_draft("A"), _draft("B")])
    failures = [AttemptFailure(draft=_draft("A"), violations=[Violation(code="x", message="m")])]

    gen.generate(_req(), [])
    gen.generate(_req(), failures)

    assert gen.calls == [[], failures]


def test_fake_generator_usage_is_constant_and_model_overridable() -> None:
    gen = FakeBriefGenerator([_draft("A")], model="fake-model")
    result = gen.generate(_req(), [])

    assert result.model == "fake-model"
    assert result.usage == {"input_tokens": FAKE_INPUT_TOKENS, "output_tokens": FAKE_OUTPUT_TOKENS}


def test_fake_generator_default_model_is_fake() -> None:
    gen = FakeBriefGenerator([_draft("A")])
    result = gen.generate(_req(), [])
    assert result.model == "fake"


# ---------------------------------------------------------------------------
# AnthropicBriefGenerator
# ---------------------------------------------------------------------------


def test_anthropic_generator_returns_generation_on_success() -> None:
    draft = _draft("A")
    resp = MagicMock()
    resp.parsed_output = draft
    resp.stop_reason = "end_turn"
    resp.model = "claude-opus-4-8"
    resp.usage.input_tokens = 111
    resp.usage.output_tokens = 22

    gen = AnthropicBriefGenerator(client=_mock_client(resp=resp), model="claude-opus-4-8")
    result = gen.generate(_req(), [])

    assert result.draft is draft
    assert result.model == "claude-opus-4-8"
    assert result.usage == {"input_tokens": 111, "output_tokens": 22}


def test_anthropic_generator_refusal_is_permanent() -> None:
    resp = MagicMock()
    resp.stop_reason = "refusal"
    resp.parsed_output = None

    gen = AnthropicBriefGenerator(client=_mock_client(resp=resp), model="claude-opus-4-8")

    with pytest.raises(PermanentBriefError) as exc_info:
        gen.generate(_req(), [])
    assert exc_info.value.code == "brief_refused"


def test_anthropic_generator_none_parsed_output_is_permanent() -> None:
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.parsed_output = None

    gen = AnthropicBriefGenerator(client=_mock_client(resp=resp), model="claude-opus-4-8")

    with pytest.raises(PermanentBriefError) as exc_info:
        gen.generate(_req(), [])
    assert exc_info.value.code == "brief_parse_failed"


def test_anthropic_generator_rate_limit_is_transient() -> None:
    err = anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=_REQ), body=None
    )
    gen = AnthropicBriefGenerator(client=_mock_client(side_effect=err), model="claude-opus-4-8")

    with pytest.raises(TransientBriefError):
        gen.generate(_req(), [])


def test_anthropic_generator_connection_error_is_transient() -> None:
    err = anthropic.APIConnectionError(request=_REQ)
    gen = AnthropicBriefGenerator(client=_mock_client(side_effect=err), model="claude-opus-4-8")

    with pytest.raises(TransientBriefError):
        gen.generate(_req(), [])


def test_anthropic_generator_5xx_status_is_transient() -> None:
    err = anthropic.APIStatusError(
        "server error", response=httpx.Response(503, request=_REQ), body=None
    )
    gen = AnthropicBriefGenerator(client=_mock_client(side_effect=err), model="claude-opus-4-8")

    with pytest.raises(TransientBriefError):
        gen.generate(_req(), [])


def test_anthropic_generator_4xx_status_is_permanent_bad_request() -> None:
    err = anthropic.APIStatusError(
        "bad request", response=httpx.Response(400, request=_REQ), body=None
    )
    gen = AnthropicBriefGenerator(client=_mock_client(side_effect=err), model="claude-opus-4-8")

    with pytest.raises(PermanentBriefError) as exc_info:
        gen.generate(_req(), [])
    assert exc_info.value.code == "anthropic_bad_request"


def test_anthropic_generator_authentication_error_is_permanent() -> None:
    err = anthropic.AuthenticationError(
        "bad key", response=httpx.Response(401, request=_REQ), body=None
    )
    gen = AnthropicBriefGenerator(client=_mock_client(side_effect=err), model="claude-opus-4-8")

    with pytest.raises(PermanentBriefError) as exc_info:
        gen.generate(_req(), [])
    assert exc_info.value.code == "anthropic_auth"


def test_anthropic_generator_calls_build_messages_with_request_and_failures(
    _stub_prompt_module: types.ModuleType,
) -> None:
    resp = MagicMock()
    resp.parsed_output = _draft("A")
    resp.stop_reason = "end_turn"
    resp.model = "claude-opus-4-8"
    resp.usage.input_tokens = 1
    resp.usage.output_tokens = 1

    gen = AnthropicBriefGenerator(client=_mock_client(resp=resp), model="claude-opus-4-8")
    request = _req()
    failures = [AttemptFailure(draft=_draft("A"), violations=[Violation(code="x", message="m")])]

    gen.generate(request, failures)

    _stub_prompt_module.build_messages.assert_called_once_with(request, failures)
