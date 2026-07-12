"""The three-gate AND scorer (Phase 5 design §4.2), TDD'd against the REAL spiked corpus.

The titles below are verbatim from the 2026-07-12 GDELT spike — not invented. If this
suite passes, the gate design provably admits the articles the demo depends on and
rejects the ones it must.
"""

from datetime import UTC, datetime

import pytest

from overwatch.fusion.models import FusionWindow, RawArticle
from overwatch.fusion.presets import FUSION_PRESETS
from overwatch.fusion.scorer import score_article

# The REAL Novo Progresso window, derived from the REAL scene pair in Postgres
# (before 2023-07-30, after 2024-07-24) via FusionWindow.around. Do not hand-invent this:
# an after-scene-anchored band looked fine on paper and returned zero live articles.
FOREST_WINDOW = FusionWindow.around(
    datetime(2023, 7, 30, tzinfo=UTC),
    datetime(2024, 7, 24, tzinfo=UTC),
    FUSION_PRESETS["forest"],
)  # -> 2023-06-30 .. 2024-08-07
FOREST_PLACE = ["Novo Progresso"]
FOREST_REGION = ["Amazon", "Amazonia", "Amazônia", "Para", "Pará", "BR-163"]


def article(
    title: str,
    *,
    seendate: datetime,
    language: str = "English",
    domain: str = "example.com",
    url: str | None = None,
) -> RawArticle:
    return RawArticle(
        url=url if url is not None else f"https://{domain}/a",
        title=title,
        domain=domain,
        language=language,
        seendate=seendate,
    )


def score_forest(art: RawArticle):
    return score_article(
        art,
        place_terms=FOREST_PLACE,
        region_terms=FOREST_REGION,
        window=FOREST_WINDOW,
        preset=FUSION_PRESETS["forest"],
        languages=["English"],
    )


# --- The real demo corpus (design §4.4) --------------------------------------------


def test_mongabay_deforester_article_passes() -> None:
    result = score_forest(
        article(
            "Brazilian authorities launch probe into Amazon largest single deforester",
            seendate=datetime(2023, 8, 11, 1, 30, tzinfo=UTC),
        )
    )
    assert result.passed
    # NOT "Novo Progresso" — the title never says it. This is the whole reason the
    # corroboration list is generous while retrieval stays strict.
    assert result.toponym == ["Amazon"]
    assert result.thematic == ["deforest"]  # the stem fires on "deforester"


def test_rio_times_hectares_cleared_article_passes() -> None:
    result = score_forest(
        article(
            "Major Amazon deforester arrested in Brazil : 6 , 500 hectares cleared",
            seendate=datetime(2023, 8, 4, 14, 45, tzinfo=UTC),
        )
    )
    assert result.passed


def test_deforestation_falls_article_passes() -> None:
    result = score_forest(
        article(
            "Brazil records 66 % drop in Amazon deforestation in July",
            seendate=datetime(2023, 8, 5, 7, 30, tzinfo=UTC),
        )
    )
    assert result.passed


def test_carrefour_cattle_article_is_rejected_no_thematic_keyword() -> None:
    # A REAL article, correctly rejected: "devastator"/"cattle" are not in the allowlist.
    # Conservative by construction — better to cite nothing than cite garbage.
    result = score_forest(
        article(
            "How the Amazon greatest devastator sold cattle to a Carrefour supplier",
            seendate=datetime(2023, 8, 29, tzinfo=UTC),
        )
    )
    assert not result.passed
    assert result.reason == "thematic"


# --- Adversarial negatives (design §4.4) -------------------------------------------


def test_amazon_prime_day_is_rejected_this_is_why_the_AND_matters() -> None:
    """The money shot: the toponym gate FIRES on 'Amazon', and the AND still kills it."""
    result = score_forest(
        article("Amazon Prime Day deals announced", seendate=datetime(2023, 8, 15, tzinfo=UTC))
    )
    assert not result.passed
    assert result.toponym == ["Amazon"]  # gate 1 passed!
    assert result.reason == "thematic"  # ...and gate 3 rejected it anyway


def test_off_place_article_is_rejected() -> None:
    result = score_forest(
        article("Severe deforestation hits Indonesia", seendate=datetime(2023, 8, 15, tzinfo=UTC))
    )
    assert not result.passed
    assert result.reason == "toponym"


def test_out_of_window_article_is_rejected() -> None:
    result = score_forest(
        article(
            "Amazon deforestation falls 66%",
            seendate=datetime(2025, 6, 1, tzinfo=UTC),  # ~10 months after the window closes
        )
    )
    assert not result.passed
    assert result.reason == "temporal"


def test_the_window_is_capped_not_unbounded() -> None:
    """An article from well before the observation interval is still rejected.

    The capped-interval window is wider than a 44-day band, but it is NOT the vacuous
    "whole before->after gap" the inherited spec implied.
    """
    result = score_forest(
        article("Amazon deforestation report", seendate=datetime(2021, 5, 1, tzinfo=UTC))
    )
    assert not result.passed
    assert result.reason == "temporal"


