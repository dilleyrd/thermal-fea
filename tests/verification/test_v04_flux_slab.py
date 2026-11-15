"""V-04 — slab with a flux: T(0) = 300 + q L / k; 1e-10."""

import pytest
from cases import TYPES, check_balance, load


@pytest.mark.parametrize("etype", TYPES)
def test_v04(etype: str) -> None:
    example = load("v04_flux_slab")
    result = example.run(etype)
    assert result["error"] < example.TOL
    assert result["face_error"] < example.TOL
    check_balance(result)
