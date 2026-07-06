"""Detection overlay PNGs for eyeball verification (Phase 2 gate)."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from overwatch.detection.models import Detection
from overwatch.imagery.models import AOIWindow
from overwatch.imagery.render import stretch_to_uint8

_OUTLINE = (255, 40, 40)


def render_detections_png(
    window: AOIWindow, detections: list[Detection], out_path: Path
) -> Path:
    """True-colour after-image with detection boundaries outlined in red."""
    rgb = np.dstack(
        [stretch_to_uint8(window.bands[b].astype(np.float32)) for b in ("red", "green", "blue")]
    )
    img = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(img)
    to_px = ~window.transform
    for det in detections:
        for ring in [det.geometry.exterior, *det.geometry.interiors]:
            draw.line([to_px * (x, y) for x, y in ring.coords], fill=_OUTLINE, width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
