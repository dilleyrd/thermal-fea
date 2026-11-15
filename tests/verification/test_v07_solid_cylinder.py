"""V-07 — solid cylinder with generation and convection, axisymmetric; 1e-3."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v07(etype: str) -> None:
    example = load("v07_solid_cylinder")
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["heat_error"] < example.TOL  # all generated heat leaves by convection
    check_balance(result)
