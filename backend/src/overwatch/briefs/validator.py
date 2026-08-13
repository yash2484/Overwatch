"""Pure, deterministic validator for LLM-generated intelligence briefs (Phase 4 + 5).

FOUR gates, run per claim:

1. **Linkage** — every `observed` claim must cite at least one evidence id, and every
   cited id must resolve to a real detection on the request (`unlinked_claim`,
   `unknown_evidence_id`).
2. **Context hygiene** — `context` claims (background, not tied to a specific
   detection) must not smuggle in unverifiable numbers: no area/percent/date figures
   (`quantified_context_claim`).
3. **Numeric consistency** — for `observed` claims with resolvable evidence, any area
   figure quoted in the text must be within ±10% of the summed area of the linked
   detections, and any date quoted must exactly equal the request's before/after date
   (`area_mismatch`, `date_mismatch`).
4. **The observed/reported wall** (Phase 5 design §6) — a claim backed ONLY by news
   articles is REPORTED SPEECH. It must be framed as such, it may carry NO quantities,
   and it must cite article ids that resolve. Conversely an `observed` claim may cite no
   articles at all, and a `mixed` claim must cite BOTH a detection and an article.
   **The platform never lets journalism masquerade as sensing.** Articles are not
   measurements; only detections carry figures.

No I/O, no DB, no LLM calls. `validate_brief` is a plain function: `BriefDraft` +
`BriefRequest` in, `list[Violation]` out. An empty list means the brief is valid.
"""

import re
from datetime import date

from overwatch.briefs.models import BriefDraft, BriefRequest, ClaimDraft, Violation

# Phase 5 lifts Phase 4's restriction: `reported` and `mixed` are now supported, policed
# by Gate 4 below. All four claim types are legal.
_SUPPORTED_CLAIM_TYPES = frozenset({"observed", "context", "reported", "mixed"})

# --- Gate 4 (Phase 5 §6): the observed/reported wall -------------------------------
# A claim backed only by articles must SOUND like reported speech...
_REPORTED_FRAMING_RE = re.compile(
    r"\b(reports?|reported|reportedly|according to|regional news|local media|"
    r"press reports?|news outlets?|coverage indicates|media reports?)\b",
    re.IGNORECASE,
)
# ...and must never wear the clothes of sensing.
_OBSERVATIONAL_FRAMING_RE = re.compile(
    r"\b(imagery (?:shows|confirms|reveals|indicates)|"
    r"satellite (?:imagery |data )?(?:shows|confirms|reveals)|"
    r"we (?:observe|observed|detect|detected)|detected|is visible|are visible|"
    r"analysis shows|the data shows|pixels? (?:show|confirm))\b",
    re.IGNORECASE,
)

_AREA_TOLERANCE_FRACTION = 0.10

# Unit alternatives ordered longer/more-specific-first (km before its m prefix,
# "hectares?" before the bare "ha" abbreviation) and guarded with a trailing
# negative lookahead so a bare "ha" cannot match inside an unrelated word like
# "hangars" (and likewise "m2" cannot match as a prefix of some longer token).
_AREA_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(km²|km2|hectares?|ha|m²|m2|sq\s?m)(?![a-zA-Z])",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\d[\d,.]*\s*%")
# Month/day are 1-or-2 digit so unpadded ISO dates ("2021-2-12") are still caught by
# Gate 3 rather than silently passing the date-figure check; padding-insensitive
# comparison happens in `_check_dates` below (never string-compare against an
# always-padded `date.isoformat()`).
_ISO_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Optional comma before the year ("February, 2021") in addition to the plain
# "February 2021" form.
_MONTH_DATE_RE = re.compile(rf"({'|'.join(_MONTH_NAMES)}),?\s+(\d{{4}})", re.IGNORECASE)
_MONTH_NUMBER = {name.lower(): i for i, name in enumerate(_MONTH_NAMES, start=1)}


def _area_to_m2(value: float, unit: str) -> float:
    """Normalize a quoted area figure to square meters."""
    unit = unit.lower().replace(" ", "")
    if unit in ("km²", "km2"):
        return value * 1_000_000
    if unit == "ha" or unit.startswith("hectare"):
        return value * 10_000
    return value  # m², m2, sqm


