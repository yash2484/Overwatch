"""Per-vertical detection presets (design spec §6) — tunable defaults, never hardcoded."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from overwatch.detection.models import ChangeType

MapName = Literal["ndvi", "ndwi", "nbr", "ssim_dissim"]


class ThresholdRule(BaseModel):
    """One gate on a change map; a preset's rules are AND-ed (conservative by construction)."""

    map: MapName
    direction: Literal["decrease", "increase"]
    threshold: float = Field(gt=0)


class DetectionPreset(BaseModel):
    vertical: str
    change_type: ChangeType
    rules: list[ThresholdRule] = Field(min_length=1)
    primary_map: MapName  # magnitude/confidence are computed from this map
    min_area_m2: float = Field(gt=0)
    morph_open_px: int = 3
    morph_close_px: int = 3
    ssim_band: str = "red"  # band the ssim_dissim map is computed from

    @model_validator(mode="after")
    def _primary_map_has_rule(self) -> "DetectionPreset":
        if self.primary_map not in {rule.map for rule in self.rules}:
            raise ValueError(f"primary_map {self.primary_map!r} has no ThresholdRule")
        return self


VERTICAL_PRESETS: dict[str, DetectionPreset] = {
    "port": DetectionPreset(
        vertical="port",
        change_type=ChangeType.CONSTRUCTION,
        rules=[
            ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.35),
            ThresholdRule(map="ndvi", direction="decrease", threshold=0.10),
        ],
        primary_map="ssim_dissim",
        min_area_m2=1_500.0,
    ),
    "forest": DetectionPreset(
        vertical="forest",
        change_type=ChangeType.VEGETATION_LOSS,
        rules=[ThresholdRule(map="ndvi", direction="decrease", threshold=0.20)],
        primary_map="ndvi",
        min_area_m2=5_000.0,
    ),
    "flood": DetectionPreset(
        vertical="flood",
        change_type=ChangeType.FLOODING,
        rules=[ThresholdRule(map="ndwi", direction="increase", threshold=0.20)],
        primary_map="ndwi",
        min_area_m2=10_000.0,
    ),
}
