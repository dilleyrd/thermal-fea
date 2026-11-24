"""Transient driver: the theta-method (Theory §6). It knows only about terms.

With ``g(T, t) = F(T, t) - K(T) T + r_extra`` the heat-flow imbalance, the step from
``t_n`` to ``t_{n+1} = t_n + dt`` solves for ``T_{n+1}``

    R(T_{n+1}) = C(T_theta) (T_{n+1} - T_n) / dt
                 - theta g(T_{n+1}, t_{n+1}) - (1 - theta) g(T_n, t_n) = 0

with ``T_theta = theta T_{n+1} + (1 - theta) T_n`` used only to evaluate ``rho c``. The
tangent is ``A = C / dt + theta (K + K_tan)`` at the current iterate, the Newton update
solves ``A_ff dT_f = -R_f``, and the line search and convergence test are those of the
steady iteration with

    F_ref = max(|C (T_{n+1} - T_n) / dt|, |F|, |K T|, 1e-12);

the round-off floor of the steady iteration uses ``K``, ``F`` and ``r_extra`` assembled at
the iterate.

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
from scipy.sparse import csr_matrix, diags

from ..core.errors import ConvergenceError, ModelError
from .assembler import Assembler
from .initial import initial_temperature
from .linear import Factorization, LinearSolver, default_solver, split_dofs
from .nonlinear import F_REF_FLOOR, Assembled, newton
from .problem import CompiledProblem
from .steady import assemble, update_providers
from .terms import State
from .timestep import StepController, error_estimate, same_time

log = logging.getLogger(__name__)

#: Local jump test (Theory §6): the probe times are ``t +- JUMP_PROBE * dt`` and twice that
#: (at least a few round-off units of ``t``). A jump at ``t`` shows as a change ``c1`` between
#: ``t`` and the first probe that is larger than ``JUMP_TOL`` of the scale while the change
#: ``c2`` between the two probes is below ``JUMP_FRACTION`` of ``c1``; a continuous function or a
#: kink has ``c2`` about equal to ``c1``.
JUMP_PROBE = 1e-8
JUMP_FRACTION = 1e-3
#: An initial temperature differs from the prescribed value that replaces it (a jump at
#: the start) when they differ by more than this fraction of the value; also the threshold
#: ``c1`` of the jump test, as a fraction of the scale.
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
    row_theta : float or ndarray
        The theta of every row: ``theta``, except 1 on the rows without capacitance
        (Theory §6); a single number when all rows use the same.
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
    row_theta: float | ndarray | None = None


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
    the update ``A dT = -R`` of Theory §6. ``theta`` is one number, or one per row (1 on
    the rows without capacitance, Theory §6).
    """

    def __init__(
        self,
        base: Assembled,
        C: csr_matrix,
        u_prev: ndarray,
        g_prev: ndarray,
        dt: float,
        theta: float | ndarray,
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
        """``A = C / dt + theta (K + K_tan)`` [W/K], row by row."""
        return (self.C / self.dt + _row_scaled(self.theta, self.base.tangent())).tocsr()

    def reference(self, u: ndarray) -> float:
        """``F_ref = max(|C (u - u_prev) / dt|, |F|, |K u|, 1e-12)`` [W]."""
        return max(
            float(np.linalg.norm(self.rate(u))),
            float(np.linalg.norm(self.base.F)),
            float(np.linalg.norm(self.base.K @ u)),
            F_REF_FLOOR,
        )

    def roundoff(self, u: ndarray, free: ndarray) -> float:
        """Residual level of the round-off test (Theory §5, §6) on the free rows [W]."""
        return self.base.roundoff(u, free)


def _row_scaled(theta: float | ndarray, M: csr_matrix) -> csr_matrix:
    """``theta M`` with ``theta`` one number or one factor per row."""
    if np.ndim(theta) == 0:
        return theta * M
    return diags(np.asarray(theta, dtype=float)) @ M


def _resolve_algebraic(
    problem: CompiledProblem, T: ndarray, t0: float, algebraic: ndarray, solver: LinearSolver
) -> ndarray:
    """Solve the free rows without capacitance for the rest of ``T`` held fixed (Theory §6).

    On a restart the stored fluid temperatures belong to the data of the earlier run; they
    are brought into balance with the stored wall temperatures and the current data
    (``g_r(T, t0) = 0`` on those rows) before ``g(T0, t0)`` is built.
    """
    fixed_idx, fixed_val = problem.prescribed(t0)
    rows = algebraic.copy()
    rows[fixed_idx] = False
    if not rows.any():
        return T
    T = T.copy()
    T[fixed_idx] = fixed_val
    held = np.flatnonzero(~rows)

    def refresh(u: ndarray) -> None:
        update_providers(problem, State(u=u, u_prev=u, t=t0, dt=None, dofs=problem.dofs))

    outcome = newton(
        lambda u: assemble(problem, u, t0, update=False), T, (held, T[held]), problem.settings,
        symmetric=False, solver=solver, refresh=refresh if problem.providers else None,
    )
    log.info(
        "restart: %d fluid temperature(s) re-solved for the stored walls (%d iteration(s))",
        int(rows.sum()), outcome.iterations,
    )
    return outcome.T


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
    problem: CompiledProblem,
    u: ndarray,
    t: float,
    dt: float,
    system: Assembled,
    *,
    left: bool = True,
) -> bool:
    """True if a prescribed value or a load changes discontinuously at time ``t`` (Theory §6).

    Two quantities are probed: the prescribed values and ``g(u, .)``. For each, with probe
    spacing ``delta`` and ``c1 = |f(t + delta) - f(t)|``, ``c2 = |f(t + 2 delta) - f(t + delta)|``,
    a jump is ``c1 > JUMP_TOL * scale`` and ``c2 < JUMP_FRACTION * c1``. The same test on the
    left (``t - delta``, ``t - 2 delta``) finds a function continuous from the right that
    jumps at ``t`` itself; it is skipped when ``left`` is False (first step of a run). The
    test is local, so a load that is periodic over the step is not a jump, nor is a kink.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray
        Solution at ``t`` [K].
    t, dt : float
        Start time and size of the step [s].
    system : Assembled
        The system assembled at ``(u, t)``.
    left : bool, keyword-only
        Also test the left side of ``t``.
    """
    if not problem.is_time_dependent:
        return False
    delta = max(JUMP_PROBE * dt, 4.0 * float(np.spacing(abs(t))))
    sides = [1.0, -1.0] if left else [1.0]
    probes = [(t + s * delta, t + 2.0 * s * delta) for s in sides]

    def is_jump(f0, f1, f2, scale: float) -> bool:
        c1, c2 = float(np.abs(f1 - f0).max()), float(np.abs(f2 - f1).max())
        return c1 > JUMP_TOL * scale and c2 < JUMP_FRACTION * c1

    idx0, val0, _ = problem._prescribed(t, warn=False)
    if val0.size:
        scale = float(np.abs(val0).max())
        for first, second in probes:
            i1, v1, _ = problem._prescribed(first, warn=False)
            i2, v2, _ = problem._prescribed(second, warn=False)
            if not (np.array_equal(i1, idx0) and np.array_equal(i2, idx0)):
                return True
            if is_jump(val0, v1, v2, scale):
                return True
    g0 = system.residual(u)
    scale = max(
        float(np.abs(system.F).max()) if system.F.size else 0.0,
        float(np.abs(abs(system.K) @ np.abs(u)).max()) if u.size else 0.0,
    )
    if not scale > 0.0:
        scale = F_REF_FLOOR
    for first, second in probes:
        g1 = assemble(problem, u, first, update=False).residual(u)
        g2 = assemble(problem, u, second, update=False).residual(u)
        if is_jump(g0, g1, g2, scale):
            return True
    return False


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
    given_dt0 = dt0 is not None and settings.auto_timestep
    first_dt = dt0 if given_dt0 else first_step_size(problem, T)
    controller = StepController(settings, t0, mandatory_times(problem), first_dt)
    # Theory §6.1: the oscillation warning is checked once, for the first step, and is not
    # logged when that step is the suggested initial step (M11.10, Q27.3)
    suggested = not given_dt0 and settings.initial_dt is None
    if problem.check_dt is not None and not suggested:
        problem.check_dt(T, controller.dt)

    # DOFs with capacitance (a nonzero row of C): the solid temperatures. A row without
    # capacitance (a fluid row of a stream) is algebraic and stepped with theta = 1 (§6).
    C_const = assemble_capacitance(problem, T, t0, T, None) if linear else None
    C_cap = C_const if C_const is not None else assemble_capacitance(problem, T, t0, T, None)
    cap_rows = np.flatnonzero(np.asarray(abs(C_cap).sum(axis=1)).ravel() > 0.0)
    algebraic = np.ones(T.size, dtype=bool)
    algebraic[cap_rows] = False
    if resume and algebraic.any():
        T = _resolve_algebraic(problem, T, t0, algebraic, solver)

    def row_theta(theta: float) -> float | ndarray:
        """The theta of every row: 1 for a row without capacitance, ``theta`` otherwise."""
        if theta == 1.0 or not algebraic.any():
            return theta
        return np.where(algebraic, 1.0, theta)

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
    cached: dict[str, object] = {}
    breakpoints = problem.breakpoints()

    def attempt(dt: float, theta: float) -> tuple:
        """Solve one step from the current state; returns the new state and its systems."""
        t_new = controller.t + dt
        fixed_idx, fixed_val = problem.prescribed(t_new)
        theta_r = row_theta(theta)
        if linear:
            base = system if not problem.is_time_dependent else assemble(problem, T, t_new, T, dt)
            A = (C_const / dt + _row_scaled(theta_r, base.tangent())).tocsr()
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
            rhs = C_const @ T / dt + theta_r * (base.F + base.r_extra) + (1.0 - theta_r) * g
            if free.size:
                T_new[free] = cached["factor"].solve(  # type: ignore[union-attr]
                    rhs[free] - A[free][:, fixed_idx] @ fixed_val
                )
            step_system = StepSystem(base, C_const, T, g, dt, theta_r)
            residual = float(np.linalg.norm(step_system.residual(T_new)[free]))
            return T_new, 1, True, residual, step_system, base

        def assemble_step(u: ndarray) -> StepSystem:
            base = assemble(problem, u, t_new, T, dt, update=False)
            # rho c at T_theta, with the solid's theta (a row without capacitance has no C)
            C = assemble_capacitance(problem, theta * u + (1.0 - theta) * T, t_new, T, dt)
            return StepSystem(base, C, T, g, dt, theta_r)

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
        first = step == first_step  # the first step of this call
        jump = settings.theta < 1.0 and _jumps(problem, T, t, dt, system, left=not first)
        discontinuous = (first and startup) or jump
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

        # the DOFs that are free at the end of the step (a prescribed one follows its history)
        free = split_dofs(T.size, problem.prescribed_owners(controller.t + dt)[0])[0]
        change = float(np.abs(T_new[free] - T[free]).max()) if free.size else 0.0
        restart = T_before is not None and (
            discontinuous or any(same_time(t, b) for b in breakpoints)
        )
        if restart:
            # outgoing side of a physical breakpoint: the history before it is of a different
            # function, so T_pred = T_n (zeroth order), taken over the solid free DOFs only
            error = error_estimate(
                T_new, T, T, dt, dt, free=np.intersect1d(free, cap_rows)
            )
        else:
            error = error_estimate(T_new, T, T_before, dt, dt_before, free=free)
        if not controller.accept(error, change):
            result.rejected += 1
            continue

        rate = step_system.rate(T_new)
        g_new = new_system.residual(T_new)
        step += 1
        record = StepRecord(
            step=step, t=controller.t, dt=dt, theta=theta, T=T_new, T_prev=T,
            iterations=iterations, converged=converged, residual=residual, system=new_system,
            g_prev=g, capacitance_rate=rate, row_theta=row_theta(theta),
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
