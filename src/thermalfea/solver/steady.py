"""Steady-state driver. It loops over ``problem.terms`` and knows no physics (Plan §7)."""

from __future__ import annotations

import logging

import numpy as np
from numpy import ndarray

from .assembler import Assembler
from .linear import LinearSolver, default_solver, solve_partitioned
from .nonlinear import Assembled, NewtonResult, newton
from .problem import CompiledProblem
from .terms import State

log = logging.getLogger(__name__)

#: Time [s] at which loads are evaluated in a steady analysis.
STEADY_TIME = 0.0
#: Uniform starting temperature [K] of the nonlinear iteration when nothing better is
#: known (20 degC, the same placeholder as a new model's initial condition).
DEFAULT_START_TEMPERATURE = 293.15


def assemble(
    problem: CompiledProblem,
    u: ndarray,
    t: float = STEADY_TIME,
    u_prev: ndarray | None = None,
    dt: float | None = None,
) -> Assembled:
    """Assemble ``K``, ``F``, the tangent-only matrix and the residual-only vector.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray, shape (n_dofs,)
        Solution at which properties and coefficients are evaluated [K].
    t : float
        Time [s] at which loads are evaluated.
    u_prev : ndarray, optional
        Solution of the previous step; defaults to ``u``.
    dt : float, optional
        Time step [s].

    Returns
    -------
    Assembled
    """
    state = State(u=u, u_prev=u if u_prev is None else u_prev, t=t, dt=dt, dofs=problem.dofs)
    for provider in problem.providers:
        provider.update(state)  # e.g. lagged hydraulics; the drivers know only this call
    asm = Assembler(problem.dofs.n_dofs)
    for term in problem.terms:
        term.conductance(state, asm)
        term.load(state, asm)
    return Assembled(asm.matrix(), asm.vector(), asm.tangent(), asm.residual())


def starting_temperature(problem: CompiledProblem, fixed_val: ndarray) -> ndarray:
    """Uniform initial guess for the nonlinear iteration [K].

    The mean of the prescribed temperatures when there are any; otherwise the model's
    uniform initial condition; otherwise :data:`DEFAULT_START_TEMPERATURE`.
    """
    value = DEFAULT_START_TEMPERATURE
    if fixed_val.size:
        value = float(np.mean(fixed_val))
    elif problem.model is not None:
        ic = problem.model.initial_condition
        if ic.kind == "uniform" and ic.value is not None:
            value = float(ic.value())
    return np.full(problem.dofs.n_dofs, value)


def steady_solution(
    problem: CompiledProblem,
    T0: ndarray | None = None,
    t: float = STEADY_TIME,
    solver: LinearSolver | None = None,
) -> NewtonResult:
    """Solve the steady problem and return the full iteration record.

    A linear problem (no term depends on the solution) takes exactly one linear solve
    with no iteration; otherwise the modified Newton iteration of Theory §5 is used.

    Parameters
    ----------
    problem : CompiledProblem
    T0 : ndarray, optional
        Initial guess [K] for a nonlinear problem; see :func:`starting_temperature`.
    t : float
        Time [s] at which loads and prescribed values are evaluated.
    solver : LinearSolver, optional

    Returns
    -------
    NewtonResult

    Raises
    ------
    ConvergenceError
        If the nonlinear iteration fails.
    SolverError
        If the system is singular (for example no temperature reference).
    """
    solver = solver or default_solver()
    fixed_idx, fixed_val = problem.prescribed(t)

    if problem.is_linear:
        zero = np.zeros(problem.dofs.n_dofs)
        system = assemble(problem, zero, t)
        T = solve_partitioned(
            system.tangent(),
            system.F + system.r_extra,
            fixed_idx,
            fixed_val,
            symmetric=problem.symmetric,
            solver=solver,
        )
        mask = np.ones(T.size, dtype=bool)
        mask[fixed_idx] = False
        residual = float(np.linalg.norm(system.residual(T)[mask]))
        log.info("linear problem: one solve, residual %.3e W", residual)
        return NewtonResult(T, 1, True, residual, system.reference(T), [], system)

    start = starting_temperature(problem, fixed_val) if T0 is None else np.array(T0, float)
    return newton(
        lambda u: assemble(problem, u, t),
        start,
        (fixed_idx, fixed_val),
        problem.settings,
        symmetric=problem.symmetric,
        solver=solver,
    )


def solve_steady(problem: CompiledProblem) -> ndarray:
    """Solve the steady problem.

    Parameters
    ----------
    problem : CompiledProblem

    Returns
    -------
    ndarray, shape (n_dofs,)
        The solution at every DOF [K]; node temperatures are
        ``T[problem.dofs.field_dofs("T")]``.

    Raises
    ------
    ConvergenceError, SolverError
        See :func:`steady_solution`.
    """
    return steady_solution(problem).T
