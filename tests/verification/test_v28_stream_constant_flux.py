"""V-28 — stream along a wall with a constant heat flux: T_out energy balance and q / h offset."""

from __future__ import annotations

import pytest
from cases import TYPES, load


@pytest.mark.parametrize("etype", TYPES)
def test_v28_stream_constant_flux(etype: str) -> None:
    example = load("v28_stream_constant_flux")
    assert example.TOL_OUT == 1e-6
    assert example.TOL_DT == 1e-2
    result = example.run(etype)
    assert result["error_out"] < example.TOL_OUT
    assert result["error_dT"] < example.TOL_DT
    assert abs(result["imbalance"]) < 1e-8
