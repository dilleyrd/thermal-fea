"""V-20 — radiative cooling of a lumped body against solve_ivp; time_tol = 0.005; 2e-3."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v20(etype: str) -> None:
    example = load("v20_radiative_cooling")
    assert (example.TOL, example.EPS, example.T_INIT) == (2e-3, 0.8, 800.0)
    result = example.run(etype)
    assert result["error"] < example.TOL
    settings = result["case"].model.solution
    assert settings.auto_timestep and settings.time_tol == 0.005
    assert 300.0 < result["T_ref"] < 400.0  # the body has cooled most of the way
    check_balance(result, linear_steady=False)
