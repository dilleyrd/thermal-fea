"""Linear solves. The only module that calls SciPy's sparse solvers (Plan §7 rule 11).

Other code uses :func:`solve_partitioned` or obtains a :class:`Factorization` from a
:class:`LinearSolver`, so iterative or parallel solvers can be added later without
touching the drivers.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np
from numpy import ndarray
from scipy.sparse import csr_matrix, issparse
from scipy.sparse.linalg import splu

from ..core.errors import SolverError

log = logging.getLogger(__name__)

#: A factorisation whose smallest pivot is below this fraction of the largest is singular.
SINGULAR_PIVOT_RATIO = 1e-13


class Factorization(Protocol):
    """A factorised matrix that can solve for any number of right-hand sides."""

    def solve(self, b: ndarray) -> ndarray:
        """Return ``x`` with ``A x = b``."""
        ...


class LinearSolver(Protocol):
    """Factory of factorisations."""

    def factorize(self, A: csr_matrix, symmetric: bool) -> Factorization:
        """Factorise ``A``; ``symmetric`` is a hint that ``A`` equals its transpose."""
        ...


class SuperLUFactorization:
    """Sparse LU factorisation (SuperLU through :func:`scipy.sparse.linalg.splu`).

    The object can be cached and reused for several right-hand sides.

    Parameters
    ----------
    A : scipy.sparse matrix, shape (n, n)
        Matrix to factorise.
    symmetric : bool
        Hint that ``A`` is symmetric; selects a fill-reducing ordering suited to it.

    Raises
    ------
    SolverError
        If ``A`` is not square, contains non-finite values, or is singular.
    """

    def __init__(self, A: csr_matrix, symmetric: bool = False) -> None:
        if not issparse(A):
            A = csr_matrix(A)
        if A.shape[0] != A.shape[1]:
            raise SolverError(f"matrix is not square: {A.shape}")
        self.n = int(A.shape[0])
        self.symmetric = bool(symmetric)
        self._lu = None
        if self.n == 0:
            return
        csc = A.tocsc()
        if not np.all(np.isfinite(csc.data)):
            raise SolverError("matrix contains non-finite values")
        try:
            self._lu = splu(csc, permc_spec="MMD_AT_PLUS_A" if symmetric else "COLAMD")
        except RuntimeError as exc:  # "Factor is exactly singular"
            raise SolverError(f"matrix is singular: {exc}") from exc
        pivots = np.abs(self._lu.U.diagonal())
        if not np.all(np.isfinite(pivots)) or pivots.min() <= SINGULAR_PIVOT_RATIO * pivots.max():
            raise SolverError(
                "matrix is singular to working precision (no temperature reference, or an "
                "unconnected part of the model?)"
            )

    def solve(self, b: ndarray) -> ndarray:
        """Solve ``A x = b``.

        Parameters
        ----------
        b : ndarray, shape (n,) or (n, k)
            Right-hand side(s).

        Returns
        -------
        ndarray, same shape as ``b``

        Raises
        ------
        SolverError
            If the right-hand side or the solution contains non-finite values.
        """
        b = np.asarray(b, dtype=float)
        if b.shape[0] != self.n:
            raise SolverError(f"right-hand side has {b.shape[0]} rows, matrix has {self.n}")
        if not np.all(np.isfinite(b)):
            raise SolverError("right-hand side contains non-finite values")
        if self._lu is None:
            return b.copy()
        x = self._lu.solve(b)
        if not np.all(np.isfinite(x)):
            raise SolverError("linear solve produced non-finite values")
        return x


class SuperLUSolver:
    """Default :class:`LinearSolver`: direct sparse LU."""

    def factorize(self, A: csr_matrix, symmetric: bool = False) -> SuperLUFactorization:
        """Factorise ``A`` (see :class:`SuperLUFactorization`)."""
        return SuperLUFactorization(A, symmetric)


_default_solver: LinearSolver = SuperLUSolver()


def default_solver() -> LinearSolver:
    """Return the linear solver used when none is given."""
    return _default_solver


def split_dofs(n_dofs: int, fixed_idx: ndarray) -> tuple[ndarray, ndarray]:
    """Split DOF numbers into free and prescribed sets.

    Parameters
    ----------
    n_dofs : int
        Total number of DOFs.
    fixed_idx : ndarray of int
        Prescribed DOF numbers (no duplicates).

    Returns
    -------
    free : ndarray of int64
        Free DOF numbers, ascending.
    fixed : ndarray of int64
        ``fixed_idx`` as int64, in the order given.
    """
    fixed = np.asarray(fixed_idx, dtype=np.int64).ravel()
    if fixed.size and (fixed.min() < 0 or fixed.max() >= n_dofs):
        raise SolverError("prescribed DOF index out of range")
    mask = np.ones(n_dofs, dtype=bool)
    mask[fixed] = False
    if n_dofs - int(mask.sum()) != fixed.size:
        raise SolverError("prescribed DOF indices contain duplicates")
    return np.flatnonzero(mask), fixed


def solve_partitioned(
    K: csr_matrix,
    F: ndarray,
    fixed_idx: ndarray,
    fixed_val: ndarray,
    *,
    symmetric: bool = False,
    solver: LinearSolver | None = None,
) -> ndarray:
    """Solve ``K T = F`` with prescribed values by partitioning (Theory §4).

    The DOFs are split into free (f) and prescribed (p) and
    ``K_ff T_f = F_f - K_fp T_p`` is solved. The penalty method is never used.

    Parameters
    ----------
    K : scipy.sparse matrix, shape (n, n)
        Global matrix [W/K].
    F : ndarray, shape (n,)
        Global load vector [W].
    fixed_idx : ndarray of int, shape (p,)
        Prescribed DOF numbers.
    fixed_val : ndarray, shape (p,)
        Prescribed values [K].
    symmetric : bool, keyword-only
        Hint that ``K`` is symmetric.
    solver : LinearSolver, keyword-only, optional
        Solver to use; defaults to :func:`default_solver`.

    Returns
    -------
    ndarray, shape (n,)
        Solution at every DOF, prescribed values included [K].

    Raises
    ------
    SolverError
        If the free system is singular or anything is non-finite.
    """
    K = csr_matrix(K)
    F = np.asarray(F, dtype=float)
    n = K.shape[0]
    if K.shape != (n, n) or F.shape != (n,):
        raise SolverError(f"system size mismatch: K {K.shape}, F {F.shape}")
    free, fixed = split_dofs(n, fixed_idx)
    values = np.asarray(fixed_val, dtype=float).ravel()
    if values.shape != fixed.shape:
        raise SolverError("fixed_idx and fixed_val have different lengths")
    if not np.all(np.isfinite(values)):
        raise SolverError("prescribed values contain non-finite values")

    T = np.empty(n)
    T[fixed] = values
    if free.size:
        K_f = K[free]
        rhs = F[free] - K_f[:, fixed] @ values
        fact = (solver or default_solver()).factorize(K_f[:, free].tocsr(), symmetric)
        T[free] = fact.solve(rhs)
    return T
