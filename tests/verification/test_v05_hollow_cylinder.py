"""V-05 — hollow cylinder, axisymmetric: T(r) and heat flow per height; 1e-3 / 1e-5."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v05(etype: str) -> None:
    example = load("v05_hollow_cylinder")
    result = example.run(etype)
    assert example.tolerance(etype) == (1e-3 if etype in ("T3", "Q4") else 1e-5)
    assert result["error"] < example.tolerance(etype)
    assert result["heat_error"] < example.tolerance(etype)
    check_balance(result)
