"""Preset configs carry every tunable number; the spec's floor values are pinned here."""

import pytest
from pydantic import ValidationError

from overwatch.aois import SHOWCASE_AOIS
from overwatch.detection.models import ChangeType
from overwatch.detection.presets import VERTICAL_PRESETS, DetectionPreset, ThresholdRule


def test_spec_minimum_areas() -> None:
    # Port raised to 5,000: the SSIM-only construction rule catches all major structural change,
    # so a larger floor suppresses scattered off-site polygons while keeping the terminal body.
    assert VERTICAL_PRESETS["port"].min_area_m2 == 5_000.0
    # Forest relaxed from the spec's 5,000 to catch smaller visible clearings.
    assert VERTICAL_PRESETS["forest"].min_area_m2 == 3_000.0
    assert VERTICAL_PRESETS["flood"].min_area_m2 == 10_000.0


def test_change_types_per_vertical() -> None:
    assert VERTICAL_PRESETS["port"].change_type is ChangeType.CONSTRUCTION
    assert VERTICAL_PRESETS["forest"].change_type is ChangeType.VEGETATION_LOSS
    assert VERTICAL_PRESETS["flood"].change_type is ChangeType.FLOODING


def test_every_showcase_vertical_has_a_preset() -> None:
    assert {a.vertical for a in SHOWCASE_AOIS.values()} <= set(VERTICAL_PRESETS)


def test_primary_map_must_have_a_rule() -> None:
    with pytest.raises(ValidationError):
        DetectionPreset(
            vertical="x",
            change_type=ChangeType.FLOODING,
            rules=[ThresholdRule(map="ndwi", direction="increase", threshold=0.2)],
            primary_map="ndvi",
            min_area_m2=1.0,
        )


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ThresholdRule(map="ndvi", direction="decrease", threshold=0.0)


def test_flood_preset_has_was_not_water_precondition() -> None:
    # NDWI increase alone fires on water->clearer-water; the precondition requires the *before*
    # image to have been non-water, so only land that became water counts as flooding.
    flood = VERTICAL_PRESETS["flood"]
    precondition = [r for r in flood.rules if r.map == "ndwi_before"]
    assert len(precondition) == 1
    assert precondition[0].direction == "decrease"
    assert flood.primary_map == "ndwi"
    assert any(r.map == "ndwi" and r.direction == "increase" for r in flood.rules)


def test_flood_preset_has_no_absolute_after_gate() -> None:
    # Guards the WITHDRAWAL, not an absence by accident. An absolute after-image gate shipped
    # and was pulled the same day: sediment raises NIR, which drags NDWI down, so
    # `ndwi_after >= 0.05` rejected the turbid water that IS the flood (1,932.7 -> 925.8 ha on
    # the real pair). ndvi_after had no separating threshold either — its curve runs smoothly
    # from 57.6% of baseline at <= 0.00 to 92.2% at <= 0.50, where it stops gating at all.
    # Re-adding an absolute gate on these four bands means re-breaking recall; the fix needs
    # SWIR. See the flood preset's comment.
    assert not [r for r in VERTICAL_PRESETS["flood"].rules if r.map.endswith("_after")]


def test_absolute_bound_directions_take_the_threshold_as_the_bound() -> None:
    # "increase"/"decrease" read the threshold as a magnitude about zero, which cannot express a
    # bound whose sign disagrees with its direction ("NDVI at most +0.10"). at_most/at_least
    # take it literally, so 0.0 and negatives are ordinary values there.
    assert ThresholdRule(map="ndvi_after", direction="at_most", threshold=0.0).threshold == 0.0
    assert ThresholdRule(map="ndvi_after", direction="at_most", threshold=-0.2).threshold == -0.2
    assert ThresholdRule(map="ndvi_before", direction="at_least", threshold=0.5).threshold == 0.5


def test_port_preset_focuses_on_the_terminal_not_the_shoreline() -> None:
    # Off-subject construction is real change that no spectral threshold can disqualify; only
    # its location can. A shoreline buffer was tried first and withdrawn — the AOI is coastline
    # end to end, so distance to water barely discriminated. Distance to the subject does.
    assert VERTICAL_PRESETS["port"].focus_radius_m == 2_000.0


def test_verticals_with_diffuse_change_have_no_focus_radius() -> None:
    # Deforestation and flooding spread across a window by nature; anchoring them to their own
    # largest polygon would delete most of what they exist to find.
    assert VERTICAL_PRESETS["forest"].focus_radius_m is None
    assert VERTICAL_PRESETS["flood"].focus_radius_m is None


def test_forest_preset_has_was_forest_precondition() -> None:
    # NDVI decrease alone conflates deforestation with crop harvest; the precondition
    # requires the *before* image to have been forest-level green.
    forest = VERTICAL_PRESETS["forest"]
    precondition = [r for r in forest.rules if r.map == "ndvi_before"]
    assert len(precondition) == 1
    assert precondition[0].direction == "increase"
    assert precondition[0].threshold >= 0.5
    # the change rule (ndvi decrease) is still present and remains the primary map
    assert forest.primary_map == "ndvi"
    assert any(r.map == "ndvi" and r.direction == "decrease" for r in forest.rules)
