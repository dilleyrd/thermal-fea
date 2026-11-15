"""V-16 — lumped body: exponential cooling at tau and 3 tau; 5e-3 (theta=1), 1e-4 (theta=1/2)."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("theta", [1.0, 0.5])
@pytest.mark.parametrize("etype", TYPES)
def test_v16(etype: str, theta: float) -> None:
    example = load("v16_lumped_body")
    assert example.TOL == {1.0: 5e-3, 0.5: 1e-4}
    assert pytest.approx(487.5) == example.TAU
    result = example.run(etype, theta)
    assert result["error"] < example.TOL[theta]
    case = result["case"]
    assert case.results.times.tolist() == pytest.approx([0.0, example.TAU, 3 * example.TAU])
    check_balance(result)  # linear: below 1e-8 on every step
