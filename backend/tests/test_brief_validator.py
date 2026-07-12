"""Tests for the three-gate brief validator (overwatch.briefs.validator).

Pure-function tests: no DB, no I/O. `_req()` builds a fixed `BriefRequest` shared by
every gate family so the arithmetic (area sums, date matches) stays easy to audit:
detection id=1 has area_m2=12_000.0, id=2 has area_m2=6_200.0 (sum 18_200.0);
before_date=2021-02-12, after_date=2025-02-11.
"""

from datetime import date

from overwatch.briefs.models import BriefDraft, BriefRequest, ClaimDraft, DetectionRow
from overwatch.briefs.validator import validate_brief


def _req() -> BriefRequest:
    return BriefRequest(
        aoi_name="Vizhinjam International Seaport, Kerala",
        aoi_slug="vizhinjam",
        vertical="port",
        before_scene_id=101,
        after_scene_id=102,
        before_date=date(2021, 2, 12),
        after_date=date(2025, 2, 11),
        detections=[
            DetectionRow(
                id=1, change_type="new_structure", area_m2=12_000.0, magnitude=0.8, confidence=0.9
            ),
            DetectionRow(
                id=2, change_type="new_structure", area_m2=6_200.0, magnitude=0.6, confidence=0.85
            ),
        ],
    )


def test_valid_brief_passes() -> None:
    draft = BriefDraft(
        headline="H",
        claims=[
            ClaimDraft(
                text="Construction added about 18,200 m² between 2021-02-12 and 2025-02-11.",
                claim_type="observed",
                evidence=[1, 2],
            ),
            ClaimDraft(text="Vizhinjam is a deepwater transshipment port.", claim_type="context"),
        ],
    )
    assert validate_brief(draft, _req()) == []


def test_structural_gates() -> None:
    assert any(
        v.code == "empty_brief" for v in validate_brief(BriefDraft(headline="H", claims=[]), _req())
    )
    draft = BriefDraft(headline="H", claims=[ClaimDraft(text="  ", claim_type="context")])
    assert any(v.code == "blank_claim" for v in validate_brief(draft, _req()))
    # SUPERSEDED BY PHASE 5: `reported` is no longer structurally rejected — Gate 4 (the
    # observed/reported wall) polices it instead. This claim must STILL be rejected, but
    # for the right reasons: it cites no article, and "News says so." is not
    # reported-speech framing. Asserting more than the Phase-4 test did, not less.
    draft = BriefDraft(
        headline="H", claims=[ClaimDraft(text="News says so.", claim_type="reported")]
    )
    codes = {v.code for v in validate_brief(draft, _req())}
    assert "unsupported_claim_type" not in codes
    assert "unlinked_reported_claim" in codes
    assert "observational_framing_on_reported_claim" in codes
    # (A claim type outside the four is unreachable through BriefDraft — ClaimType is a
    # Pydantic Literal, so the SDK schema rejects it at the API boundary. The validator's
    # `unsupported_claim_type` branch remains as defence-in-depth for non-model callers.)


def test_gate1_linkage() -> None:
    draft = BriefDraft(
        headline="H", claims=[ClaimDraft(text="Something changed.", claim_type="observed")]
    )
    assert any(
        v.code == "unlinked_claim" and v.claim_seq == 0 for v in validate_brief(draft, _req())
    )
    draft = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="x", claim_type="observed", evidence=[999])],
    )
    assert any(v.code == "unknown_evidence_id" for v in validate_brief(draft, _req()))


def test_gate2_context_hygiene() -> None:
    quantified_texts = (
        "Cleared 5,000 m² of land.",
        "About 40% of the port.",
        "Work began on 2023-05-01.",
    )
    for text in quantified_texts:
        draft = BriefDraft(headline="H", claims=[ClaimDraft(text=text, claim_type="context")])
        assert any(v.code == "quantified_context_claim" for v in validate_brief(draft, _req())), (
            text
        )


def test_gate3_area_within_10pct_passes_outside_fails() -> None:
    ok = BriefDraft(
        headline="H",
        claims=[
            ClaimDraft(
                text="Roughly 12,500 m² of new surface.", claim_type="observed", evidence=[1]
            )
        ],
    )  # 12,000 ±10%
    assert validate_brief(ok, _req()) == []
    bad = BriefDraft(
        headline="H",
        claims=[
            ClaimDraft(
                text="Roughly 50,000 m² of new surface.", claim_type="observed", evidence=[1]
            )
        ],
    )
    assert any(v.code == "area_mismatch" for v in validate_brief(bad, _req()))


def test_gate3_km2_and_ha_units_normalize() -> None:
    ok = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="About 0.012 km² changed.", claim_type="observed", evidence=[1])],
    )
    assert validate_brief(ok, _req()) == []


def test_gate3_date_mismatch() -> None:
    bad = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Captured on 2020-01-01.", claim_type="observed", evidence=[1])],
    )
    assert any(v.code == "date_mismatch" for v in validate_brief(bad, _req()))
    ok = BriefDraft(
        headline="H",
        claims=[
            ClaimDraft(
                text="Between February 2021 and February 2025.",
                claim_type="observed",
                evidence=[1],
            )
        ],
    )
    assert validate_brief(ok, _req()) == []


def test_gate3_date_mismatch_unpadded_iso_still_caught() -> None:
    # "2021-2-9" is a genuinely hallucinated date: neither before_date (2021-02-12)
    # nor after_date (2025-02-11), and unpadded (single-digit month AND day) so the
    # old zero-padded-only regex `\d{4}-\d{2}-\d{2}` never matches it at all and the
    # date-figure check silently skips over it (no date_mismatch, wrongly).
    bad = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Captured on 2021-2-9.", claim_type="observed", evidence=[1])],
    )
    assert any(v.code == "date_mismatch" for v in validate_brief(bad, _req()))


def test_gate3_date_unpadded_iso_matching_before_date_still_passes() -> None:
    # "2021-2-12" (unpadded) is numerically the SAME calendar date as before_date
    # (2021-02-12, padded). A correct padding-insensitive fix must recognize this as
    # a match (no date_mismatch) — comparing the raw strings ("2021-2-12" != the
    # always-padded "2021-02-12") would wrongly flag a true, correctly-cited date as
    # a mismatch, violating the gate's "a matching date must still pass" contract.
    ok = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Captured on 2021-2-12.", claim_type="observed", evidence=[1])],
    )
    assert validate_brief(ok, _req()) == []


def test_gate3_date_mismatch_month_name_with_comma() -> None:
    # "January, 2019" (comma before year) must still be checked against the scene
    # dates, not silently skipped because the regex required a bare space.
    bad = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Captured in January, 2019.", claim_type="observed", evidence=[1])],
    )
    assert any(v.code == "date_mismatch" for v in validate_brief(bad, _req()))


def test_gate3_date_mismatch_regression_guards() -> None:
    # Existing passing cases must still pass after the regex/parsing changes.
    ok_month_pair = BriefDraft(
        headline="H",
        claims=[
            ClaimDraft(
                text="Between February 2021 and February 2025.",
                claim_type="observed",
                evidence=[1],
            )
        ],
    )
    assert validate_brief(ok_month_pair, _req()) == []

    # Padded ISO date that IS the before_date must not be flagged.
    ok_padded_iso = BriefDraft(
        headline="H",
        claims=[ClaimDraft(text="Captured on 2021-02-12.", claim_type="observed", evidence=[1])],
    )
    assert validate_brief(ok_padded_iso, _req()) == []
