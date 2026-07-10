"""Bounded generate-validate-retry loop for LLM-generated intelligence briefs.

`run_brief_loop` drives a `BriefGenerator`: generate a draft, validate it, and on failure
re-prompt with the accumulated violation history, up to `max_attempts` times. It does not
catch `TransientBriefError`/`PermanentBriefError` raised by the generator — those are a
generator-transport concern (retry/backoff, auth failure) handled by the caller, not the
draft/validate feedback loop itself.
"""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from overwatch.briefs.generator import BriefGenerator
from overwatch.briefs.models import AttemptFailure, BriefDraft, BriefRequest, Violation


class LoopResult(BaseModel):
    status: Literal["validated", "rejected"]
    draft: BriefDraft | None
    failures: list[AttemptFailure]
    attempts: int
    model: str | None
    usage: dict[str, int]  # summed across attempts


def run_brief_loop(
    generator: BriefGenerator,
    request: BriefRequest,
    *,
    validate: Callable[[BriefDraft, BriefRequest], list[Violation]],
    max_attempts: int,
) -> LoopResult:
    failures: list[AttemptFailure] = []
    usage_totals: dict[str, int] = {}
    model: str | None = None

    for attempt in range(1, max_attempts + 1):
        # Pass a snapshot, not the live accumulator: FakeBriefGenerator (and any real
        # generator that logs/stores its input) must see what this attempt received, not
        # a reference that keeps growing as later attempts append to it.
        generation = generator.generate(request, list(failures))
        model = generation.model
        for key, value in generation.usage.items():
            usage_totals[key] = usage_totals.get(key, 0) + value

        violations = validate(generation.draft, request)
        if not violations:
            return LoopResult(
                status="validated",
                draft=generation.draft,
                failures=failures,
                attempts=attempt,
                model=model,
                usage=usage_totals,
            )

        failures.append(AttemptFailure(draft=generation.draft, violations=violations))

    return LoopResult(
        status="rejected",
        draft=None,
        failures=failures,
        attempts=max_attempts,
        model=model,
        usage=usage_totals,
    )