def _has_quantity(text: str) -> bool:
    """True if text contains an area, percent, or date figure of any supported form."""
    return bool(
        _AREA_RE.search(text)
        or _PERCENT_RE.search(text)
        or _ISO_DATE_RE.search(text)
        or _MONTH_DATE_RE.search(text)
    )


def _check_area(claim: ClaimDraft, seq: int, linked_area_m2: float) -> list[Violation]:
    violations: list[Violation] = []
    for match in _AREA_RE.finditer(claim.text):
        raw_value, unit = match.group(1), match.group(2)
        value_m2 = _area_to_m2(float(raw_value.replace(",", "")), unit)
        tolerance = _AREA_TOLERANCE_FRACTION * linked_area_m2
        if abs(value_m2 - linked_area_m2) > tolerance:
            violations.append(
                Violation(
                    code="area_mismatch",
                    claim_seq=seq,
                    message=(
                        f"Claim quotes {match.group(0).strip()} (~{value_m2:.0f} m²), "
                        f"outside ±10% of linked detection area ({linked_area_m2:.0f} m²)."
                    ),
                    detail={
                        "quoted_m2": value_m2,
                        "linked_area_m2": linked_area_m2,
                    },
                )
            )
    return violations


def _check_dates(claim: ClaimDraft, seq: int, request: BriefRequest) -> list[Violation]:
    violations: list[Violation] = []
    scene_dates = (request.before_date, request.after_date)

    for match in _ISO_DATE_RE.finditer(claim.text):
        iso = match.group(0)
        year_str, month_str, day_str = iso.split("-")
        try:
            # Parse to a `date` (not a string compare) so an unpadded quote like
            # "2021-2-12" is recognized as equal to the padded scene date it means.
            quoted_date: date | None = date(int(year_str), int(month_str), int(day_str))
        except ValueError:
            # Impossible calendar date (e.g. "2021-13-45") can't be a scene date either.
            quoted_date = None
        if quoted_date not in scene_dates:
            violations.append(
                Violation(
                    code="date_mismatch",
                    claim_seq=seq,
                    message=f"Claim date {iso} matches neither before nor after scene date.",
                    detail={"quoted_date": iso},
                )
            )

    before_key = (request.before_date.month, request.before_date.year)
    after_key = (request.after_date.month, request.after_date.year)
    for match in _MONTH_DATE_RE.finditer(claim.text):
        month_name, year_str = match.group(1), match.group(2)
        key = (_MONTH_NUMBER[month_name.lower()], int(year_str))
        if key not in (before_key, after_key):
            violations.append(
                Violation(
                    code="date_mismatch",
                    claim_seq=seq,
                    message=(
                        f"Claim date '{match.group(0)}' matches neither before nor after "
                        "scene date."
                    ),
                    detail={"quoted_date": match.group(0)},
                )
            )
    return violations


