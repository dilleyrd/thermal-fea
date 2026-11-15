"""V-06 — the cylinder of V-05 as a planar quarter annulus: same T(r), heat flow / 4; 2e-3."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v06(etype: str) -> None:
    example = load("v06_quarter_annulus")
    result = example.run(etype)
    assert example.TOL == 2e-3 and example.SIZE == 0.004
    assert result["error"] < example.TOL
    assert result["heat_error"] < example.TOL
    check_balance(result)
