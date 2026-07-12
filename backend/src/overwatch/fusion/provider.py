"""GDELT DOC 2.0 retrieval (Phase 5 design §6). The ONLY I/O in the fusion path.

Hard-won facts from the 2026-07-12 spike. Do NOT "simplify" these away:

  * **GEO 2.0 is a 404** on every documented form, and returns no coordinates anyway.
    DOC 2.0 is the only usable surface (design §2.1). Never point `gdelt_api_url` at /geo/.
  * **A 429 body is PLAINTEXT, not JSON.** `response.json()` on it raises. (§2.6)
  * **A 200 can ALSO carry a plaintext error** — "One or more of your keywords were too
    short, too long or too common". That is a legitimate empty result, not an exception.
  * >=5 s between requests is GDELT's documented ask; we default to 6 s and still saw
    429s after bursts. The throttle is not optional.

This module RETRIEVES. It does not gate: every article it returns — including non-English
ones — is handed to the pure scorer, which decides. Keeping the two apart is what makes
the gating unit-testable without a network.
"""

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from overwatch.config import settings
from overwatch.fusion.models import RawArticle
from overwatch.fusion.presets import FusionPreset

logger = logging.getLogger(__name__)

_GDELT_TS = "%Y%m%d%H%M%S"
_GDELT_SEENDATE = "%Y%m%dT%H%M%SZ"


class TransientFusionError(Exception):
    """Rate limit / 5xx / network. Safe to retry with backoff (Celery autoretries)."""


class NewsProvider(Protocol):
    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]: ...


def build_query(place_term: str, preset: FusionPreset) -> str:
    """Conjunctive: the STRICT place term AND any of the vertical's themes.

    GDELT matches the quoted term against the article's FULL TEXT — strictly more than the
    title our scorer can see (design §4.1). This is layer one of the two-layer conjunction;
    the pure scorer is layer two. It is why a generous "Amazon" in the corroboration list
    cannot admit a Rondonia-only story: that story is never retrieved in the first place.
    """
    themes = " OR ".join(f"theme:{t}" for t in preset.themes)
    return f'"{place_term}" ({themes})'


def _parse_seendate(raw: str) -> datetime:
    """GDELT's compact stamp: '20240615T170000Z' — not ISO-8601."""
    return datetime.strptime(raw, _GDELT_SEENDATE).replace(tzinfo=UTC)


def _to_articles(payload: dict[str, Any]) -> list[RawArticle]:
    out: list[RawArticle] = []
    for row in payload.get("articles", []):
        try:
            out.append(
                RawArticle(
                    url=row["url"],
                    title=row["title"].strip(),
                    domain=row["domain"],
                    language=row["language"],
                    seendate=_parse_seendate(row["seendate"]),
                    socialimage=row.get("socialimage", ""),
                    sourcecountry=row.get("sourcecountry", ""),
                )
            )
        except (KeyError, ValueError) as exc:
            # One malformed row must not lose the whole response.
            logger.warning("skipping malformed GDELT row: %s", exc)
    return out


class GdeltDocProvider:
    """The real provider. Throttled, and defensive about GDELT's non-JSON responses."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            wait = settings.gdelt_min_interval_s - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]:
        self._throttle()
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": settings.gdelt_max_records,
            "startdatetime": start.astimezone(UTC).strftime(_GDELT_TS),
            "enddatetime": end.astimezone(UTC).strftime(_GDELT_TS),
        }
        try:
            response = self._client.get(settings.gdelt_api_url, params=params)
        except httpx.HTTPError as exc:
            raise TransientFusionError(f"GDELT request failed: {exc}") from exc

        if response.status_code == 429:
            # The body here is PLAINTEXT. Do not parse it as JSON.
            raise TransientFusionError(f"GDELT rate limited: {response.text[:120]!r}")
        if response.status_code >= 500:
            raise TransientFusionError(f"GDELT {response.status_code}")
        if response.status_code != 200:
            logger.warning("GDELT %s: %s", response.status_code, response.text[:200])
            return []

        body = response.text.strip()
        if not body or not body.startswith("{"):
            # A 200 with a plaintext notice ("keywords were too short, too long or too
            # common") is a real GDELT response meaning "no results" — not an error.
            if body:
                logger.info("GDELT plaintext notice: %s", body[:200])
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning("GDELT returned undecodable JSON: %s", body[:200])
            return []
        return _to_articles(payload)


class FakeNewsProvider:
    """Replays recorded fixtures. CI never touches the network."""

    def __init__(self, articles: list[RawArticle]) -> None:
        self._articles = articles

    @classmethod
    def from_artlist(cls, payload: dict[str, Any]) -> "FakeNewsProvider":
        return cls(_to_articles(payload))

    def search(self, query: str, start: datetime, end: datetime) -> list[RawArticle]:
        return list(self._articles)
