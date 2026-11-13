"""M1.1 — quadrature rules (Theory §3)."""

from __future__ import annotations

from math import factorial

import numpy as np
import pytest

from thermalfea.core.errors import ModelError
from thermalfea.core.quadrature import register_rule, rule

REFERENCE_MEASURE = {"T3": 0.5, "T6": 0.5, "Q4": 4.0, "Q8": 4.0, "L2": 2.0, "L3": 2.0}
N_POINTS = {"T3": 3, "T6": 6, "Q4": 4, "Q8": 9, "L2": 2, "L3": 3}


def tri_exact(p: int, q: int) -> float:
    """Integral of xi^p eta^q over the unit triangle."""
    return factorial(p) * factorial(q) / factorial(p + q + 2)


def line_exact(p: int) -> float:
    """Integral of xi^p over [-1, 1]."""
    return 0.0 if p % 2 else 2.0 / (p + 1)


@pytest.mark.parametrize("etype", sorted(REFERENCE_MEASURE))
def test_weights_sum_to_reference_measure(etype: str) -> None:
    pts, w = rule(etype)
    assert pts.shape[0] == w.shape[0] == N_POINTS[etype]
    assert pts.ndim == 2
    assert np.all(w > 0)
    assert w.sum() == pytest.approx(REFERENCE_MEASURE[etype], rel=1e-14)


@pytest.mark.parametrize(("etype", "degree"), [("T3", 2), ("T6", 4)])
def test_triangle_rules_exact_to_total_degree(etype: str, degree: int) -> None:
    pts, w = rule(etype)
    assert pts.shape[1] == 2
    for p in range(degree + 1):
        for q in range(degree + 1 - p):
            got = np.sum(w * pts[:, 0] ** p * pts[:, 1] ** q)
            assert got == pytest.approx(tri_exact(p, q), abs=1e-14), (p, q)


@pytest.mark.parametrize(("etype", "degree"), [("T3", 2), ("T6", 4)])
def test_triangle_rules_not_exact_one_degree_higher(etype: str, degree: int) -> None:
    pts, w = rule(etype)
    p = degree + 1
    got = np.sum(w * pts[:, 0] ** p)
    assert abs(got - tri_exact(p, 0)) > 1e-8


@pytest.mark.parametrize(("etype", "degree"), [("Q4", 3), ("Q8", 5)])
def test_quad_rules_exact_per_axis(etype: str, degree: int) -> None:
    pts, w = rule(etype)
    assert pts.shape[1] == 2
    for p in range(degree + 1):
        for q in range(degree + 1):
            got = np.sum(w * pts[:, 0] ** p * pts[:, 1] ** q)
            assert got == pytest.approx(line_exact(p) * line_exact(q), abs=1e-13), (p, q)


@pytest.mark.parametrize(("etype", "degree"), [("L2", 3), ("L3", 5)])
def test_line_rules_exact(etype: str, degree: int) -> None:
    pts, w = rule(etype)
    assert pts.shape[1] == 1
    for p in range(degree + 1):
        got = np.sum(w * pts[:, 0] ** p)
        assert got == pytest.approx(line_exact(p), abs=1e-14), p


def test_points_lie_inside_reference_element() -> None:
    for etype in ("T3", "T6"):
        pts, _ = rule(etype)
        assert np.all(pts > 0)
        assert np.all(pts.sum(axis=1) < 1)
    for etype in ("Q4", "Q8", "L2", "L3"):
        pts, _ = rule(etype)
        assert np.all(np.abs(pts) < 1)


def test_t3_rule_is_the_one_in_theory() -> None:
    pts, w = rule("T3")
    expected = np.array([[1 / 6, 1 / 6], [2 / 3, 1 / 6], [1 / 6, 2 / 3]])
    np.testing.assert_allclose(pts, expected, rtol=0, atol=1e-15)
    np.testing.assert_allclose(w, 1 / 6, rtol=0, atol=1e-15)


def test_unknown_type_raises_and_registration_works() -> None:
    with pytest.raises(ModelError):
        rule("NOPE")
    register_rule("_TEST1", lambda: (np.zeros((1, 1)), np.array([2.0])))
    pts, w = rule("_TEST1")
    assert pts.shape == (1, 1)
    assert w.sum() == 2.0


def test_rule_returns_fresh_arrays() -> None:
    pts, w = rule("Q4")
    pts[:] = 0.0
    w[:] = 0.0
    pts2, w2 = rule("Q4")
    assert w2.sum() == pytest.approx(4.0)
    assert np.any(pts2 != 0.0)
