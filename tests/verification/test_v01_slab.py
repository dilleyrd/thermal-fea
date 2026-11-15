"""V-01 — slab with two fixed faces: T linear, flux q = k dT / L everywhere; 1e-10."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v01(etype: str) -> None:
    example = load("v01_slab")
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["flux_error"] < example.TOL
    assert result["heat_error"] < example.TOL
    check_balance(result)
