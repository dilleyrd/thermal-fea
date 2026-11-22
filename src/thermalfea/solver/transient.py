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
from .initial import initial_temperature
from .linear import Factorization, LinearSolver, default_solver, split_dofs
from .nonlinear import F_REF_FLOOR, Assembled, newton
from .problem import CompiledProblem
from .steady import assemble, update_providers
from .terms import State
from .timestep import StepController, error_estimate

log = logging.getLogger(__name__)

#: A load or prescribed value "jumps" at the start of a step when the change over the
#: first ``JUMP_PROBE`` of the step exceeds ``JUMP_FRACTION`` of its change over the whole
#: step. A continuous function changes by about ``JUMP_PROBE`` of it; a jump by all of it.
JUMP_PROBE = 1e-8
JUMP_FRACTION = 1e-3
#: An initial temperature differs from the prescribed value that replaces it (a jump at
#: the start) when they differ by more than this fraction of the value.
JUMP_TOL = 1e-6


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
    rejected : int
        Steps rejected by the time-stepping error test and redone with a smaller step.
    newton_failures : int
        Steps redone with a smaller step because the nonlinear iteration failed.
    """

    times: list[float] = field(default_factory=list)
    T: ndarray | None = None
    temperatures: list[ndarray] = field(default_factory=list)
    iterations: list[int] = field(default_factory=list)
    thetas: list[float] = field(default_factory=list)
    cancelled: bool = False
    factorizations: int = 0
    rejected: int = 0
    newton_failures: int = 0

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


def initial_state(
    problem: CompiledProblem, T0: ndarray | float | None, t0: float, resume: bool = False
) -> tuple:
    """Initial solution with the prescribed values of ``t0`` applied.

    Parameters
    ----------
    problem : CompiledProblem
    T0 : ndarray or float, optional
        Initial values [K]; by default the model's initial condition.
    t0 : float
        Start time [s].
    resume : bool
        ``T0`` is the full solution of an earlier run at ``t0``: the flow providers do
        not reset their unknowns to the start values.

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
        T = initial_temperature(problem)
    else:
        T = np.broadcast_to(np.asarray(T0, dtype=float), (n,)).copy()
    if resume:
        # the stored solution is the state: the providers (e.g. a pipe network that sets
        # a stream's mass flow) are brought up to date with it, their unknowns not reset
        update_providers(problem, State(u=T, u_prev=T, t=t0, dt=None, dofs=problem.dofs))
    else:
        for provider in problem.providers:
            initialize = getattr(provider, "initialize", None)
            if initialize is not None:
                initialize(T, t0)  # e.g. fluid nodes start at their inlet temperature
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
        assemble(problem, u, probe, update=False).residual(u) - g_now,
        assemble(problem, u, t_new, update=False).residual(u) - g_now,
    )


def first_step_size(problem: CompiledProblem, T: ndarray) -> float:
    """Size of the first step [s].

    ``settings.initial_dt`` when given; otherwise the suggestion of Theory §6.1
    (``h_min^2 / (4 alpha_max)``), which the problem supplies through its ``suggest_dt``
    hook. A fixed-step run always needs ``initial_dt``.
    """
    settings = problem.settings
    dt = settings.initial_dt
    if dt is not None:
        if not dt > 0.0:
            raise ModelError("the initial time step (solution.initial_dt) must be positive")
        return float(dt)
    if not settings.auto_timestep:
        raise ModelError(
            "a fixed-step transient analysis needs a positive initial time step "
            "(solution.initial_dt), or automatic time stepping switched on"
        )
    if problem.suggest_dt is None:
        raise ModelError(
            "no initial time step is given (solution.initial_dt) and the problem cannot "
            "suggest one"
        )
    dt = float(problem.suggest_dt(T))
    log.info("initial time step suggested from the mesh and materials: %.3g s", dt)
    return dt


def mandatory_times(problem: CompiledProblem) -> list[float]:
    """Times [s] a step must land on: output times and breakpoints of the loads."""
    settings = problem.settings
    times = list(problem.breakpoints())
    if settings.output == "times":
        times += [float(t) for t in settings.output_times]
    return times


