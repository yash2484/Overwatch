"""Change maps between two co-registered windows (design spec §6)."""

import numpy as np
from skimage.metrics import structural_similarity


def index_delta(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """after - before as float32. NaN wherever either side is NaN."""
    return (after.astype(np.float32) - before.astype(np.float32)).astype(np.float32)


def ssim_dissimilarity(
    before: np.ndarray, after: np.ndarray, *, data_range: float = 10_000.0
) -> np.ndarray:
    """1 - local SSIM, in [0, 2]. NaNs are zero-filled first; mask their pixels downstream."""
    b = np.nan_to_num(before.astype(np.float32), nan=0.0)
    a = np.nan_to_num(after.astype(np.float32), nan=0.0)
    _, ssim_map = structural_similarity(b, a, data_range=data_range, full=True)
    return (1.0 - ssim_map).astype(np.float32)
