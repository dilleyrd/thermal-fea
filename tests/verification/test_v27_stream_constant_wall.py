"""V-27 — stream along a wall at constant temperature: exponential outlet, NTU = 1."""

from __future__ import annotations

import pytest
from cases import TYPES, load


@pytest.mark.parametrize("n_cells", [1, 20])
@pytest.mark.parametrize("etype", TYPES)
def test_v27_stream_constant_wall(etype: str, n_cells: int) -> None:
    example = load("v27_stream_constant_wall")
    assert example.TOL == 1e-6
    result = example.run(etype, n_cells)
    assert result["error"] < example.TOL
    # every fluid node lies on the exponential, not only the outlet
    assert result["profile_error"] < example.TOL
    assert abs(result["imbalance"]) < 1e-8
    assert result["iterations"] == 1  # linear: constant h and frozen c_p
