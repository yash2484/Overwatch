"""Validator Gate 4 — the observed/reported wall (Phase 5 design §6).

This is the phase's trust boundary. The platform never lets journalism masquerade as
sensing: a claim backed ONLY by news articles must be framed as reported speech and may
carry NO quantities. Only detections carry measured figures.
"""

from datetime import date

from overwatch.briefs.models import (
    ArticleRow,
    BriefDraft,
    BriefRequest,
    ClaimDraft,
    DetectionRow,
)
from overwatch.briefs.validator import validate_brief


def _request() -> BriefRequest:
    return BriefRequest(
        aoi_name="Novo Progresso",
        aoi_slug="novo-progresso",
        vertical="forest",
        before_scene_id=1,
        after_scene_id=2,
        before_date=date(2023, 7, 30),
        after_date=date(2024, 7, 24),
        detections=[
            DetectionRow(
                id=10,
                change_type="vegetation_loss",
                area_m2=50_000.0,
                magnitude=0.4,
                confidence=0.8,
            )
        ],
        articles=[
            ArticleRow(
                id=99,
                title="Brazilian authorities launch probe into Amazon largest single deforester",
                domain="news.mongabay.com",
                seendate=date(2023, 8, 11),
            )
        ],
    )


def _codes(draft: BriefDraft) -> set[str]:
    return {v.code for v in validate_brief(draft, _request())}


def _draft(claim: ClaimDraft) -> BriefDraft:
    return BriefDraft(headline="h", claims=[claim])


# --- The wall holds ----------------------------------------------------------------


def test_reported_claim_with_reported_framing_is_valid() -> None:
    draft = _draft(
        ClaimDraft(
            text="Regional news reports that authorities opened a deforestation probe.",
            claim_type="reported",
            article_evidence=[99],
        )
    )
    assert validate_brief(draft, _request()) == []


def test_article_only_claim_with_OBSERVATIONAL_framing_is_REJECTED() -> None:
    """THE headline negative test: journalism must never wear the clothes of sensing."""
    draft = _draft(
        ClaimDraft(
            text="Imagery confirms that authorities opened a deforestation probe.",
            claim_type="reported",
            article_evidence=[99],
        )
    )
    assert "observational_framing_on_reported_claim" in _codes(draft)


def test_article_only_claim_carrying_a_QUANTITY_is_REJECTED() -> None:
    """A real article really does say '6,500 hectares'. The brief still may not — an
    article is not a measurement. Only detections carry figures."""
    draft = _draft(
        ClaimDraft(
            text="Regional news reports 6,500 hectares were cleared.",
            claim_type="reported",
            article_evidence=[99],
        )
    )
    assert "quantified_reported_claim" in _codes(draft)


def test_reported_claim_with_no_article_link_is_rejected() -> None:
    draft = _draft(
        ClaimDraft(text="Regional news reports a probe was opened.", claim_type="reported")
    )
    assert "unlinked_reported_claim" in _codes(draft)


def test_reported_claim_citing_an_unknown_article_id_is_rejected() -> None:
    draft = _draft(
        ClaimDraft(
            text="Regional news reports a probe was opened.",
            claim_type="reported",
            article_evidence=[12345],
        )
    )
    assert "unknown_article_id" in _codes(draft)


def test_observed_claim_may_not_carry_article_evidence() -> None:
    draft = _draft(
        ClaimDraft(
            text="Clearing is visible across the northern block.",
            claim_type="observed",
            evidence=[10],
            article_evidence=[99],
        )
    )
    assert "article_evidence_on_observed_claim" in _codes(draft)


# --- mixed claims need BOTH sides --------------------------------------------------


def test_mixed_claim_with_only_a_detection_is_rejected() -> None:
    draft = _draft(
        ClaimDraft(text="Clearing is visible and reported.", claim_type="mixed", evidence=[10])
    )
    assert "mixed_claim_missing_side" in _codes(draft)


def test_mixed_claim_with_only_an_article_is_rejected() -> None:
    draft = _draft(
        ClaimDraft(
            text="Clearing is visible and reported.",
            claim_type="mixed",
            article_evidence=[99],
        )
    )
    assert "mixed_claim_missing_side" in _codes(draft)


def test_mixed_claim_with_both_sides_is_valid() -> None:
    draft = _draft(
        ClaimDraft(
            text=(
                "Clearing of 50,000 m² is visible, and regional news reports an enforcement probe."
            ),
            claim_type="mixed",
            evidence=[10],
            article_evidence=[99],
        )
    )
    assert validate_brief(draft, _request()) == []


def test_mixed_claim_may_carry_a_quantity_because_it_cites_a_detection() -> None:
    # The quantity is licensed by the DETECTION, not the article.
    draft = _draft(
        ClaimDraft(
            text="Regional news reports a probe; imagery shows 50,000 m² cleared.",
            claim_type="mixed",
            evidence=[10],
            article_evidence=[99],
        )
    )
    assert validate_brief(draft, _request()) == []


# --- Phase 4 regression guard ------------------------------------------------------


def test_phase4_gates_still_hold_unlinked_observed_claim() -> None:
    draft = _draft(ClaimDraft(text="Clearing is visible.", claim_type="observed", evidence=[]))
    assert "unlinked_claim" in _codes(draft)


def test_phase4_reported_and_mixed_are_no_longer_structurally_rejected() -> None:
    # Phase 4 rejected these with `unsupported_claim_type`. Phase 5 lifts that.
    draft = _draft(
        ClaimDraft(
            text="Regional news reports a probe was opened.",
            claim_type="reported",
            article_evidence=[99],
        )
    )
    assert "unsupported_claim_type" not in _codes(draft)
