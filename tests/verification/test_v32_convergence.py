"""V-32 — manufactured solution: L2 error order >= 1.9 (T3, Q4) and >= 2.8 (T6, Q8)."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v32(etype: str) -> None:
    example = load("v32_convergence")
    assert example.SIZES == (0.1, 0.05, 0.025)
    assert example.required_order(etype) == (1.9 if etype in ("T3", "Q4") else 2.8)
    result = example.run(etype)
    assert result["order"] >= example.required_order(etype)
    assert result["l2_fine"] < result["l2_coarse"]
    check_balance(result)