# --- Boundaries --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seendate", "expected"),
    [
        (datetime(2023, 6, 30, tzinfo=UTC), True),  # exactly ON window start — inclusive
        (datetime(2024, 8, 7, tzinfo=UTC), True),  # exactly ON window end — inclusive
        (datetime(2023, 6, 29, 23, 59, tzinfo=UTC), False),  # one minute early
        (datetime(2024, 8, 7, 0, 1, tzinfo=UTC), False),  # one minute late
    ],
)
def test_temporal_gate_boundaries_are_inclusive(seendate: datetime, expected: bool) -> None:
    result = score_forest(article("Amazon deforestation report", seendate=seendate))
    assert result.passed is expected


def test_non_english_is_rejected_by_the_language_precondition() -> None:
    # v0.1 gates on the record's OWN language field, not GDELT's unverified sourcelang:.
    result = score_forest(
        article(
            "Desmatamento na Amazônia cai",
            seendate=datetime(2023, 8, 15, tzinfo=UTC),
            language="Portuguese",
        )
    )
    assert not result.passed
    assert result.reason == "language"


def test_non_http_url_is_rejected() -> None:
    result = score_forest(
        article(
            "Amazon deforestation report",
            seendate=datetime(2023, 8, 15, tzinfo=UTC),
            url="ftp://sketchy/1",
        )
    )
    assert not result.passed
    assert result.reason == "url"


def test_gate_result_records_why_it_passed_for_audit() -> None:
    result = score_forest(
        article("Amazon deforestation falls 66% in July", seendate=datetime(2023, 8, 5, tzinfo=UTC))
    )
    assert result.passed
    assert result.toponym and result.thematic and result.temporal
    assert result.reason is None


# --- The other two verticals -------------------------------------------------------


# Real Vizhinjam pair from Postgres: 2021-02-12 -> 2025-02-11 (1460d, capped).
PORT_WINDOW = FusionWindow.around(
    datetime(2021, 2, 12, tzinfo=UTC),
    datetime(2025, 2, 11, tzinfo=UTC),
    FUSION_PRESETS["port"],
)  # -> 2023-12-08 .. 2025-02-25

# Real Porto Alegre pair from Phase 1: 2024-04-18 -> 2024-05-21 (33d).
FLOOD_WINDOW = FusionWindow.around(
    datetime(2024, 4, 18, tzinfo=UTC),
    datetime(2024, 5, 21, tzinfo=UTC),
    FUSION_PRESETS["flood"],
)  # -> 2024-03-19 .. 2024-06-04


def test_vizhinjam_port_articles_pass() -> None:
    for title, seen in [
        ("Customs grants approval to Vizhinjam International Seaport", datetime(2024, 6, 15)),
        (
            "Upcoming Vadhavan port may cast a shadow on Vizhinjam port prospects",
            datetime(2024, 6, 20),
        ),
        (
            "Vizhinjam beckons shipping lines as delay hit cargo handling at Colombo Port",
            datetime(2024, 7, 15),
        ),
    ]:
        result = score_article(
            article(title, seendate=seen.replace(tzinfo=UTC)),
            place_terms=["Vizhinjam"],
            region_terms=["Thiruvananthapuram", "Kerala"],
            window=PORT_WINDOW,
            preset=FUSION_PRESETS["port"],
            languages=["English"],
        )
        assert result.passed, f"expected pass: {title!r} (rejected by {result.reason})"


def test_porto_alegre_flood_article_passes_on_the_region_term() -> None:
    # ZERO of the six real Porto Alegre articles name the city in their title.
    result = score_article(
        article(
            "Brazil Rio Grande Do Sul May Have More Record Level Flooding",
            seendate=datetime(2024, 5, 12, 21, 45, tzinfo=UTC),
        ),
        place_terms=["Porto Alegre"],
        region_terms=["Rio Grande do Sul", "Guaiba", "Guaíba"],
        window=FLOOD_WINDOW,
        preset=FUSION_PRESETS["flood"],
        languages=["English"],
    )
    assert result.passed
    assert result.toponym == ["Rio Grande do Sul"]


def test_porto_alegre_placeless_headline_is_rejected() -> None:
    # Real article, genuinely about Porto Alegre's mayor — but the TITLE establishes no
    # place. Rejecting it is the conservative, correct call.
    result = score_article(
        article(
            "Brazil Mayor Mammoth Task : Rebuild From Floods , Prevent More",
            seendate=datetime(2024, 5, 21, tzinfo=UTC),
        ),
        place_terms=["Porto Alegre"],
        region_terms=["Rio Grande do Sul", "Guaiba", "Guaíba"],
        window=FLOOD_WINDOW,
        preset=FUSION_PRESETS["flood"],
        languages=["English"],
    )
    assert not result.passed
    assert result.reason == "toponym"
