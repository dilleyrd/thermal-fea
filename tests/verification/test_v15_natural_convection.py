"""V-15 - slab with natural convection: surface temperature within 1e-5 of the scalar root."""

import pytest
from cases import TYPES, check_balance, load


def test_scalar_root_is_between_the_boundary_temperatures() -> None:
    example = load("v15_natural_convection")
    assert example.TOL == 1e-5
    assert example.T_INF < example.root() < example.T0


@pytest.mark.parametrize("etype", TYPES)
def test_v15(etype: str) -> None:
    example = load("v15_natural_convection")
    result = example.run(etype)
    assert result["error"] < example.TOL
    check_balance(result, linear_steady=False)
