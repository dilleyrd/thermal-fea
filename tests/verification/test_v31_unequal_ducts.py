"""V-31 — two parallel ducts, one twice as long, turbulent: equal dp with the Churchill f."""

from __future__ import annotations

from cases import load


def test_v31_unequal_ducts() -> None:
    example = load("v31_unequal_ducts")
    assert example.TOL == 1e-5
    assert example.L_LONG == 2.0 * example.L_SHORT
    result = example.run()
    assert result["dp_error_short"] < example.TOL
    assert result["dp_error_long"] < example.TOL
    assert result["Re_short"] > 4000.0
    assert result["Re_long"] > 4000.0
    assert result["flow_ratio"] > 1.0
    assert result["mass_conservation"] < 1e-10
