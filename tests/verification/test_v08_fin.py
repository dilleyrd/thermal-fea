"""V-08 — straight fin in 2D against 1D fin theory with a convecting tip; 5e-3."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v08(etype: str) -> None:
    example = load("v08_fin")
    result = example.run(etype)
    assert example.TOL == 5e-3 and example.SIZE == 0.001
    assert result["error"] < example.TOL
    check_balance(result)
