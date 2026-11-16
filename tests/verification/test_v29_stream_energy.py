"""V-29 — energy conservation with a stream: boundary heat + m c_p (T_in - T_out) = 0."""

from __future__ import annotations

import pytest
from cases import TYPES, load


@pytest.mark.parametrize("variant", ["given", "network"])
@pytest.mark.parametrize("etype", TYPES)
def test_v29_stream_energy(etype: str, variant: str) -> None:
    example = load("v29_stream_energy")
    assert example.TOL == 1e-8
    result = example.run(etype, variant)
    assert result["error"] < example.TOL
    assert abs(result["imbalance"]) < example.TOL
    # the streams do carry the heat away, and the water stays inside its property table
    assert result["stream_enthalpy"] < -1000.0
    assert example.T_IN < result["T_out"] < 360.0
    if variant == "network":
        lower, upper = result["streams"]["lower"], result["streams"]["upper"]
        assert lower["mass_flow"][-1] > upper["mass_flow"][-1] > 0.0  # the extra loss
        assert lower["dp"][-1] == pytest.approx(400.0) and upper["dp"][-1] == pytest.approx(400.0)
