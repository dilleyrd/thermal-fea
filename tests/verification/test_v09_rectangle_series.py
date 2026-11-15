"""V-09 — square with one hot side (Fourier series) at (0.5, 0.5) and (0.5, 0.75); 1e-3."""

import pytest
from cases import TYPES, check_balance, load


def test_series_value_at_the_centre() -> None:
    example = load("v09_rectangle_series")
    assert example.theta(0.5, 0.5) == pytest.approx(0.25, abs=1e-12)  # stated in the case
    assert 0.25 < example.theta(0.5, 0.75) < 1.0


@pytest.mark.parametrize("etype", TYPES)
def test_v09(etype: str) -> None:
    example = load("v09_rectangle_series")
    result = example.run(etype)
    assert example.TOL == 1e-3 and example.SIZE == 0.02
    assert result["error"] < example.TOL
    assert result["centre_theta"] == pytest.approx(0.25, abs=1e-3)
    check_balance(result)
