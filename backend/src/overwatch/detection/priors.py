"""Spatial priors: constraints on WHERE a change can plausibly be (design spec §6).

A threshold rule gates on how a pixel changed. A prior gates on where it sits. Some verticals
need both, because the spectral evidence can be perfectly real and still be the wrong subject:
construction across the window from the harbour is a genuine structural rebuild, so no SSIM
threshold rejects it — raising the threshold far enough to drop it drops the harbour too.

Pure module: geometry in, geometry out. No I/O, no LLM.
"""

from overwatch.detection.models import Detection


def keep_near_largest(detections: list[Detection], *, radius_m: float) -> list[Detection]:
    """Keep changes within `radius_m` of the largest one, which anchors the subject.

    A monitored site is one dominant structure plus its apron: at Vizhinjam the terminal is
    39.6 ha while no other polygon reaches 1.1 ha, so "largest" identifies the subject without
    any per-AOI configuration. Distance is edge to edge, not centroid to centroid — a quay runs
    for hundreds of metres, and measuring from its middle would push its own apron out.

    Anchoring on the largest rather than the first matters: polygonize emits in label order,
    which follows raster position, so the first element is whichever speck was labelled first.

    An earlier version of this prior measured distance to open water instead. It was withdrawn:
    the Vizhinjam AOI is 4.5 x 5.5 km of coastline, so every pixel is within 2 km of the sea and
    the gate removed almost nothing, while the tiny NDWI-positive specks scattered inland each
    seeded a buffer of their own. Proximity to the subject is the question; proximity to water
    was only ever a proxy for it.
    """
    if len(detections) < 2:
        return list(detections)
    anchor = max(detections, key=lambda d: d.area_m2)
    return [d for d in detections if d.geometry.distance(anchor.geometry) <= radius_m]
