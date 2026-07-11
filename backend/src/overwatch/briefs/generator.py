"""BriefGenerator implementations: Anthropic (real) and Fake (deterministic, for tests).

Both implementations turn a `BriefRequest` plus the accumulated `AttemptFailure` history from
prior loop attempts into a `BriefGeneration` (see `overwatch.briefs.loop.run_brief_loop`, which
threads that history back in on each retry).

No I/O happens at import time: `AnthropicBriefGenerator` builds its default client lazily in
`__init__` (only when no client is injected), and imports `overwatch.briefs.prompt` — built by a
parallel lane — lazily inside `generate()`, so this module (and Fake-only tests) stay usable
before that module exists and without ever touching the network in CI.
"""

from typing import Protocol

import anthropic

from overwatch.briefs.models import AttemptFailure, BriefDraft, BriefGeneration, BriefRequest
from overwatch.config import settings

FAKE_INPUT_TOKENS = 100
FAKE_OUTPUT_TOKENS = 50


class BriefGenerator(Protocol):
    def generate(
        self, request: BriefRequest, failures: list[AttemptFailure]
    ) -> BriefGeneration: ...


class FakeBriefGenerator:
    """Deterministic generator for tests: returns pre-built drafts in call order.

    Records every call's feedback in `.calls` so loop tests can assert what each attempt saw.
    Raises `AssertionError` if `generate` is called more times than drafts were supplied.
    """

    def __init__(self, drafts: list[BriefDraft], model: str = "fake") -> None:
        self._drafts = list(drafts)
        self._model = model
        self._next_index = 0
        self.calls: list[list[AttemptFailure]] = []

    def generate(self, request: BriefRequest, failures: list[AttemptFailure]) -> BriefGeneration:
        self.calls.append(failures)
        assert self._next_index < len(self._drafts), "FakeBriefGenerator: drafts exhausted"
        draft = self._drafts[self._next_index]
        self._next_index += 1
        return BriefGeneration(
            draft=draft,
            model=self._model,
            usage={"input_tokens": FAKE_INPUT_TOKENS, "output_tokens": FAKE_OUTPUT_TOKENS},
        )


class TransientBriefError(Exception):
    """Retryable generation failure (rate limit, connection error, 5xx from the API)."""


class PermanentBriefError(Exception):
    """Non-retryable generation failure — the loop should stop, not re-prompt."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AnthropicBriefGenerator:
    """Real generator backed by the Anthropic Messages API structured-output mode."""

    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None) -> None:
        self._client = (
            client
            if client is not None
            else anthropic.Anthropic(api_key=settings.anthropic_api_key)
        )
        self._model = model if model is not None else settings.anthropic_model

    def generate(self, request: BriefRequest, failures: list[AttemptFailure]) -> BriefGeneration:
        from overwatch.briefs.prompt import SYSTEM_PROMPT, build_messages  # lazy: lane isolation

        try:
            resp = self._client.messages.parse(
                model=self._model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=build_messages(request, failures),
                output_format=BriefDraft,
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            raise TransientBriefError(str(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise PermanentBriefError("anthropic_auth", str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientBriefError(str(exc)) from exc
            raise PermanentBriefError("anthropic_bad_request", str(exc)) from exc
        if resp.stop_reason == "refusal":
            raise PermanentBriefError("brief_refused", "model refused the request")
        if resp.parsed_output is None:
            raise PermanentBriefError("brief_parse_failed", "no parseable structured output")
        return BriefGeneration(
            draft=resp.parsed_output,
            model=resp.model,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )
