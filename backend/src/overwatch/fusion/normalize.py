"""Pure text normalization + matching for the fusion gates (Phase 5 design §4.2).

Two matchers, deliberately different — this distinction is load-bearing:

  * `match_terms` — WHOLE-WORD. Used for TOPONYMS. Stops "Para" firing on "Paraguay".
  * `match_stems` — PREFIX at a word start. Used for THEMATIC keywords. Lets "deforest"
    fire on "deforester" and "deforestation", which is exactly how the two Novo Progresso
    demo articles pass the thematic gate (design §4.4).

Everything here is pure: no I/O, no DB, no network.
"""

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold, strip diacritics (Pará -> para), collapse whitespace.

    Diacritic folding runs both ways at the call site: the DB may hold "Pará" while a
    headline writes "Para", or the reverse. Both must match.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return WHITESPACE_RE.sub(" ", stripped.casefold()).strip()


def match_terms(text: str, terms: list[str]) -> list[str]:
    """Whole-word, diacritic-insensitive matches. Returns the ORIGINAL terms that hit."""
    haystack = normalize(text)
    hits: list[str] = []
    for term in terms:
        needle = normalize(term)
        if not needle:
            continue
        # `\b` is unreliable next to non-word characters (the hyphen in "BR-163" is a
        # word boundary itself, so `\bbr-163\b` behaves surprisingly). Bound explicitly
        # on "not an alphanumeric" instead.
        pattern = rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])"
        if re.search(pattern, haystack):
            hits.append(term)
    return hits


def match_stems(text: str, stems: list[str]) -> list[str]:
    """Prefix matches anchored at a word start. Returns the ORIGINAL stems that hit.

    Open-ended at the tail by design: "deforest" -> "deforester", "deforestation".
    Anchored at the head so it cannot fire mid-word ("reflooding" is not "flood").
    """
    haystack = normalize(text)
    hits: list[str] = []
    for stem in stems:
        needle = normalize(stem)
        if not needle:
            continue
        pattern = rf"(?<![0-9a-z]){re.escape(needle)}"
        if re.search(pattern, haystack):
            hits.append(stem)
    return hits
