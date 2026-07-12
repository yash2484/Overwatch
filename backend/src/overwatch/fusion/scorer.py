"""The three-gate AND relevance scorer (Phase 5 design §4.2). Pure — no I/O, no DB.

**Gate 1 is the TOPONYM gate, NOT a spatial one.** GDELT exposes no article geotag
(design §2.2), and the GKG/GGG geofence was measured and rejects 100% of our true
positives — its geocoder is centroid-based by GDELT's own documentation (§2.4b). Do not
rename this "spatial", and do not add a geometry check here.

Two-layer conjunction (design §4.1) — both layers are AND-shaped, neither is trusted alone:

  1. RETRIEVAL (provider): GDELT enforces the STRICT place term against the article's
     FULL TEXT — strictly more information than we can see.
  2. SCORING (here): corroborates against the only text a DOC record exposes, the TITLE,
     using a GENEROUS term list that includes regional names. This is required because
     titles routinely omit the specific place: zero of six Porto Alegre articles and
     zero of four Novo Progresso articles name their AOI in the title (§2.5).

An article only reaches this scorer if it already passed the strict full-text term, so a
generous "Amazon" in the corroboration list cannot admit a Rondônia-only story — that
story would never have been retrieved.
"""

import re

from overwatch.fusion.models import FusionWindow, GateResult, RawArticle
from overwatch.fusion.normalize import (
    WHITESPACE_RE,
    match_stems,
    match_terms,
    normalize,
)
from overwatch.fusion.presets import FusionPreset

_PUNCT_RE = re.compile(r"[^0-9a-z ]+")


def score_article(
    article: RawArticle,
    *,
    place_terms: list[str],
    region_terms: list[str],
    window: FusionWindow,
    preset: FusionPreset,
    languages: list[str],
) -> GateResult:
    """All gates must pass (AND). The first failure short-circuits and is recorded."""
    # --- Preconditions (cheap rejects before the gates) ---
    # Language comes from the record's OWN field, never GDELT's unverified `sourcelang:`
    # operator (design decision 7).
    if article.language not in languages:
        return GateResult(passed=False, reason="language")

    if not article.url.startswith(("http://", "https://")):
        return GateResult(passed=False, reason="url")

    # --- Gate 1: TOPONYM (whole-word, over place ∪ region terms) ---
    toponym = match_terms(article.title, [*place_terms, *region_terms])
    if not toponym:
        return GateResult(passed=False, reason="toponym")

    # --- Gate 2: TEMPORAL (inclusive; anchored on the AFTER scene) ---
    if not (window.start <= article.seendate <= window.end):
        return GateResult(passed=False, toponym=toponym, reason="temporal")

    # --- Gate 3: THEMATIC (stem match, so "deforest" fires on "deforester") ---
    thematic = match_stems(article.title, preset.keywords)
    if not thematic:
        return GateResult(passed=False, toponym=toponym, temporal=True, reason="thematic")

    return GateResult(passed=True, toponym=toponym, temporal=True, thematic=thematic)


def _title_key(title: str) -> str:
    """Collapse a title to a comparison key: normalized, punctuation-free, single-spaced.

    "Brazil Rio Grande Do Sul May Have More Record Level Flooding" (usnews) and its
    lowercase yahoo syndication collapse to the same key.
    """
    return WHITESPACE_RE.sub(" ", _PUNCT_RE.sub(" ", normalize(title))).strip()


def dedupe(
    articles: list[RawArticle], *, domain_rank: list[str]
) -> list[tuple[RawArticle, list[str]]]:
    """Collapse syndicated copies. Returns (survivor, suppressed_urls) per story.

    Two of the six real Porto Alegre results are the same Reuters wire carried by
    usnews.com and yahoo.com (design §2.5). Without this, syndication inflates the
    citation count and one story masquerades as corroboration.

    Winner: highest-ranked domain; ties (and unranked domains) break on earliest seendate.
    Suppressed URLs are RETURNED, not discarded, so the dedup lands in the persisted row's
    meta and stays visible rather than silent (design §4.3).
    """
    groups: dict[str, list[RawArticle]] = {}
    for article in articles:
        groups.setdefault(_title_key(article.title), []).append(article)

    def rank(article: RawArticle) -> tuple[int, float]:
        try:
            domain_score = domain_rank.index(article.domain)
        except ValueError:
            domain_score = len(domain_rank)  # unranked sorts last
        return (domain_score, article.seendate.timestamp())

    out: list[tuple[RawArticle, list[str]]] = []
    for group in groups.values():
        winner, *losers = sorted(group, key=rank)
        out.append((winner, [a.url for a in losers]))
    return out
