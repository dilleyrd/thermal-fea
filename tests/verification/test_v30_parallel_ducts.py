"""V-30 — two identical parallel ducts: equal split, single-duct law, laminar 32 mu L V / D^2."""

from __future__ import annotations

from cases import load


def test_v30_parallel_ducts() -> None:
    example = load("v30_parallel_ducts")
    assert example.TOL == 1e-5
    result = example.run()
    assert result["split_error"] < example.TOL
    assert result["total_error"] < example.TOL
    assert result["laminar_error"] < example.TOL
    assert result["Re"] < 2000.0
    assert result["mass_conservation"] < 1e-10
