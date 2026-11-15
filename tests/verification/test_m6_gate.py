"""M6 gate — the runnable examples of V-25 and V-26, and V-15 with its energy balance.

The detailed checks of V-25 and V-26 are in ``test_v25_correlations.py`` and
``test_v26_friction.py``; this file ties the example scripts to the same tolerances.
"""

from __future__ import annotations

import pytest
from cases import TYPES, check_balance, load


def test_v25_example_meets_the_tolerance() -> None:
    example = load("v25_correlations")
    errors = example.run()
    assert set(errors) == {
        "plate_forced_avg", "plate_forced_local", "cylinder_crossflow", "vplate_natural",
        "inclined_natural", "hplate_up_natural", "hplate_down_natural", "hcyl_natural",
        "duct_internal", "power_law",
    }
    assert example.TOL == 1e-12
    for name, error in errors.items():
        assert error < example.TOL, name


def test_v26_example_meets_the_tolerances() -> None:
    example = load("v26_friction")
    assert (example.TOL_LAMINAR, example.TOL_TURBULENT) == (1e-3, 0.03)
    assert (example.RE_LAMINAR, example.RE_TURBULENT) == (500.0, 1e5)
    result = example.run()
    assert result["laminar_error"] < example.TOL_LAMINAR
    assert result["turbulent_error"] < example.TOL_TURBULENT


@pytest.mark.parametrize("etype", TYPES)
def test_v15_through_the_solver(etype: str) -> None:
    example = load("v15_natural_convection")
    result = example.run(etype)
    assert result["error"] < 1e-5
    assert 2 <= result["iterations"] <= 30  # nonlinear: the coefficient depends on T
    check_balance(result, linear_steady=False)