def solve_transient(
    problem: CompiledProblem,
    T0: ndarray | float | None = None,
    on_step: Callable[[StepRecord], bool | None] | None = None,
    *,
    t0: float = 0.0,
    store: bool = True,
    solver: LinearSolver | None = None,
    resume: bool = False,
    dt0: float | None = None,
    first_step: int = 0,
) -> TransientResult:
    """Integrate in time with the theta-method (Theory §6, §6.1).

    With ``settings.auto_timestep`` the step size follows the error estimate of Theory
    §6.1; otherwise it is the fixed ``settings.initial_dt``. In both cases steps land
    exactly on the mandatory times (output times, load-table breakpoints, the end time).

    Parameters
    ----------
    problem : CompiledProblem
        ``problem.settings`` supplies the end time, the step controls, ``theta`` and the
        nonlinear tolerances.
    T0 : ndarray or float, optional
        Initial temperatures [K]; by default the model's initial condition.
    on_step : callable, optional
        ``on_step(record: StepRecord)``, called after every accepted step; returning
        ``False`` stops the run cleanly.
    t0 : float, keyword-only
        Start time [s].
    store : bool, keyword-only
        Keep the solution of every step in the result.
    solver : LinearSolver, keyword-only, optional
    resume : bool, keyword-only
        Continue an earlier run: ``T0`` is its full solution at ``t0``. The state is then
        not treated as the switching-on of the loads (no ``theta = 1`` start-up step
        unless a prescribed temperature differs from ``T0``), and ``g(T0, t0)`` is
        recomputed from ``T0``, which is what the earlier run kept.
    dt0 : float, keyword-only, optional
        Size of the first step [s] of an automatically stepped run, instead of
        ``settings.initial_dt`` or the suggestion of Theory §6.1.
    first_step : int, keyword-only
        Number of steps already taken; the first step is numbered ``first_step + 1``.

    Returns
    -------
    TransientResult

    Raises
    ------
    ConvergenceError
        If a step does not converge (after cutting the step down to ``dt_min`` when
        stepping is automatic).
    SolverError
        If a system is singular.
    ModelError
        If the settings are unusable.
    """
    settings = problem.settings
    solver = solver or default_solver()
    symmetric = problem.symmetric
    linear = problem.is_linear

    T, shock = initial_state(problem, T0, t0, resume)
    first_dt = dt0 if dt0 is not None and settings.auto_timestep else first_step_size(problem, T)
    controller = StepController(settings, t0, mandatory_times(problem), first_dt)
    if problem.check_dt is not None:
        problem.check_dt(T, controller.dt)
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
    # a resumed run is in the middle of its history: an imbalance is no switching-on
    startup = shock or (not resume and bool(np.linalg.norm(g[free0]) > JUMP_TOL * scale))

    result = TransientResult(times=[t0], T=T.copy())
    if store:
        result.temperatures.append(T.copy())

    # data reused between the steps of a linear problem
    C_const = assemble_capacitance(problem, T, t0, T, None) if linear else None
    cached: dict[str, object] = {}

    def attempt(dt: float, theta: float) -> tuple:
        """Solve one step from the current state; returns the new state and its systems."""
        t_new = controller.t + dt
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
            return T_new, 1, True, residual, step_system, base

        def assemble_step(u: ndarray) -> StepSystem:
            base = assemble(problem, u, t_new, T, dt, update=False)
            C = assemble_capacitance(problem, theta * u + (1.0 - theta) * T, t_new, T, dt)
            return StepSystem(base, C, T, g, dt, theta)

        def refresh_providers(u: ndarray) -> None:
            # once per iterate (Theory §9.2); line-search trials never update the providers
            update_providers(
                problem, State(u=u, u_prev=T, t=t_new, dt=dt, dofs=problem.dofs)
            )

        outcome = newton(
            assemble_step, T, (fixed_idx, fixed_val), settings,  # type: ignore[arg-type]
            symmetric=symmetric, solver=solver,
            refresh=refresh_providers if problem.providers else None,
        )
        step_system = outcome.system
        return (outcome.T, outcome.iterations, outcome.converged, outcome.residual,
                step_system, step_system.base)  # type: ignore[union-attr]

    step = int(first_step)
    T_before: ndarray | None = None  # the solution one step before T
    dt_before: float | None = None
    while not controller.finished:
        t = controller.t
        dt = controller.propose()
        discontinuous = (step == first_step and startup) or (
            settings.theta < 1.0 and _jumps(problem, T, t, dt, system)
        )
        theta = 1.0 if discontinuous else float(settings.theta)
        try:
            T_new, iterations, converged, residual, step_system, new_system = attempt(dt, theta)
        except ConvergenceError as exc:
            try:
                controller.newton_failed()
            except ConvergenceError as final:
                raise ConvergenceError(
                    f"step {step + 1} (t = {t + dt:g} s, dt = {dt:g} s) did not converge: "
                    f"{exc} [{final}]"
                ) from None
            result.newton_failures += 1
            continue

        error = error_estimate(T_new, T, T_before, dt, dt_before)
        if not controller.accept(error, float(np.abs(T_new - T).max())):
            result.rejected += 1
            continue

        rate = step_system.rate(T_new)
        g_new = new_system.residual(T_new)
        step += 1
        record = StepRecord(
            step=step, t=controller.t, dt=dt, theta=theta, T=T_new, T_prev=T,
            iterations=iterations, converged=converged, residual=residual, system=new_system,
            g_prev=g, capacitance_rate=rate,
        )
        T_before, dt_before = T, dt
        T, g, system = T_new, g_new, new_system
        result.times.append(controller.t)
        result.iterations.append(iterations)
        result.thetas.append(theta)
        result.T = T
        if store:
            result.temperatures.append(T.copy())
        log.info(
            "step %d: t = %.6g s, dt = %.3g s, theta = %g, %d iteration(s), residual %.2e W",
            step, controller.t, dt, theta, iterations, residual,
        )
        if on_step is not None and on_step(record) is False:
            result.cancelled = True
            log.info("transient run cancelled at t = %.6g s", controller.t)
            break
    return result
