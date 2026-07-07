"""Preset configs carry every tunable number; the spec's floor values are pinned here."""

import pytest
from pydantic import ValidationError

from overwatch.aois import SHOWCASE_AOIS
from overwatch.detection.models import ChangeType
from overwatch.detection.presets import VERTICAL_PRESETS, DetectionPreset, ThresholdRule


def test_spec_minimum_areas() -> None:
    assert VERTICAL_PRESETS["port"].min_area_m2 == 1_500.0
    assert VERTICAL_PRESETS["forest"].min_area_m2 == 5_000.0
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
