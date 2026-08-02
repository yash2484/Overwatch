"""Per-vertical detection presets (design spec §6) — tunable defaults, never hardcoded."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from overwatch.detection.models import ChangeType

# "<index>" gates on the after-minus-before delta; "<index>_before" gates on the
# absolute index in the before image (a precondition on prior land cover).
MapName = Literal["ndvi", "ndwi", "nbr", "ssim_dissim", "ndvi_before"]


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
        # Construction = STRUCTURAL rebuild of the harbour, caught by SSIM dissimilarity alone.
        # A terminal is built across MANY prior covers within one before/after window — open sea
        # (reclamation), earlier-reclaimed bare fill, and vegetation alike. Any single-index
        # co-signal captures only ONE of those transitions and vetoes the rest: NDVI-decrease
        # sees veg->built but misses reclamation; NDWI-decrease sees sea->built but misses the
        # bare-fill body already reclaimed before the window. Both leave the terminal
        # half-outlined. SSIM is agnostic to the prior cover — it fires wherever the surface was
        # remade — so it captures the whole build (~75 ha near the Vizhinjam terminal vs ~30 ha
        # for the NDWI-gated rule). Specificity is the threshold (0.55 keeps strong rebuilds and
        # drops 4-year vegetation phenology) plus min_area, not an index veto that misses most
        # of the construction.
        rules=[
            ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.55),
        ],
        primary_map="ssim_dissim",
        min_area_m2=5_000.0,
    ),
    "forest": DetectionPreset(
        vertical="forest",
        change_type=ChangeType.VEGETATION_LOSS,
        # Relaxed from the initial conservative defaults: visible clearings were being missed
        # by eye. Three levers loosened together — (1) the NDVI-drop magnitude 0.20 -> 0.15
        # catches partial/edge clearings and hazier after-scenes; (2) the before-NDVI
        # precondition 0.60 -> 0.50 admits edge/degraded forest that still reads well above
        # cropland (~0.3-0.45) so harvested fields stay excluded; (3) min_area 0.5 ha -> 0.3 ha
        # catches smaller footprints. Still AND-ed and conservative by construction.
        rules=[
            ThresholdRule(map="ndvi", direction="decrease", threshold=0.15),
            ThresholdRule(map="ndvi_before", direction="increase", threshold=0.50),
        ],
        primary_map="ndvi",
        min_area_m2=3_000.0,
    ),
    "flood": DetectionPreset(
        vertical="flood",
        change_type=ChangeType.FLOODING,
        rules=[ThresholdRule(map="ndwi", direction="increase", threshold=0.20)],
        primary_map="ndwi",
        min_area_m2=10_000.0,
    ),
}
