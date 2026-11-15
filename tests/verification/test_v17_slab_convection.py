"""V-17 — convectively cooled slab against the 20-term series; automatic time step; 2e-3."""

import pytest
from cases import TYPES, check_balance, load


def test_series_starts_at_one_and_decays() -> None:
    example = load("v17_slab_convection")
    assert example.series(0.0, 1e-9) == pytest.approx(1.0, abs=5e-3)  # 20 terms at Fo ~ 0
    assert 0.0 < example.series(1.0, 1.0) < example.series(0.0, 1.0) < example.series(0.0, 0.2)


@pytest.mark.parametrize("etype", TYPES)
def test_v17(etype: str) -> None:
    example = load("v17_slab_convection")
    assert (example.TOL, example.N, example.FOURIER) == (2e-3, 40, (0.2, 1.0))
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["case"].model.solution.auto_timestep is True
    check_balance(result)
