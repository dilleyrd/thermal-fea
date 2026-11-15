"""V-10 — NAFEMS T4: T at (0.6, 0.2) = 18.3 degC, within 0.15 degC at the fine mesh."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v10(etype: str) -> None:
    example = load("v10_nafems_t4")
    assert (example.TARGET_C, example.TOL_C, example.SIZES) == (18.3, 0.15, (0.05, 0.025))
    coarse = example.run(etype, 0.05)
    fine = example.run(etype, 0.025)
    assert fine["error_degC"] < example.TOL_C
    assert abs(coarse["T_degC"] - example.TARGET_C) < 1.0  # the coarse mesh is already close
    assert fine["case"].mesh.n_elements > 3 * coarse["case"].mesh.n_elements
    check_balance(coarse)
    check_balance(fine)
