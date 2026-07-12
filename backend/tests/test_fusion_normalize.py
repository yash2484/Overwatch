"""Pure text normalization + the two matchers (Phase 5 design §4.2)."""

from overwatch.fusion.normalize import match_stems, match_terms, normalize


def test_normalize_casefolds_and_strips_diacritics() -> None:
    assert normalize("Pará") == "para"
    assert normalize("Amazônia") == "amazonia"
    assert normalize("Guaíba") == "guaiba"
    assert normalize("  Rio  Grande   do Sul ") == "rio grande do sul"


def test_match_terms_is_diacritic_insensitive_both_directions() -> None:
    # The DB carries "Pará"; a headline may write "Para" (or vice versa). Both must hit.
    assert match_terms("Deforestation in Pará rises", ["Para"]) == ["Para"]
    assert match_terms("Deforestation in Para rises", ["Pará"]) == ["Pará"]


def test_match_terms_respects_word_boundaries() -> None:
    # The bug this prevents: "Para" firing on "Paraguay".
    assert match_terms("Flooding hits Paraguay", ["Para"]) == []
    assert match_terms("Deforestation in Para state", ["Para"]) == ["Para"]


def test_match_terms_handles_multiword_terms() -> None:
    # A real headline — it names the region, never the city.
    assert match_terms(
        "Brazil Rio Grande Do Sul May Have More Record Level Flooding",
        ["Rio Grande do Sul"],
    ) == ["Rio Grande do Sul"]


def test_match_terms_returns_every_match_in_term_order() -> None:
    assert match_terms("Novo Progresso, Pará", ["Pará", "Novo Progresso"]) == [
        "Pará",
        "Novo Progresso",
    ]


def test_match_terms_handles_hyphenated_terms() -> None:
    # \b is unreliable next to a hyphen — BR-163 must still match.
    assert match_terms("Trucks on the BR-163 highway", ["BR-163"]) == ["BR-163"]


def test_match_terms_ignores_empty_terms() -> None:
    assert match_terms("anything", ["", "  "]) == []


def test_match_stems_matches_prefixes_at_a_word_start() -> None:
    # The real demo articles: "deforester" and "deforestation" must BOTH hit "deforest".
    assert match_stems("Amazon largest single deforester", ["deforest"]) == ["deforest"]
    assert match_stems("Amazon deforestation falls 66%", ["deforest"]) == ["deforest"]
    assert match_stems("Record level flooding", ["flood"]) == ["flood"]
    assert match_stems("Evacuations ordered", ["evacuat"]) == ["evacuat"]


def test_match_stems_does_not_match_mid_word() -> None:
    # A stem must START a word, or "flood" fires on unrelated words containing it.
    assert match_stems("The reflooding of memories", ["flood"]) == []


def test_match_stems_multiword_stem() -> None:
    assert match_stems("The water levels kept rising", ["water level"]) == ["water level"]


def test_match_stems_returns_each_stem_once() -> None:
    assert match_stems("Deforestation and deforester alike", ["deforest"]) == ["deforest"]
