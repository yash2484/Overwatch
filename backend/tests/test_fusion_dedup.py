"""Syndication dedup (Phase 5 design §4.3).

Two of the six real Porto Alegre spike results are the SAME Reuters wire story, carried by
usnews.com and yahoo.com. Without dedup, syndication inflates the citation count and one
story masquerades as corroboration.
"""

from datetime import UTC, datetime

from overwatch.fusion.models import RawArticle
from overwatch.fusion.scorer import dedupe

RANK = ["reuters.com", "usnews.com", "yahoo.com"]


def art(title: str, domain: str, day: int) -> RawArticle:
    return RawArticle(
        url=f"https://{domain}/{day}",
        title=title,
        domain=domain,
        language="English",
        seendate=datetime(2024, 5, day, tzinfo=UTC),
    )


def test_syndicated_wire_story_collapses_to_one_survivor() -> None:
    # The REAL case from the spike: usnews + yahoo carrying the same Reuters piece,
    # differing only in capitalisation.
    a = art("Brazil Rio Grande Do Sul May Have More Record Level Flooding", "usnews.com", 12)
    b = art("Brazil Rio Grande do Sul may have more record level flooding", "yahoo.com", 12)
    survivors = dedupe([a, b], domain_rank=RANK)
    assert len(survivors) == 1
    survivor, suppressed = survivors[0]
    assert survivor.domain == "usnews.com"  # ranks above yahoo
    assert suppressed == ["https://yahoo.com/12"]


def test_dedup_is_punctuation_insensitive() -> None:
    a = art("Major Amazon deforester arrested : 6 , 500 hectares cleared", "a.com", 4)
    b = art("Major Amazon deforester arrested: 6,500 hectares cleared", "b.com", 4)
    assert len(dedupe([a, b], domain_rank=RANK)) == 1


def test_distinct_stories_are_both_kept() -> None:
    a = art("Amazon deforestation falls 66% in July", "a.com", 5)
    b = art("Brazilian authorities launch probe into Amazon deforester", "b.com", 11)
    assert len(dedupe([a, b], domain_rank=RANK)) == 2


def test_unranked_domains_tiebreak_on_earliest_seendate() -> None:
    a = art("Same headline", "unknown-a.com", 20)
    b = art("Same headline", "unknown-b.com", 12)
    survivor, suppressed = dedupe([a, b], domain_rank=RANK)[0]
    assert survivor.domain == "unknown-b.com"  # earlier seendate wins
    assert suppressed == ["https://unknown-a.com/20"]


def test_a_ranked_domain_beats_an_unranked_one_even_if_later() -> None:
    ranked = art("Same headline", "reuters.com", 20)
    unranked = art("Same headline", "aggregator.example", 12)
    survivor, _ = dedupe([unranked, ranked], domain_rank=RANK)[0]
    assert survivor.domain == "reuters.com"


def test_suppressed_urls_are_returned_not_silently_dropped() -> None:
    # The dedup must be VISIBLE in the persisted row's meta, never silent.
    a = art("Same headline", "usnews.com", 12)
    b = art("Same headline", "yahoo.com", 13)
    c = art("Same headline", "other.example", 14)
    _survivor, suppressed = dedupe([a, b, c], domain_rank=RANK)[0]
    assert sorted(suppressed) == ["https://other.example/14", "https://yahoo.com/13"]


def test_empty_input_is_empty_output() -> None:
    assert dedupe([], domain_rank=RANK) == []


def test_single_article_survives_with_no_suppressions() -> None:
    survivor, suppressed = dedupe([art("Solo story", "a.com", 1)], domain_rank=RANK)[0]
    assert survivor.domain == "a.com"
    assert suppressed == []
