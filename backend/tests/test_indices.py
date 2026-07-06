"""Tests for spectral index functions."""

import numpy as np
import pytest

from overwatch.detection.indices import nbr, ndvi, ndwi


def test_ndvi_known_value() -> None:
    bands = {"nir": np.array([[3000]], dtype=np.uint16), "red": np.array([[1000]], dtype=np.uint16)}
    assert ndvi(bands)[0, 0] == pytest.approx(0.5)


def test_ndwi_known_value() -> None:
    bands = {
        "green": np.array([[600]], dtype=np.uint16),
        "nir": np.array([[3400]], dtype=np.uint16),
    }
    assert ndwi(bands)[0, 0] == pytest.approx(-0.7)


def test_nbr_known_value() -> None:
    bands = {
        "nir": np.array([[3000]], dtype=np.uint16),
        "swir22": np.array([[1000]], dtype=np.uint16),
    }
    assert nbr(bands)[0, 0] == pytest.approx(0.5)


def test_zero_denominator_is_nan_not_error() -> None:
    bands = {"nir": np.zeros((2, 2), dtype=np.uint16), "red": np.zeros((2, 2), dtype=np.uint16)}
    assert np.isnan(ndvi(bands)).all()


def test_nan_input_propagates() -> None:
    nir = np.array([[np.nan, 3000.0]], dtype=np.float32)
    red = np.array([[1000.0, 1000.0]], dtype=np.float32)
    out = ndvi({"nir": nir, "red": red})
    assert np.isnan(out[0, 0]) and out[0, 1] == pytest.approx(0.5)


def test_output_is_float32_and_uint16_safe() -> None:
    # uint16 sums overflow if not upcast first: 40000 + 40000 > 65535.
    bands = {
        "nir": np.full((2, 2), 40_000, dtype=np.uint16),
        "red": np.full((2, 2), 40_000, dtype=np.uint16),
    }
    out = ndvi(bands)
    assert out.dtype == np.float32
    assert out[0, 0] == pytest.approx(0.0)
