"""V-18 — semi-infinite solid, step in surface temperature: erf solution at t = 30 s; 1e-2."""

import numpy as np
import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v18(etype: str) -> None:
    example = load("v18_semi_infinite")
    assert (example.TOL, example.SIZE_NEAR, example.POINTS, example.END) == (
        1e-2, 0.001, (0.01, 0.02), 30.0)
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["far_end_change"] < 1e-6  # the far end stays undisturbed
    case = result["case"]
    settings = case.model.solution
    assert settings.lumped_capacitance and settings.auto_timestep
    # graded mesh: elements near x = 0 are much smaller than those far away
    x = case.nodes[:, 0]
    near, far = np.sort(np.unique(np.round(x[x < 0.01], 9))), np.sort(np.unique(x[x > 0.4]))
    assert np.diff(near).max() < 0.0015
    assert np.diff(far).max() > 5.0 * np.diff(near).max()
    check_balance(result)
