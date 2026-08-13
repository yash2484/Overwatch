"""GDELT DOC 2.0 provider (Phase 5 design §6). CI never touches the network.

Every fixture here is a VERBATIM response captured during the 2026-07-12 spike, including
the two failure bodies that would crash a naive client:
  * a 429 whose body is PLAINTEXT, not JSON
  * a 200 whose body is ALSO plaintext (the "keywords too short/long/common" error)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from overwatch.config import settings
from overwatch.fusion import provider as provider_module
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.provider import (
    FakeNewsProvider,
    GdeltDocProvider,
    TransientFusionError,
    build_query,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"
START = datetime(2024, 6, 15, tzinfo=UTC)
END = datetime(2024, 8, 15, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _cold_throttle_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the process-wide rate-limit clock before every test in this module.

    The throttle is deliberately class-level (GDELT limits per IP, so the limiter must be per
    process, not per object) — which means its state leaks from one test into the next. These
    tests drive a MockTransport and never touch the network, so an inherited hot clock would
    make each of them sleep out a real 6-second interval for nothing: the suite went from 11 s
    to 58 s before this fixture existed.
    """
    monkeypatch.setattr(GdeltDocProvider, "_last_call", float("-inf"))


def _provider_with(handler) -> GdeltDocProvider:
    return GdeltDocProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_build_query_is_conjunctive_strict_place_AND_themes() -> None:
    q = build_query("Vizhinjam", FUSION_PRESETS["port"])
    assert q.startswith('"Vizhinjam" (')
    assert "theme:MARITIME" in q
    assert " OR " in q  # themes are OR-ed INSIDE the AND-ed group


def test_build_query_quotes_multiword_place_terms() -> None:
    q = build_query("Novo Progresso", FUSION_PRESETS["forest"])
    assert '"Novo Progresso"' in q
    assert "theme:ENV_DEFORESTATION" in q


def test_parses_a_real_artlist_response() -> None:
    body = (FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    articles = provider.search("q", START, END)
    assert len(articles) == 4
    first = articles[0]
    assert first.domain == "thehindu.com"
    assert first.language == "English"
    assert first.title == "Customs grants approval to Vizhinjam International Seaport"
    # seendate must parse from GDELT's COMPACT stamp, not ISO-8601.
    assert first.seendate == datetime(2024, 6, 15, 17, 0, tzinfo=UTC)


def test_the_provider_does_not_filter_it_returns_everything() -> None:
    """Retrieval and gating are separate layers. The Malayalam article must survive the
    provider and be rejected later, by the pure scorer — not silently dropped here."""
    body = (FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    languages = {a.language for a in provider.search("q", START, END)}
    assert "Malayalam" in languages


def test_429_plaintext_body_raises_transient_and_never_json_decodes() -> None:
    body = (FIXTURES / "rate_limited.txt").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(429, text=body))
    with pytest.raises(TransientFusionError, match="rate limited"):
        provider.search("q", START, END)


def test_200_with_plaintext_keyword_error_returns_empty_not_a_crash() -> None:
    body = (FIXTURES / "keyword_error.txt").read_text(encoding="utf-8")
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    assert provider.search("q", START, END) == []


def test_empty_200_body_returns_empty() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, text=""))
    assert provider.search("q", START, END) == []


def test_5xx_raises_transient_so_celery_retries() -> None:
    provider = _provider_with(lambda req: httpx.Response(503, text="upstream down"))
    with pytest.raises(TransientFusionError):
        provider.search("q", START, END)


def test_network_error_raises_transient() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    with pytest.raises(TransientFusionError):
        _provider_with(boom).search("q", START, END)


def test_malformed_row_is_skipped_not_fatal() -> None:
    body = json.dumps(
        {
            "articles": [
                {"url": "https://a.com/1", "title": "no seendate here", "domain": "a.com"},
                {
                    "url": "https://b.com/2",
                    "title": "Good row",
                    "seendate": "20240615T170000Z",
                    "domain": "b.com",
                    "language": "English",
                },
            ]
        }
    )
    provider = _provider_with(lambda req: httpx.Response(200, text=body))
    articles = provider.search("q", START, END)
    assert [a.title for a in articles] == ["Good row"]


def test_request_carries_the_gdelt_timestamp_format() -> None:
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, text='{"articles": []}')

    _provider_with(capture).search("q", START, END)
    assert seen["startdatetime"] == "20240615000000"  # not ISO, not epoch
    assert seen["enddatetime"] == "20240815000000"
    assert seen["mode"] == "artlist"
    assert seen["format"] == "json"


def test_fake_provider_replays_fixtures_offline() -> None:
    body = json.loads((FIXTURES / "vizhinjam_2024.json").read_text(encoding="utf-8"))
    provider = FakeNewsProvider.from_artlist(body)
    assert len(provider.search("anything", START, END)) == 4


# --- the throttle ------------------------------------------------------------------


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"articles": []})


def test_throttle_is_process_wide_not_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """GDELT rate-limits per IP, so the limiter must be per PROCESS — not per object.

    `get_news_provider()` builds a fresh `GdeltDocProvider` on every task run, and Celery
    re-runs the whole task body on every retry. With the throttle clock stored per instance,
    each retry starts from a zeroed clock, computes a negative wait, and sleeps for nothing —
    so the throttle never fires and the retries hammer GDELT inside its own 5-second limit.

    That is not hypothetical: the first live run (2026-07-13) issued three requests in 28
    seconds and took a 429 on every one of them.
    """
    slept: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", lambda s: slept.append(s))
    # Reset the shared clock to cold. monkeypatch restores it afterwards, so tests stay
    # isolated from each other despite the state being process-wide by design.
    monkeypatch.setattr(GdeltDocProvider, "_last_call", float("-inf"))

    _provider_with(_ok).search("q", START, END)
    assert slept == []  # the first call of the process has nothing to wait for

    # A brand-new instance — exactly what `get_news_provider()` hands the next task attempt.
    _provider_with(_ok).search("q", START, END)

    assert slept, (
        "a fresh provider instance ignored the throttle: every Celery retry would hit "
        "GDELT immediately, inside its 5-second limit"
    )
    assert slept[0] >= settings.gdelt_min_interval_s - 0.5


def test_throttle_does_not_stall_a_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # The floor must not become a tax: with the clock cold, the first call goes straight out.
    slept: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(GdeltDocProvider, "_last_call", float("-inf"))

    _provider_with(_ok).search("q", START, END)

    assert slept == []
