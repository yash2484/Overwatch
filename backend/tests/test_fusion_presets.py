"""Fusion presets + the after-scene-anchored window (Phase 5 design §4.2, decision 3)."""

from datetime import UTC, datetime

import pytest

from overwatch.aois import SHOWCASE_AOIS
from overwatch.fusion.models import FusionWindow
from overwatch.fusion.presets import FUSION_PRESETS


def test_every_vertical_has_a_fusion_preset() -> None:
    assert set(FUSION_PRESETS) == {"port", "forest", "flood"}


@pytest.mark.parametrize("vertical", ["port", "forest", "flood"])
def test_presets_carry_themes_keywords_and_window_bounds(vertical: str) -> None:
    preset = FUSION_PRESETS[vertical]
    assert preset.themes, "themes drive GDELT retrieval (recall)"
    assert preset.keywords, "keywords are the thematic gate (precision)"
    assert preset.lead_days == 30
    assert preset.lag_days == 14
    assert preset.max_lookback_days == 400


def test_themes_are_the_literal_spike_verified_identifiers() -> None:
    # design §2.6 — pulled from the live LOOKUP-GKGTHEMES.TXT, not invented.
    assert "NATURAL_DISASTER_FLOOD" in FUSION_PRESETS["flood"].themes
    assert "ENV_DEFORESTATION" in FUSION_PRESETS["forest"].themes
    assert "MARITIME" in FUSION_PRESETS["port"].themes


# The REAL scene pairs, read out of Postgres 2026-07-12. The window design is verified
# against these, not against invented dates — an after-scene-anchored window looked fine
# on paper and returned ZERO articles for the forest AOI against the real pair.
REAL_PAIRS = {
    "forest": (datetime(2023, 7, 30, tzinfo=UTC), datetime(2024, 7, 24, tzinfo=UTC)),  # 360d
    "port": (datetime(2021, 2, 12, tzinfo=UTC), datetime(2025, 2, 11, tzinfo=UTC)),  # 1460d
    "flood": (datetime(2024, 4, 18, tzinfo=UTC), datetime(2024, 5, 21, tzinfo=UTC)),  # 33d
}


def test_window_covers_the_observation_interval_for_the_real_forest_pair() -> None:
    """The regression this locks: the Aug-2023 deforestation coverage MUST be in-window.

    An after-scene-anchored 44-day band (2024-06-24..2024-08-07) returned zero articles
    from live GDELT. The clearing accrues across the interval, and the news lands with it.
    """
    before, after = REAL_PAIRS["forest"]
    window = FusionWindow.around(before, after, FUSION_PRESETS["forest"])
    assert window.start == datetime(2023, 6, 30, tzinfo=UTC)  # before - 30d lead
    assert window.end == datetime(2024, 8, 7, tzinfo=UTC)  # after + 14d lag
    # The four real demo articles (Aug 4 / Aug 11 / Aug 29 / Sep 7, 2023) are all inside.
    for day in (datetime(2023, 8, 4), datetime(2023, 8, 11), datetime(2023, 9, 7)):
        assert window.start <= day.replace(tzinfo=UTC) <= window.end


def test_the_cap_stops_a_four_year_port_gap_becoming_a_four_year_window() -> None:
    """Vizhinjam's real pair spans 1,460 days. Uncapped, the gate would be vacuous."""
    before, after = REAL_PAIRS["port"]
    window = FusionWindow.around(before, after, FUSION_PRESETS["port"])
    assert window.start == datetime(2023, 12, 9, tzinfo=UTC)  # after - 400d cap - 30d lead
    assert window.end == datetime(2025, 2, 25, tzinfo=UTC)
    span_days = (window.end - window.start).days
    assert span_days < 500, f"window is {span_days}d — the cap is not doing its job"
    # ...and the real Jun/Jul-2024 Vizhinjam coverage still lands inside it.
    assert window.start <= datetime(2024, 6, 15, tzinfo=UTC) <= window.end


def test_a_tight_flood_pair_gets_a_tight_window() -> None:
    before, after = REAL_PAIRS["flood"]
    window = FusionWindow.around(before, after, FUSION_PRESETS["flood"])
    assert window.start == datetime(2024, 3, 19, tzinfo=UTC)
    assert window.end == datetime(2024, 6, 4, tzinfo=UTC)
    assert (window.end - window.start).days == 77  # bounded by the event, not the cap
    assert window.start <= datetime(2024, 5, 12, tzinfo=UTC) <= window.end  # real articles


def test_showcase_aois_carry_toponym_terms() -> None:
    assert SHOWCASE_AOIS["vizhinjam"].place_terms == ["Vizhinjam"]
    # design §2.5: ZERO of the four real Novo Progresso articles name the AOI in their
    # title — they all say "Amazon". The corroboration list must carry what titles
    # actually contain, or the gate scores 0/4 on our own demo corpus.
    assert "Amazon" in SHOWCASE_AOIS["novo-progresso"].region_terms
    # "Porto Alegre" is ambiguous (there is one in Portugal); the real headlines say
    # "Rio Grande do Sul".
    assert "Rio Grande do Sul" in SHOWCASE_AOIS["porto-alegre"].region_terms


def test_every_showcase_aoi_has_a_strict_place_term() -> None:
    # place_terms[0] is the STRICT term GDELT matches against full article text.
    for aoi in SHOWCASE_AOIS.values():
        assert aoi.place_terms, f"{aoi.slug} has no place_terms; fusion would be skipped"
