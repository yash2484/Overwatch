"""Pure, deterministic validator for LLM-generated intelligence briefs (Phase 4).

Three gates, run per claim:

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

No I/O, no DB, no LLM calls. `validate_brief` is a plain function: `BriefDraft` +
`BriefRequest` in, `list[Violation]` out. An empty list means the brief is valid.
"""

import re

from overwatch.briefs.models import BriefDraft, BriefRequest, ClaimDraft, Violation

# Supported claim types in Phase 4. `reported` and `mixed` are structurally rejected
# here; Phase 5 is expected to lift that restriction once corroboration is designed.
_SUPPORTED_CLAIM_TYPES = frozenset({"observed", "context"})

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
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
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
_MONTH_DATE_RE = re.compile(rf"({'|'.join(_MONTH_NAMES)})\s+(\d{{4}})", re.IGNORECASE)
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
    before_iso = request.before_date.isoformat()
    after_iso = request.after_date.isoformat()

    for match in _ISO_DATE_RE.finditer(claim.text):
        iso = match.group(0)
        if iso not in (before_iso, after_iso):
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
    """Run the three gates against `draft`. Empty list means the brief is valid."""
    if not draft.claims:
        return [Violation(code="empty_brief", message="Brief has no claims.")]

    known_ids = {d.id for d in request.detections}
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
                    message=f"Claim type '{claim.claim_type}' is not supported in Phase 4.",
                    detail={"claim_type": claim.claim_type},
                )
            )
            continue

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
