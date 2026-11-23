"""Modified Newton iteration with line search (Theory §5).

The driver knows nothing about heat transfer. It is given a function that assembles the
system at a trial solution and returns ``K``, ``F``, the tangent-only matrix and the
residual-only vector (see :mod:`thermalfea.solver.terms`), and iterates

1. assemble ``K(T)``, ``F(T)``, ``K_tan(T)``, ``r(T) = F - K T + r_extra``;
2. solve ``(K + K_tan)_ff dT_f = r_f``;
3. line search: ``s = 1``; while ``|r(T + s dT)| > (1 - 1e-4 s) |r(T)|`` and
   ``s > 1/32``: ``s <- s / 2``;
4. ``T <- T + s dT``;
5. converged when ``|r_f|_2 <= rtol F_ref`` and ``|s dT|_inf <= ttol``, with
   ``F_ref = max(|F|_2, |K T|_2, 1e-12)``; the residual test also passes (round-off
   floor) when ``|r_f|_2 <= N eps (|(|K| |T|)_f|_2 + |F_f|_2 + |r_extra,f|_2)`` with
   ``N = 100``, and ``ttol`` is still required;
6. no convergence within the iteration limit raises ``ConvergenceError``.

An optional ``refresh(T)`` hook (the flow providers' update) is called once per iterate,
before the assembly at the start and again after each accepted update, never for a
line-search trial; the system is then assembled again at the accepted iterate.

Property derivatives (dk/dT, dh/dT) are deliberately not in the tangent. A trial solution
with any temperature at or below 0 K counts as a failed line-search step.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy import ndarray
from scipy.sparse import csr_matrix

from ..core.errors import ConvergenceError
from ..model.settings import SolutionSettings
from .linear import LinearSolver, default_solver, split_dofs

log = logging.getLogger(__name__)

ARMIJO = 1e-4  # sufficient-decrease factor of the line search
S_MIN = 1.0 / 32.0  # smallest line-search factor
F_REF_FLOOR = 1e-12
#: N of the round-off convergence test (Theory §5; the owner's choice, Q29.1 D1).
ROUNDOFF_FACTOR = 100.0
_EPS = float(np.finfo(float).eps)


def roundoff_level(K: csr_matrix, F: ndarray, r_extra: ndarray, u: ndarray, rows: ndarray) -> float:
    """``N eps (|(|K| |u|)_f|_2 + |F_f|_2 + |r_extra,f|_2)`` over the given rows [W].

    The residual of the round-off test of Theory §5: a free-row residual at most this large
    is at the round-off level of the sums that form it.
    """
    Ku = abs(K) @ np.abs(u)
    return ROUNDOFF_FACTOR * _EPS * (
        float(np.linalg.norm(Ku[rows]))
        + float(np.linalg.norm(F[rows]))
        + float(np.linalg.norm(r_extra[rows]))
    )


@dataclass
class Assembled:
    """The system assembled at one trial solution.

    Attributes
    ----------
    K : csr_matrix
        Conductance matrix [W/K].
    F : ndarray
        Load vector [W].
    K_tan : csr_matrix
        Tangent-only matrix (for example ``K_rad``) [W/K].
    r_extra : ndarray
        Residual-only vector (for example ``r_rad``) [W].
    """

    K: csr_matrix
    F: ndarray
    K_tan: csr_matrix
    r_extra: ndarray

    def residual(self, u: ndarray) -> ndarray:
        """``r(u) = F - K u + r_extra`` [W]."""
        return self.F - self.K @ u + self.r_extra

    def tangent(self) -> csr_matrix:
        """``K + K_tan`` [W/K]."""
        return (self.K + self.K_tan).tocsr()

    def reference(self, u: ndarray) -> float:
        """``F_ref = max(|F|_2, |K u|_2, 1e-12)`` [W]."""
        return max(float(np.linalg.norm(self.F)), float(np.linalg.norm(self.K @ u)), F_REF_FLOOR)

    def roundoff(self, u: ndarray, free: ndarray) -> float:
        """Residual level of the round-off test (Theory §5) on the free rows [W]."""
        return roundoff_level(self.K, self.F, self.r_extra, u, free)


@dataclass
class IterationRecord:
    """What happened in one Newton iteration."""

    iteration: int
    residual: float  # |r_f|_2 after the update [W]
    max_dT: float  # |s dT|_inf [K]
    step: float  # line-search factor s


@dataclass
class NewtonResult:
    """Outcome of :func:`newton`.

    Attributes
    ----------
    T : ndarray
        Solution at every DOF [K].
    iterations : int
        Number of linear solves performed.
    converged : bool
    residual : float
        ``|r_f|_2`` at the solution [W].
    reference : float
        ``F_ref`` at the solution [W].
    history : list of IterationRecord
    system : Assembled
        The system assembled at the solution (for reactions and the energy balance).
    """

    T: ndarray
    iterations: int
    converged: bool
    residual: float
    reference: float
    history: list[IterationRecord] = field(default_factory=list)
    system: Assembled | None = None


def newton(
    assemble_fn: Callable[[ndarray], Assembled],
    T0: ndarray,
    fixed: tuple[ndarray, ndarray],
    settings: SolutionSettings,
    *,
    symmetric: bool = False,
    solver: LinearSolver | None = None,
    refresh: Callable[[ndarray], None] | None = None,
) -> NewtonResult:
    """Solve ``r(T) = 0`` by modified Newton iteration with line search (Theory §5).

    Parameters
    ----------
    assemble_fn : callable
        ``assemble_fn(T) -> Assembled`` evaluated with properties and coefficients at
        ``T``.
    T0 : ndarray, shape (n,)
        Initial guess [K].
    fixed : (ndarray of int, ndarray)
        Prescribed DOF numbers and their values [K].
    settings : SolutionSettings
        Uses ``rtol``, ``ttol``, ``max_iterations`` and ``line_search``.
    symmetric : bool, keyword-only
        Hint for the linear solver.
    solver : LinearSolver, keyword-only, optional
        Defaults to :func:`thermalfea.solver.linear.default_solver`.
    refresh : callable, keyword-only, optional
        ``refresh(T)`` updates state that ``assemble_fn`` reads but that must change at most
        once per iteration (the flow providers, Theory §9.2). It is called once before the
        first assembly and once after each accepted update, each time followed by a fresh
        ``assemble_fn(T)`` at that iterate: exactly ``1 + iterations`` calls. Line-search
        trials never call it. Without it no extra assembly is made.

    Returns
    -------
    NewtonResult

    Raises
    ------
    ConvergenceError
        If the iteration limit is reached, or a temperature at or below 0 K (or a
        non-finite residual) cannot be avoided by shortening the step.
    SolverError
        If the tangent matrix is singular.
    """
    solver = solver or default_solver()
    T = np.array(T0, dtype=float)
    fixed_idx, fixed_val = fixed
    free, fixed_idx = split_dofs(T.size, fixed_idx)
    T[fixed_idx] = np.asarray(fixed_val, dtype=float)

    if refresh is not None:
        refresh(T)
    system = assemble_fn(T)
    r = system.residual(T)
    norm_r = float(np.linalg.norm(r[free]))
    history: list[IterationRecord] = []

    for iteration in range(1, settings.max_iterations + 1):
        # step 2: solve the tangent system on the free DOFs
        dT = np.zeros_like(T)
        if free.size:
            A = system.tangent()
            dT[free] = solver.factorize(A[free][:, free].tocsr(), symmetric).solve(r[free])

        # step 3: line search (a non-positive temperature, a non-finite residual or a
        # ConvergenceError of the trial assembly counts as a failed trial)
        s = 1.0
        while True:
            trial = T + s * dT
            usable = bool(np.all(np.isfinite(trial)) and trial.min() > 0.0)
            if usable:
                try:
                    trial_system = assemble_fn(trial)
                    trial_r = trial_system.residual(trial)
                    trial_norm = float(np.linalg.norm(trial_r[free]))
                    usable = bool(np.isfinite(trial_norm))
                except ConvergenceError:  # e.g. a film temperature below 0 K at some point
                    usable = False
            decreased = usable and trial_norm <= (1.0 - ARMIJO * s) * norm_r
            if decreased or (usable and not settings.line_search) or s <= S_MIN:
                break
            s *= 0.5
        if not usable:
            raise ConvergenceError(
                f"iteration {iteration}: the temperature became zero or negative (or the "
                "residual non-finite) and shortening the step did not help. Check that "
                "temperatures are absolute and that the loads are reasonable."
            )

        # step 4: update
        T, system, r, norm_r = trial, trial_system, trial_r, trial_norm
        if refresh is not None:
            # once per accepted iterate: the trial system was assembled with the previous
            # state of whatever ``refresh`` updates, so assemble again at the accepted T
            refresh(T)
            system = assemble_fn(T)
            r = system.residual(T)
            norm_r = float(np.linalg.norm(r[free]))
        max_dT = float(np.abs(s * dT).max()) if dT.size else 0.0
        reference = system.reference(T)
        history.append(IterationRecord(iteration, norm_r, max_dT, s))
        log.info(
            "iteration %2d: residual %.3e W (%.2e of reference), max dT %.3e K, "
            "line-search factor %g",
            iteration, norm_r, norm_r / reference, max_dT, s,
        )

        # step 5: convergence test; the residual allowance never falls below the round-off
        # level of the assembled terms (it matters when F_ref has collapsed to round-off)
        roundoff = system.roundoff(T, free)
        allowance = max(settings.rtol * reference, roundoff)
        if norm_r <= allowance and max_dT <= settings.ttol:
            if norm_r > settings.rtol * reference:
                log.info(
                    "converged: residual %.3e W is at the round-off level %.3e W",
                    norm_r, roundoff,
                )
            return NewtonResult(T, iteration, True, norm_r, reference, history, system)

    # step 6
    raise ConvergenceError(
        f"no convergence in {settings.max_iterations} iterations: residual "
        f"{norm_r:.3e} W ({norm_r / reference:.2e} of the reference, tolerance "
        f"{settings.rtol:g}), last temperature change {max_dT:.3e} K (tolerance "
        f"{settings.ttol:g} K)"
    )
