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


def test_themes_are_the_literal_spike_verified_identifiers() -> None:
    # design §2.6 — pulled from the live LOOKUP-GKGTHEMES.TXT, not invented.
    assert "NATURAL_DISASTER_FLOOD" in FUSION_PRESETS["flood"].themes
    assert "ENV_DEFORESTATION" in FUSION_PRESETS["forest"].themes
    assert "MARITIME" in FUSION_PRESETS["port"].themes


def test_window_anchors_on_the_after_scene_not_the_pair() -> None:
    # Decision 3: a 3-year scene gap must NOT produce a 3-year window. The gate is a
    # ~44-day band around when the change was actually observed.
    after = datetime(2024, 5, 20, tzinfo=UTC)
    window = FusionWindow.around(after, FUSION_PRESETS["flood"])
    assert window.start == datetime(2024, 4, 20, tzinfo=UTC)
    assert window.end == datetime(2024, 6, 3, tzinfo=UTC)
    assert (window.end - window.start).days == 44


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
