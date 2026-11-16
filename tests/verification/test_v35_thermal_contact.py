"""V-35 — thermal contact: V-11 with h_c = 2000 at the interface; jump = q / h_c; 1e-9."""

from __future__ import annotations

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v35_thermal_contact(etype: str) -> None:
    example = load("v35_thermal_contact")
    assert example.TOL == 1e-9 and example.H_C == 2000.0
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["jump_error"] < example.TOL
    assert result["flux_error"] < example.TOL
    # one extra node per interface node, and nothing else
    assert result["duplicated"] == result["interface_nodes"] > 0
    check_balance(result)
