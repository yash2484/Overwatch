import numpy as np

from overwatch.imagery.masking import (
    MASKED_SCL_CLASSES,
    apply_mask,
    usable_fraction,
    usable_mask,
)


def test_usable_mask_flags_cloud_and_nodata() -> None:
    scl = np.array([[4, 8], [0, 5]], dtype=np.uint8)
    expected = np.array([[True, False], [False, True]])
    assert (usable_mask(scl) == expected).all()


def test_every_masked_class_is_unusable() -> None:
    for cls in MASKED_SCL_CLASSES:
        assert usable_fraction(np.full((3, 3), cls, dtype=np.uint8)) == 0.0


def test_every_usable_class_is_usable() -> None:
    for cls in (2, 4, 5, 6, 7):
        assert usable_fraction(np.full((3, 3), cls, dtype=np.uint8)) == 1.0


def test_usable_fraction_counts_share() -> None:
    scl = np.array([[4, 9], [4, 4]], dtype=np.uint8)
    assert usable_fraction(scl) == 0.75


def test_usable_fraction_empty_is_zero() -> None:
    assert usable_fraction(np.array([], dtype=np.uint8)) == 0.0


def test_apply_mask_nans_unusable_and_leaves_input_untouched() -> None:
    band = np.array([[100, 200], [300, 400]], dtype=np.uint16)
    mask = np.array([[True, False], [False, True]])
    out = apply_mask(band, mask)
    assert out.dtype == np.float32
    assert np.isnan(out[0, 1]) and np.isnan(out[1, 0])
    assert out[0, 0] == 100.0 and out[1, 1] == 400.0
    assert band[0, 1] == 200  # input not mutated
