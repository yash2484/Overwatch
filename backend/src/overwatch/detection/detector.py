"""ChangeDetector protocol + the classical implementation (design spec §4, §6).

Pure module: no I/O, no LLM. The deterministic pipeline decides; downstream layers narrate.
"""

from typing import Protocol

import numpy as np

from overwatch.detection.differencing import index_delta, ssim_dissimilarity
from overwatch.detection.indices import nbr, ndvi, ndwi
from overwatch.detection.models import Detection
from overwatch.detection.polygonize import polygonize_mask
from overwatch.detection.postprocess import clean_mask, rule_mask
from overwatch.detection.presets import DetectionPreset
from overwatch.imagery.masking import apply_mask, usable_mask
from overwatch.imagery.models import AOIWindow

_INDEX_FNS = {"ndvi": ndvi, "ndwi": ndwi, "nbr": nbr}


class ChangeDetector(Protocol):
    def detect(
        self, before: AOIWindow, after: AOIWindow, preset: DetectionPreset
    ) -> list[Detection]:
        """Change polygons between two co-registered windows of the same AOI."""
        ...


class ClassicalChangeDetector:
    """Index deltas + SSIM -> AND-ed thresholds -> morphology -> polygons."""

    def detect(
        self, before: AOIWindow, after: AOIWindow, preset: DetectionPreset
    ) -> list[Detection]:
        _check_coregistered(before, after)
        usable = usable_mask(before.scl) & usable_mask(after.scl)
        maps = _change_maps(before, after, preset, usable)
        mask = clean_mask(
            rule_mask(maps, preset.rules, usable),
            open_px=preset.morph_open_px,
            close_px=preset.morph_close_px,
        )
        return polygonize_mask(mask, maps, preset, before.transform, before.epsg)


def _check_coregistered(before: AOIWindow, after: AOIWindow) -> None:
    if before.epsg != after.epsg:
        raise ValueError(f"CRS mismatch: {before.epsg} != {after.epsg}")
    if before.scl.shape != after.scl.shape:
        raise ValueError(f"shape mismatch: {before.scl.shape} != {after.scl.shape}")
    if before.transform != after.transform:
        raise ValueError("window transforms differ — windows are not co-registered")


def _change_maps(
    before: AOIWindow, after: AOIWindow, preset: DetectionPreset, usable: np.ndarray
) -> dict[str, np.ndarray]:
    """A map per rule name. Delta and absolute-before index maps see NaN-masked bands; SSIM raw.

    `"<index>"` -> after-minus-before delta; `"<index>_before"` -> the absolute index in the
    before image (a precondition on prior land cover, e.g. "was this forest?").
    """
    needed = {rule.map for rule in preset.rules}
    masked_before = {k: apply_mask(v, usable) for k, v in before.bands.items()}
    masked_after = {k: apply_mask(v, usable) for k, v in after.bands.items()}
    maps: dict[str, np.ndarray] = {}
    for name in needed:
        if name in _INDEX_FNS:
            fn = _INDEX_FNS[name]
            maps[name] = index_delta(fn(masked_before), fn(masked_after))
        elif name.endswith("_before") and name.removesuffix("_before") in _INDEX_FNS:
            maps[name] = _INDEX_FNS[name.removesuffix("_before")](masked_before)
        elif name == "ssim_dissim":
            maps[name] = ssim_dissimilarity(
                before.bands[preset.ssim_band], after.bands[preset.ssim_band]
            )
    return maps
