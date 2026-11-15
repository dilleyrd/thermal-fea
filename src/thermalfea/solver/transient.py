"""Transient driver: the theta-method (Theory §6). It knows only about terms.

With ``g(T, t) = F(T, t) - K(T) T + r_extra`` the heat-flow imbalance, the step from
``t_n`` to ``t_{n+1} = t_n + dt`` solves for ``T_{n+1}``

    R(T_{n+1}) = C(T_theta) (T_{n+1} - T_n) / dt
                 - theta g(T_{n+1}, t_{n+1}) - (1 - theta) g(T_n, t_n) = 0

with ``T_theta = theta T_{n+1} + (1 - theta) T_n`` used only to evaluate ``rho c``. The
tangent is ``A = C / dt + theta (K + K_tan)`` at the current iterate, the Newton update
solves ``A_ff dT_f = -R_f``, and the line search and convergence test are those of the
steady iteration with

    F_ref = max(|C (T_{n+1} - T_n) / dt|, |F|, |K T|, 1e-12).

``g(T_n, t_n)`` is kept from the end of the previous step, not recomputed. At a step where
a prescribed temperature or a load jumps discontinuously, ``theta = 1`` is used for that
one step. The first step is such a step whenever the initial state is not in equilibrium
with the loads: they are switched on at the start time. Prescribed temperatures are set
to their value at ``t_{n+1}`` before the first iteration. In the linear case ``A`` is
constant while ``dt`` is constant: it is factorised once and reused.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy import ndarray
from scipy.sparse import csr_matrix

from ..core.errors import ConvergenceError, ModelError
from .assembler import Assembler
from .linear import Factorization, LinearSolver, default_solver, split_dofs
from .nonlinear import F_REF_FLOOR, Assembled, newton
from .problem import CompiledProblem
from .steady import DEFAULT_START_TEMPERATURE, assemble
from .terms import State

log = logging.getLogger(__name__)

#: A load or prescribed value "jumps" at the start of a step when the change over the
#: first ``JUMP_PROBE`` of the step exceeds ``JUMP_FRACTION`` of its change over the whole
#: step. A continuous function changes by about ``JUMP_PROBE`` of it; a jump by all of it.
JUMP_PROBE = 1e-8
JUMP_FRACTION = 1e-3
#: An initial temperature differs from the prescribed value that replaces it (a jump at
#: the start) when they differ by more than this fraction of the value.
JUMP_TOL = 1e-6
_TIME_EPS = 1e-12  # relative tolerance when comparing times
_LAST_STEP_SLACK = 1e-9  # a remainder below this fraction of dt is merged into the last step


@dataclass
class StepRecord:
    """One accepted time step, as handed to the ``on_step`` callback.

    Attributes
    ----------
    step : int
        Step number, 1 for the first step (0 is the initial state).
    t : float
        Time at the end of the step [s].
    dt : float
        Step size [s].
    theta : float
        The theta actually used (1 on a discontinuity step).
    T : ndarray
        Solution at ``t`` [K].
    T_prev : ndarray
        Solution at ``t - dt`` [K].
    iterations : int
        Linear solves used.
    converged : bool
    residual : float
        ``|R_f|_2`` at the end of the step [W].
    system : Assembled
        ``K``, ``F``, ... assembled at ``(T, t)``.
    g_prev : ndarray
        ``g(T_prev, t - dt)`` [W].
    capacitance_rate : ndarray
        ``C (T - T_prev) / dt`` [W]; its sum is the rate of change of stored energy.
    """

    step: int
    t: float
    dt: float
    theta: float
    T: ndarray
    T_prev: ndarray
    iterations: int
    converged: bool
    residual: float
    system: Assembled
    g_prev: ndarray
    capacitance_rate: ndarray


@dataclass
class TransientResult:
    """Outcome of :func:`solve_transient`.

    Attributes
    ----------
    times : list of float
        Time of the initial state and of every accepted step [s].
    T : ndarray
        Solution at the last time [K].
    temperatures : list of ndarray
        Solution at every time in ``times`` (empty when ``store=False``).
    iterations : list of int
        Linear solves of every step.
    thetas : list of float
        Theta used by every step.
    cancelled : bool
        True when the ``on_step`` callback stopped the run.
    factorizations : int
        Number of matrix factorisations performed (linear path only).
    """

    times: list[float] = field(default_factory=list)
    T: ndarray | None = None
    temperatures: list[ndarray] = field(default_factory=list)
    iterations: list[int] = field(default_factory=list)
    thetas: list[float] = field(default_factory=list)
    cancelled: bool = False
    factorizations: int = 0

    @property
    def n_steps(self) -> int:
        """Number of accepted steps."""
        return len(self.times) - 1


def assemble_capacitance(
    problem: CompiledProblem, u: ndarray, t: float, u_prev: ndarray, dt: float | None
) -> csr_matrix:
    """Assemble ``C`` with ``rho c`` evaluated at ``u``.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray
        Temperature at which ``rho c`` is evaluated [K] (``T_theta`` in Theory §6).
    t : float
        Time [s].
    u_prev : ndarray
        Solution of the previous step [K].
    dt : float or None
        Time step [s].

    Returns
    -------
    csr_matrix
        Capacitance matrix [J/K].
    """
    state = State(u=u, u_prev=u_prev, t=t, dt=dt, dofs=problem.dofs)
    asm = Assembler(problem.dofs.n_dofs)
    for term in problem.terms:
        term.capacitance(state, asm)
    return asm.matrix()


class StepSystem:
    """The nonlinear system of one time step, in the form the Newton driver expects.

    ``residual(u)`` returns ``-R(u)`` so that the driver's ``tangent dT = residual`` is
    the update ``A dT = -R`` of Theory §6.
    """

    def __init__(
        self,
        base: Assembled,
        C: csr_matrix,
        u_prev: ndarray,
        g_prev: ndarray,
        dt: float,
        theta: float,
    ) -> None:
        self.base, self.C = base, C
        self.u_prev, self.g_prev = u_prev, g_prev
        self.dt, self.theta = dt, theta

    def rate(self, u: ndarray) -> ndarray:
        """``C (u - u_prev) / dt`` [W]."""
        return self.C @ (u - self.u_prev) / self.dt

    def residual(self, u: ndarray) -> ndarray:
        """``-R(u) = theta g(u) + (1 - theta) g_prev - C (u - u_prev) / dt`` [W]."""
        return (
            self.theta * self.base.residual(u) + (1.0 - self.theta) * self.g_prev - self.rate(u)
        )

    def tangent(self) -> csr_matrix:
        """``A = C / dt + theta (K + K_tan)`` [W/K]."""
        return (self.C / self.dt + self.theta * self.base.tangent()).tocsr()

    def reference(self, u: ndarray) -> float:
        """``F_ref = max(|C (u - u_prev) / dt|, |F|, |K u|, 1e-12)`` [W]."""
        return max(
            float(np.linalg.norm(self.rate(u))),
            float(np.linalg.norm(self.base.F)),
            float(np.linalg.norm(self.base.K @ u)),
            F_REF_FLOOR,
        )


def initial_state(problem: CompiledProblem, T0: ndarray | float | None, t0: float) -> tuple:
    """Initial solution with the prescribed values of ``t0`` applied.

    Returns
    -------
    T : ndarray
        Initial solution [K]; prescribed DOFs hold their boundary value at ``t0``.
    shock : bool
        True when a prescribed value differs from the initial temperature it replaces,
        that is, when a prescribed temperature jumps at ``t0``.
    """
    n = problem.dofs.n_dofs
    if T0 is None:
        value = DEFAULT_START_TEMPERATURE
        if problem.model is not None:
            ic = problem.model.initial_condition
            if ic.kind == "uniform" and ic.value is not None:
                value = float(ic.value())
        T = np.full(n, value)
    else:
        T = np.broadcast_to(np.asarray(T0, dtype=float), (n,)).copy()
    idx, values = problem.prescribed(t0)
    scale = max(1.0, float(np.abs(values).max())) if values.size else 1.0
    shock = bool(values.size and np.abs(T[idx] - values).max() > JUMP_TOL * scale)
    T[idx] = values
    return T, shock


def _jumps(
    problem: CompiledProblem, u: ndarray, t: float, dt: float, system: Assembled
) -> bool:
    """True if a prescribed value or a load changes discontinuously at time ``t``.

    The change just after ``t`` is compared with the change over the whole step: for a
    continuous function the former is a vanishing fraction of the latter, for a jump at
    ``t`` it is essentially all of it.
    """
    if not problem.is_time_dependent:
        return False
    probe, t_new = t + JUMP_PROBE * dt, t + dt

    def is_jump(early: ndarray, whole: ndarray) -> bool:
        change = float(np.abs(early).max()) if early.size else 0.0
        return change > 0.0 and change > JUMP_FRACTION * float(np.abs(whole).max())

    _, now = problem.prescribed(t)
    if is_jump(problem.prescribed(probe)[1] - now, problem.prescribed(t_new)[1] - now):
        return True
    g_now = system.residual(u)
    return is_jump(
        assemble(problem, u, probe).residual(u) - g_now,
        assemble(problem, u, t_new).residual(u) - g_now,
    )


def fixed_step_size(problem: CompiledProblem) -> float:
    """Step size of a fixed-step run: ``settings.initial_dt`` (required)."""
    dt = problem.settings.initial_dt
    if dt is None or not dt > 0.0:
        raise ModelError(
            "a fixed-step transient analysis needs a positive initial time step "
            "(solution.initial_dt), or automatic time stepping switched on"
        )
    return float(dt)


def solve_transient(
    problem: CompiledProblem,
    T0: ndarray | float | None = None,
    on_step: Callable[[StepRecord], bool | None] | None = None,
    *,
    t0: float = 0.0,
    store: bool = True,
    solver: LinearSolver | None = None,
) -> TransientResult:
    """Integrate in time with the theta-method at a fixed step (Theory §6).

    Parameters
    ----------
    problem : CompiledProblem
        ``problem.settings`` supplies ``end_time``, ``initial_dt`` (the step size),
        ``theta`` and the nonlinear tolerances.
    T0 : ndarray or float, optional
        Initial temperatures [K]; by default the model's uniform initial condition.
    on_step : callable, optional
        ``on_step(record: StepRecord)``, called after every accepted step; returning
        ``False`` stops the run cleanly.
    t0 : float, keyword-only
        Start time [s].
    store : bool, keyword-only
        Keep the solution of every step in the result.
    solver : LinearSolver, keyword-only, optional

    Returns
    -------
    TransientResult

    Raises
    ------
    ConvergenceError
        If a step does not converge.
    SolverError
        If a system is singular.
    ModelError
        If the settings are unusable.
    """
    settings = problem.settings
    solver = solver or default_solver()
    end = float(settings.end_time)
    if not end > t0:
        raise ModelError("the end time of a transient analysis must be after its start")
    dt_nominal = fixed_step_size(problem)
    symmetric = problem.symmetric
    linear = problem.is_linear

    T, shock = initial_state(problem, T0, t0)
    system = assemble(problem, T, t0)
    g = system.residual(T)
    # Loads applied to a body that is not in equilibrium with them at the start are a
    # discontinuity at t0 (the loads are, in effect, switched on there), as is an initial
    # temperature that differs from a prescribed one.
    free0, _ = split_dofs(T.size, problem.prescribed(t0)[0])
    # scale: the magnitude of the terms whose sum is g (K T cancels to round-off at rest)
    scale = max(
        float(np.linalg.norm(system.F)),
        float(np.linalg.norm(abs(system.K) @ np.abs(T))),
        F_REF_FLOOR,
    )
    startup = shock or bool(np.linalg.norm(g[free0]) > JUMP_TOL * scale)
    result = TransientResult(times=[t0], T=T.copy())
    if store:
        result.temperatures.append(T.copy())

    # data reused between the steps of a linear problem
    C_const = assemble_capacitance(problem, T, t0, T, None) if linear else None
    cached: dict[str, object] = {}

    t, step = t0, 0
    span = end - t0
    while end - t > _TIME_EPS * span:
        dt = dt_nominal
        if end - (t + dt) < _LAST_STEP_SLACK * dt:
            dt = end - t  # land exactly on the end time (absorbing round-off)
        t_new = t + dt
        discontinuous = (step == 0 and startup) or (
            settings.theta < 1.0 and _jumps(problem, T, t, dt, system)
        )
        theta = 1.0 if discontinuous else float(settings.theta)
        fixed_idx, fixed_val = problem.prescribed(t_new)

        if linear:
            base = system if not problem.is_time_dependent else assemble(problem, T, t_new, T, dt)
            A = (C_const / dt + theta * base.tangent()).tocsr()
            free, fixed_idx = split_dofs(T.size, fixed_idx)
            reuse = (
                cached.get("key") == (dt, theta)
                and np.array_equal(cached["free"], free)
                and (base is cached.get("base") or (A != cached["A"]).nnz == 0)
            )
            if not reuse:
                factor: Factorization | None = (
                    solver.factorize(A[free][:, free].tocsr(), symmetric) if free.size else None
                )
                cached.update(key=(dt, theta), free=free, base=base, A=A, factor=factor)
                result.factorizations += 1
            T_new = np.empty_like(T)
            T_new[fixed_idx] = fixed_val
            rhs = C_const @ T / dt + theta * (base.F + base.r_extra) + (1.0 - theta) * g
            if free.size:
                T_new[free] = cached["factor"].solve(  # type: ignore[union-attr]
                    rhs[free] - A[free][:, fixed_idx] @ fixed_val
                )
            step_system = StepSystem(base, C_const, T, g, dt, theta)
            residual = float(np.linalg.norm(step_system.residual(T_new)[free]))
            iterations, converged, new_system = 1, True, base
        else:

            def assemble_step(
                u: ndarray, t_new: float = t_new, dt: float = dt, theta: float = theta,
                T: ndarray = T, g: ndarray = g,
            ) -> StepSystem:
                base = assemble(problem, u, t_new, T, dt)
                C = assemble_capacitance(problem, theta * u + (1.0 - theta) * T, t_new, T, dt)
                return StepSystem(base, C, T, g, dt, theta)

            try:
                outcome = newton(
                    assemble_step, T, (fixed_idx, fixed_val), settings,  # type: ignore[arg-type]
                    symmetric=symmetric, solver=solver,
                )
            except ConvergenceError as exc:
                raise ConvergenceError(
                    f"step {step + 1} (t = {t_new:g} s, dt = {dt:g} s) did not converge: {exc}"
                ) from None
            T_new, iterations, converged = outcome.T, outcome.iterations, outcome.converged
            residual = outcome.residual
            step_system = outcome.system  # type: ignore[assignment]
            new_system = step_system.base

        rate = step_system.rate(T_new)
        g_new = new_system.residual(T_new)
        step += 1
        record = StepRecord(
            step=step, t=t_new, dt=dt, theta=theta, T=T_new, T_prev=T, iterations=iterations,
            converged=converged, residual=residual, system=new_system, g_prev=g,
            capacitance_rate=rate,
        )
        T, g, system, t = T_new, g_new, new_system, t_new
        result.times.append(t)
        result.iterations.append(iterations)
        result.thetas.append(theta)
        result.T = T
        if store:
            result.temperatures.append(T.copy())
        log.info(
            "step %d: t = %.6g s, dt = %.3g s, theta = %g, %d iteration(s), residual %.2e W",
            step, t, dt, theta, iterations, residual,
        )
        if on_step is not None and on_step(record) is False:
            result.cancelled = True
            log.info("transient run cancelled at t = %.6g s", t)
            break
    return result
