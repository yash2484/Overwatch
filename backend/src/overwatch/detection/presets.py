"""Per-vertical detection presets (design spec §6) — tunable defaults, never hardcoded."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from overwatch.detection.models import ChangeType

# "<index>" gates on the after-minus-before delta; "<index>_before" and "<index>_after" gate on
# the absolute index in that image — a precondition on prior land cover ("was this forest?") or a
# floor on what the pixel must actually BE afterwards ("is this water now?"). A delta alone
# cannot express either: it says how far a pixel moved, never where it started or landed.
MapName = Literal[
    "ndvi",
    "ndwi",
    "nbr",
    "ssim_dissim",
    "ndvi_before",
    "ndwi_before",
    "ndvi_after",
    "ndwi_after",
]

# "increase"/"decrease" read the threshold as a MAGNITUDE about zero (`>= t` / `<= -t`), which
# suits deltas. An absolute map often needs a bound whose sign does not match its direction —
# "NDVI at most +0.10" is unsayable as a decrease — so "at_most"/"at_least" take the threshold
# as the bound itself.
Direction = Literal["decrease", "increase", "at_most", "at_least"]


class ThresholdRule(BaseModel):
    """One gate on a change map; a preset's rules are AND-ed (conservative by construction)."""

    map: MapName
    direction: Direction
    threshold: float

    @model_validator(mode="after")
    def _magnitude_must_be_positive(self) -> "ThresholdRule":
        # For increase/decrease the threshold is a magnitude about zero, so a non-positive one
        # is meaningless (and `decrease` with 0.0 would gate on `<= -0.0`, i.e. everything).
        # at_most/at_least take the threshold as the bound itself, where 0 and negatives are
        # ordinary values — "NDVI at most 0.0" is exactly the water test.
        if self.direction in ("increase", "decrease") and self.threshold <= 0:
            raise ValueError(
                f"{self.direction!r} reads the threshold as a magnitude, so it must be > 0; "
                f"got {self.threshold}. Use at_most/at_least for an absolute bound."
            )
        return self


class DetectionPreset(BaseModel):
    vertical: str
    change_type: ChangeType
    rules: list[ThresholdRule] = Field(min_length=1)
    primary_map: MapName  # magnitude/confidence are computed from this map
    min_area_m2: float = Field(gt=0)
    morph_open_px: int = 3
    morph_close_px: int = 3
    ssim_band: str = "red"  # band the ssim_dissim map is computed from
    # Spatial prior, opt-in per vertical: when set, a detection must lie within this many metres
    # of open water in the before image. Verticals that are not location-constrained leave it
    # None rather than inheriting a filter that makes no physical sense for them.
    near_water_m: float | None = Field(default=None, gt=0)
    # Minimum size for a water body to count as coastline at all. Guards the prior against
    # regions where small water is everywhere (ponds, paddy, backwater), which would otherwise
    # place the whole AOI "near water" and neuter the gate.
    near_water_min_body_m2: float = Field(default=0.0, ge=0)

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
        # SSIM's breadth is also its cost: it fires on ANY structural rebuild inside the AOI, so
        # scattered inland buildings scored as high as the terminal itself (ssim_dissim ~0.87).
        # That is not a threshold error — they are real construction, and no threshold separates
        # them from the harbour, because raising it far enough drops the harbour too. What
        # disqualifies them is location: port works are on the sea. So the gate is geometric,
        # applied alongside the spectral rule rather than instead of it.
        # 1 km measured on the real pair: 22 detections / 83.3 ha -> 14 / 77.8 ha, dropping eight
        # small inland polygons holding 5.5 ha between them while keeping 93% of detected area.
        # 2 km gates nothing (the AOI is only 4.5 x 5.5 km, so the whole window is within 2 km of
        # the sea); 500 m starts eating quay-adjacent development the demo wants to show.
        # The size floor carries as much weight as the distance: the before-image water mask
        # holds the 1,538 ha sea plus 16 specks of <=0.1 ha inland, and each speck seeds its own
        # buffer. Without the floor the same 1 km buffer keeps 20 of 22. 10 ha clears the specks
        # by four orders of magnitude while admitting any genuinely navigable water.
        rules=[
            ThresholdRule(map="ssim_dissim", direction="increase", threshold=0.55),
        ],
        primary_map="ssim_dissim",
        min_area_m2=5_000.0,
        near_water_m=1_000.0,
        near_water_min_body_m2=100_000.0,
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
        # NDWI-increase alone cannot separate "land became water" from "water became more
        # water-like". Sediment settling or a channel deepening between two dates raises NDWI
        # by more than the 0.20 gate on pixels that were ALREADY water, so open water reads as
        # newly flooded: on the real Porto Alegre pair, 26% of detected area (719.7 ha) sat on
        # already-water pixels, including a 251 ha polygon that was 100% water beforehand, and
        # genuine flood polygons swelled across the channels between islands.
        # The was-NOT-water precondition is the flood analogue of forest's was-forest gate.
        # -0.05 rather than 0.0 because the land/water NDWI boundary here is sharp (median
        # ndwi_before inside true flood area is -0.73), so the small negative margin costs
        # ~19 ha of marginal wet-soil pixels and buys a clean separation.
        # KNOWN LIMITATION, deliberately left open: shaded/darkening land can still pass. NDWI
        # rises when a canopy is shaded (NIR falls harder than green), so a green hillside can
        # clear both rules below and be outlined as flood.
        #
        # An absolute after-image gate was shipped for it on 2026-08-13 and WITHDRAWN the same
        # day, because it cost more truth than it bought. Porto Alegre's floodwater is heavily
        # sediment-laden, and suspended solids raise NIR, which drags NDWI down — so
        # `ndwi_after >= 0.05` rejected the brown turbid water that IS the flood, keeping only
        # 925.8 ha of the 1,932.7 ha the two rules below find. `ndvi_after` was measured as the
        # replacement (it is far more shade-invariant) and its curve has no knee either:
        # <= 0.00 keeps 57.6%, <= 0.10 keeps 64.3%, <= 0.30 keeps 76.4%, <= 0.50 keeps 92.2%,
        # by which point it no longer gates anything. No absolute threshold on these four bands
        # separates turbid floodwater from wet vegetation, because the scene holds a genuine
        # continuum: open brown water, shallow water over grass, partly submerged canopy.
        #
        # The right instrument is SWIR, which is not fetched today (`_KEEP_ASSETS` is
        # red/green/blue/nir/scl). Water absorbs SWIR almost totally whatever its sediment load,
        # while shaded and wet vegetation does not, so MNDWI = (green - swir16)/(green + swir16)
        # or AWEI_sh (which carries an explicit shadow term) makes the cut that NDWI and NDVI
        # cannot. That needs two more assets and a re-fetch, so it is a scoped follow-up rather
        # than a tuning change. Until then, recall is preferred over precision here on purpose.
        rules=[
            ThresholdRule(map="ndwi", direction="increase", threshold=0.20),
            ThresholdRule(map="ndwi_before", direction="decrease", threshold=0.05),
        ],
        primary_map="ndwi",
        min_area_m2=10_000.0,
    ),
}
