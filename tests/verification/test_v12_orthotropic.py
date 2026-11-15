"""V-12 — orthotropic square, manufactured quadratic solution, quadratic elements; 1e-9."""

import numpy as np
import pytest
from cases import check_balance, load


@pytest.mark.parametrize("etype", ["T6", "Q8"])
def test_v12(etype: str) -> None:
    example = load("v12_orthotropic")
    assert example.TYPES == ("T6", "Q8") and example.TOL == 1e-9 and example.SIZE == 0.05
    result = example.run(etype)
    assert result["error"] < example.TOL
    check_balance(result)


def test_generation_is_computed_from_d() -> None:
    """Q = -div(D grad T) = -(100 Dxx + 60 Dxy + 40 Dyy) for the 30-degree material."""
    example = load("v12_orthotropic")
    c, s = np.cos(np.radians(30.0)), np.sin(np.radians(30.0))
    dxx = 50.0 * c * c + 5.0 * s * s
    dyy = 50.0 * s * s + 5.0 * c * c
    dxy = (50.0 - 5.0) * s * c
    assert example.generation() == pytest.approx(-(100 * dxx + 60 * dxy + 40 * dyy), rel=1e-14)
