"""Numerical integration rules on the reference elements (Theory §3).

Each rule is a pair ``(points, weights)`` with ``points`` shaped ``(n_pts, dim)`` in the
reference coordinates of the element and ``weights`` shaped ``(n_pts,)``. The weights sum
to the reference measure: 1/2 for the unit triangle, 4 for the bi-unit square and 2 for
the line ``[-1, 1]``.

Rules are stored in a table keyed by element-type name, so a new element type adds a rule
with :func:`register_rule` instead of editing this module.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy import ndarray

from .errors import ModelError

Rule = tuple[ndarray, ndarray]


def gauss_line(n: int) -> Rule:
    """Gauss-Legendre rule on the line ``[-1, 1]``.

    Parameters
    ----------
    n : int
        Number of points; the rule is exact for polynomials of degree ``2 n - 1``.

    Returns
    -------
    points : ndarray, shape (n, 1)
        Reference coordinates (dimensionless).
    weights : ndarray, shape (n,)
        Weights summing to 2.
    """
    x, w = np.polynomial.legendre.leggauss(n)
    return x.reshape(-1, 1), w


def gauss_square(n: int) -> Rule:
    """Tensor-product ``n`` x ``n`` Gauss-Legendre rule on ``[-1, 1]^2``.

    Parameters
    ----------
    n : int
        Number of points per axis; exact to degree ``2 n - 1`` in each axis.

    Returns
    -------
    points : ndarray, shape (n*n, 2)
        Reference coordinates (dimensionless).
    weights : ndarray, shape (n*n,)
        Weights summing to 4.
    """
    x, w = np.polynomial.legendre.leggauss(n)
    xi, eta = np.meshgrid(x, x, indexing="ij")
    points = np.column_stack([xi.ravel(), eta.ravel()])
    weights = np.outer(w, w).ravel()
    return points, weights


def triangle_3pt() -> Rule:
    """Three-point degree-2 rule on the unit triangle (Theory §3).

    Returns
    -------
    points : ndarray, shape (3, 2)
    weights : ndarray, shape (3,)
        Each 1/6; they sum to the reference area 1/2.
    """
    points = np.array([[1 / 6, 1 / 6], [2 / 3, 1 / 6], [1 / 6, 2 / 3]])
    weights = np.full(3, 1 / 6)
    return points, weights


def triangle_dunavant4() -> Rule:
    """Six-point degree-4 Dunavant rule on the unit triangle (Theory §3).

    Returns
    -------
    points : ndarray, shape (6, 2)
    weights : ndarray, shape (6,)
        Weights for the reference area 1/2.
    """
    a1, b1, w1 = 0.445948490915965, 0.108103018168070, 0.223381589678011 / 2
    a2, b2, w2 = 0.091576213509771, 0.816847572980459, 0.109951743655322 / 2
    points = np.array(
        [[a1, a1], [a1, b1], [b1, a1], [a2, a2], [a2, b2], [b2, a2]]
    )
    weights = np.array([w1, w1, w1, w2, w2, w2])
    return points, weights


_RULES: dict[str, Callable[[], Rule]] = {
    "T3": triangle_3pt,
    "T6": triangle_dunavant4,
    "Q4": lambda: gauss_square(2),
    "Q8": lambda: gauss_square(3),
    "L2": lambda: gauss_line(2),
    "L3": lambda: gauss_line(3),
}


def register_rule(etype: str, factory: Callable[[], Rule]) -> None:
    """Register the integration rule used for an element type.

    Parameters
    ----------
    etype : str
        Element-type name.
    factory : callable
        Returns ``(points, weights)`` for that element type.
    """
    _RULES[etype] = factory


def rule(etype: str) -> Rule:
    """Return the integration rule of an element type.

    Parameters
    ----------
    etype : str
        Element-type name, e.g. ``"T3"``, ``"T6"``, ``"Q4"``, ``"Q8"``, ``"L2"``, ``"L3"``.

    Returns
    -------
    points : ndarray, shape (n_pts, dim)
        Reference coordinates of the integration points (dimensionless).
    weights : ndarray, shape (n_pts,)
        Weights summing to the reference measure.

    Raises
    ------
    ModelError
        If no rule is registered for ``etype``.
    """
    try:
        factory = _RULES[etype]
    except KeyError:
        raise ModelError(f"no quadrature rule for element type {etype!r}") from None
    points, weights = factory()
    return np.array(points, dtype=float), np.array(weights, dtype=float)
