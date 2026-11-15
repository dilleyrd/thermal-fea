"""V-13 — conductivity k0 (1 + beta (T - 300)): Kirchhoff solution and flux; 1e-4."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v13(etype: str) -> None:
    example = load("v13_kirchhoff")
    result = example.run(etype)
    assert example.TOL == 1e-4 and example.N == 40
    assert result["error"] < example.TOL
    assert result["heat_error"] < example.TOL
    assert 2 <= result["iterations"] <= 30  # nonlinear: Newton iterations were needed
    check_balance(result, linear_steady=False)
