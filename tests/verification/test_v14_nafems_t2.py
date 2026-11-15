"""V-14 — NAFEMS T2: radiating bar, T at the radiating end = 927.0 K within 0.1 K."""

import pytest
from cases import TYPES, check_balance, load


def test_scalar_root_matches_the_published_target() -> None:
    example = load("v14_nafems_t2")
    assert abs(example.root() - example.TARGET) < example.TOL_K


@pytest.mark.parametrize("etype", TYPES)
def test_v14(etype: str) -> None:
    example = load("v14_nafems_t2")
    assert (example.TARGET, example.TOL_K) == (927.0, 0.1)
    result = example.run(etype)
    assert result["error_K"] < example.TOL_K
    assert result["root_error_K"] < 1e-6  # and it is the root of the scalar balance
    check_balance(result, linear_steady=False)
