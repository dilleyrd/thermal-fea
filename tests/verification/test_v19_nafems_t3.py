"""V-19 — NAFEMS T3: T(0.08 m, 32 s) = 36.60 degC; 0.3 degC (theta=1/2), 1.0 degC (theta=1)."""

import pytest
from cases import check_balance, load


@pytest.mark.parametrize("theta", [0.5, 1.0])
@pytest.mark.parametrize("etype", ["T6", "Q8"])
def test_v19(etype: str, theta: float) -> None:
    example = load("v19_nafems_t3")
    assert example.TARGET_C == 36.60 and example.TOL_C == {0.5: 0.3, 1.0: 1.0}
    assert (example.N, example.DT, example.TYPES) == (20, 0.5, ("T6", "Q8"))
    result = example.run(etype, theta)
    assert result["error_degC"] < example.TOL_C[theta]
    check_balance(result)
