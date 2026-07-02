"""RGB PNG rendering for eyeball verification (Phase 1 gate)."""

from pathlib import Path

import numpy as np
from PIL import Image

from overwatch.imagery.models import AOIWindow


def stretch_to_uint8(band: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray:
    """Percentile-stretch to 0..255 uint8. NaN-safe: NaN pixels render as 0 (black)."""
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return np.zeros(band.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        return np.zeros(band.shape, dtype=np.uint8)
    scaled = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
    return np.nan_to_num(scaled * 255.0).astype(np.uint8)


def render_rgb_png(window: AOIWindow, out_path: Path) -> Path:
    """True-colour PNG from the window's red/green/blue bands."""
    rgb = np.dstack(
        [stretch_to_uint8(window.bands[b].astype(np.float32)) for b in ("red", "green", "blue")]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_path)
    return out_path
