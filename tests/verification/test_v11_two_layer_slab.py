"""V-11 — two-layer slab: interface temperature; one flux value per region, both q; 1e-10."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v11(etype: str) -> None:
    example = load("v11_two_layer_slab")
    result = example.run(etype)
    assert result["regions"] == 2
    assert result["error"] < example.TOL
    assert result["interface_error"] < example.TOL
    assert result["flux_error"] < example.TOL
    check_balance(result)
