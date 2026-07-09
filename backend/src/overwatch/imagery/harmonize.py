"""Sentinel-2 BOA DN-offset harmonization (baseline ≥04.00) — shared by CLI and workers."""

import numpy as np

from overwatch.imagery.models import AOIWindow, SceneMeta


def harmonize_window(window: AOIWindow, scene: SceneMeta) -> AOIWindow:
    """Add the scene's BOA offset to every band (float32, clipped at 0); no-op when 0."""
    if not scene.dn_offset:
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
