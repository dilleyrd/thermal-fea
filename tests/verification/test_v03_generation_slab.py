"""V-03 — slab with generation: T = 300 + Q/(2k) x (L - x); linear 1e-3, quadratic 1e-10."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v03(etype: str) -> None:
    example = load("v03_generation_slab")
    result = example.run(etype)
    assert example.tolerance(etype) == (1e-3 if etype in ("T3", "Q4") else 1e-10)
    assert result["error"] < example.tolerance(etype)
    assert result["heat_error"] < 1e-10
    check_balance(result)
