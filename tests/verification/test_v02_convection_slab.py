"""V-02 — slab with convection: T(L) and the heat flow k (T0 - T(L)) / L; 1e-10."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v02(etype: str) -> None:
    example = load("v02_convection_slab")
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["end_error"] < example.TOL
    assert result["heat_error"] < example.TOL
    check_balance(result)