def validate_brief(draft: BriefDraft, request: BriefRequest) -> list[Violation]:
    """Run the four gates against `draft`. Empty list means the brief is valid."""
    if not draft.claims:
        return [Violation(code="empty_brief", message="Brief has no claims.")]

    known_ids = {d.id for d in request.detections}
    known_article_ids = {a.id for a in request.articles}
    violations: list[Violation] = []

    for seq, claim in enumerate(draft.claims):
        text = claim.text.strip()
        if not text:
            violations.append(
                Violation(code="blank_claim", claim_seq=seq, message="Claim text is blank.")
            )
            continue

        if claim.claim_type not in _SUPPORTED_CLAIM_TYPES:
            violations.append(
                Violation(
                    code="unsupported_claim_type",
                    claim_seq=seq,
                    message=f"Claim type '{claim.claim_type}' is not a supported claim type.",
                    detail={"claim_type": claim.claim_type},
                )
            )
            continue

        # Gate 4a — cited article ids must resolve (applies to reported AND mixed).
        if claim.claim_type in ("reported", "mixed"):
            for aid in claim.article_evidence:
                if aid not in known_article_ids:
                    violations.append(
                        Violation(
                            code="unknown_article_id",
                            claim_seq=seq,
                            message=(
                                f"Claim cites article id {aid}, which is not a known article."
                            ),
                            detail={"article_id": aid},
                        )
                    )

        if claim.claim_type == "context":
            if _has_quantity(text):
                violations.append(
                    Violation(
                        code="quantified_context_claim",
                        claim_seq=seq,
                        message="Context claim contains an unverifiable area/percent/date figure.",
                    )
                )
            continue

        # Gate 4b — a `mixed` claim must genuinely straddle both kinds of evidence.
        # Its quantities are licensed by the DETECTION it cites, so it is exempt from the
        # no-quantities rule (but the numeric-consistency gate still applies below).
        if claim.claim_type == "mixed":
            if not claim.evidence or not claim.article_evidence:
                violations.append(
                    Violation(
                        code="mixed_claim_missing_side",
                        claim_seq=seq,
                        message=(
                            "A 'mixed' claim must cite at least one detection AND at least "
                            "one article."
                        ),
                    )
                )
            else:
                unknown = [eid for eid in claim.evidence if eid not in known_ids]
                for eid in unknown:
                    violations.append(
                        Violation(
                            code="unknown_evidence_id",
                            claim_seq=seq,
                            message=(
                                f"Claim cites evidence id {eid}, which is not a known detection."
                            ),
                            detail={"evidence_id": eid},
                        )
                    )
                linked = [d for d in request.detections if d.id in claim.evidence]
                if linked:
                    violations.extend(_check_area(claim, seq, sum(d.area_m2 for d in linked)))
                violations.extend(_check_dates(claim, seq, request))
            continue

        # Gate 4c — THE WALL. A claim backed only by articles is REPORTED SPEECH:
        # it must be framed as such, and it may carry no quantities. Articles are not
        # measurements. Journalism never masquerades as sensing.
        if claim.claim_type == "reported":
            if not claim.article_evidence:
                violations.append(
                    Violation(
                        code="unlinked_reported_claim",
                        claim_seq=seq,
                        message="Reported claim cites no article evidence.",
                    )
                )
            if _OBSERVATIONAL_FRAMING_RE.search(text) or not _REPORTED_FRAMING_RE.search(text):
                violations.append(
                    Violation(
                        code="observational_framing_on_reported_claim",
                        claim_seq=seq,
                        message=(
                            "A claim backed only by news articles must use reported-speech "
                            "framing (e.g. 'Regional news reports that...'), never "
                            "observational framing. Journalism is not sensing."
                        ),
                    )
                )
            if _has_quantity(text):
                violations.append(
                    Violation(
                        code="quantified_reported_claim",
                        claim_seq=seq,
                        message=(
                            "A claim backed only by news articles may not carry a quantity. "
                            "Only detections carry measured figures."
                        ),
                    )
                )
            continue

        # claim.claim_type == "observed" — Gate 4d: pixels only, no article links.
        if claim.article_evidence:
            violations.append(
                Violation(
                    code="article_evidence_on_observed_claim",
                    claim_seq=seq,
                    message=("An 'observed' claim may not cite article evidence — use 'mixed'."),
                )
            )

        # claim.claim_type == "observed"
        if not claim.evidence:
            violations.append(
                Violation(
                    code="unlinked_claim",
                    claim_seq=seq,
                    message="Observed claim cites no evidence (detection ids).",
                )
            )
            linked_detections = []
        else:
            unknown_ids = [eid for eid in claim.evidence if eid not in known_ids]
            for eid in unknown_ids:
                violations.append(
                    Violation(
                        code="unknown_evidence_id",
                        claim_seq=seq,
                        message=f"Claim cites evidence id {eid}, which is not a known detection.",
                        detail={"evidence_id": eid},
                    )
                )
            linked_detections = [d for d in request.detections if d.id in claim.evidence]

        # Area consistency only makes sense once we have at least one real linked
        # detection to sum against; zero linked detections is already flagged above
        # via unlinked_claim or unknown_evidence_id.
        if linked_detections:
            linked_area_m2 = sum(d.area_m2 for d in linked_detections)
            violations.extend(_check_area(claim, seq, linked_area_m2))

        violations.extend(_check_dates(claim, seq, request))

    return violations
