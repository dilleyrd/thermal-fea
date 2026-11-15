"""V-21 — observed time-stepping order: ~1 (theta = 1), ~2 (theta = 1/2), within 0.15."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize(("theta", "expected"), [(1.0, 1.0), (0.5, 2.0)])
@pytest.mark.parametrize("etype", TYPES)
def test_v21(etype: str, theta: float, expected: float) -> None:
    example = load("v21_time_order")
    assert example.TOL == 0.15 and example.EXPECTED == {1.0: 1.0, 0.5: 2.0}
    result = example.run(etype, theta)
    assert abs(result["order"] - expected) < example.TOL
    check_balance(result)
