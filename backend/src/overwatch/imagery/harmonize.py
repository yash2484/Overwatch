"""Sentinel-2 BOA DN-offset harmonization (baseline ≥04.00) — shared by CLI and workers."""

import logging

import numpy as np

from overwatch.imagery.models import AOIWindow, SceneMeta

logger = logging.getLogger(__name__)

# If removing the BOA offset would clip more than this fraction of valid pixels to zero, the
# scene's DNs plainly do not carry the offset and the STAC flag that set it is wrong — skip.
_OFFSET_ABSENT_CLIP_FRACTION = 0.5


def _offset_is_present(window: AOIWindow, offset: int) -> bool:
    """True unless removing ``offset`` would clip most valid pixels — i.e. the DNs already lack it.

    The BOA offset (baseline ≥04.00) shifts every valid reflectance DN up by ``|offset|``, so a
    scene that genuinely carries it has essentially no valid pixels below ``|offset|``. But Earth
    Search's ``earthsearch:boa_offset_applied`` flag is unreliable for some products — notably
    Sentinel-2C, which reports baseline ≥04.00 with the flag False yet ships offset-free DNs
    (reflectance-scale, ~300 median). Blindly subtracting -1000 from those zeros ~90% of the
    scene. Detect that from the data: if a majority of valid pixels sit at/below ``|offset|``,
    the offset is not present.
    """
    columns = []
    for band in window.bands.values():
        arr = np.asarray(band)
        columns.append(arr[np.isfinite(arr) & (arr > 0)].ravel())
    valid = np.concatenate(columns) if columns else np.empty(0)
    if valid.size == 0:
        return True  # no signal to judge on — honour the metadata-driven default
    clip_fraction = float(np.mean(valid <= abs(offset)))
    return clip_fraction <= _OFFSET_ABSENT_CLIP_FRACTION


def harmonize_window(window: AOIWindow, scene: SceneMeta) -> AOIWindow:
    """Add the scene's BOA offset to every band (float32, clipped at 0); no-op when 0.

    Guards against a wrong STAC offset flag: if the DNs already lack the offset (removing it
    would clip most of the scene to zero), harmonization is skipped and warned rather than
    destroying the imagery. See ``_offset_is_present``.
    """
    if not scene.dn_offset:
        return window
    if scene.dn_offset < 0 and not _offset_is_present(window, scene.dn_offset):
        logger.warning(
            "scene %s: BOA offset %d would clip most valid pixels to zero; DNs are already "
            "offset-free (STAC flag wrong) — skipping harmonization",
            scene.stac_id,
            scene.dn_offset,
        )
        return window
    return AOIWindow(
        bands={
            name: np.clip(band.astype(np.float32) + scene.dn_offset, 0, None)
            for name, band in window.bands.items()
        },
        scl=window.scl,
        transform=window.transform,
        epsg=window.epsg,
    )
