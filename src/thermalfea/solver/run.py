"""Runs a compiled problem and streams its results to a file."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy import ndarray

from ..model.settings import SolutionSettings
from ..post.energy import EnergyBalance, energy_balance, step_energy_balance
from ..post.reactions import term_heats
from .problem import CompiledProblem
from .results_writer import ResultsWriter
from .steady import STEADY_TIME, steady_solution
from .terms import State
from .transient import StepRecord, TransientResult, initial_state, solve_transient

log = logging.getLogger(__name__)


@dataclass
class StepInfo:
    """What the progress callback is told after each step (Data §11).

    Attributes
    ----------
    step : int
        Index of the step just finished (0 for a steady solution).
    time : float
        Its time [s].
    dt : float
        The time step that led to it [s] (0 when steady).
    iterations : int
        Iterations it took.
    converged : bool
    residual : float
        Final residual norm [W].
    end_time : float
        Time at which the analysis ends [s] (equal to ``time`` when steady).
    """

    step: int
    time: float
    dt: float
    iterations: int
    converged: bool
    residual: float
    end_time: float


ProgressCallback = Callable[[StepInfo], bool]


def log_balance(balance: EnergyBalance) -> None:
    """Write the energy balance to the log (Plan §6: every solve prints one)."""
    log.info("energy balance [W], positive into the body:\n%s", balance.format())


def flow_results(
    problem: CompiledProblem, u: ndarray, t: float, u_prev: ndarray | None = None,
    dt: float | None = None,
) -> dict[str, ndarray]:
    """Per-step results of every flow provider, keyed ``"<quantity>:<stream>"``.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray, shape (n_dofs,)
        Solution [K].
    t : float
        Time [s].
    u_prev : ndarray, optional
        Solution of the previous step; defaults to ``u``.
    dt : float, optional
        Time step [s].
    """
    if not problem.providers:
        return {}
    state = State(u=u, u_prev=u if u_prev is None else u_prev, t=t, dt=dt, dofs=problem.dofs)
    out: dict[str, ndarray] = {}
    for provider in problem.providers:
        out.update(provider.results(state))
    return out


def run_steady(
    problem: CompiledProblem, path: str | Path, progress: ProgressCallback | None = None
) -> None:
    """Solve a steady problem and write a one-step results file.

    Parameters
    ----------
    problem : CompiledProblem
    path : str or Path
        Results file to create.
    progress : callable, optional
        Called once, after the solve.

    Raises
    ------
    ConvergenceError, SolverError
        If the solution fails; no results file is written in that case.
    """
    result = steady_solution(problem)
    balance = energy_balance(problem, result.T, STEADY_TIME, system=result.system)
    log_balance(balance)
    with ResultsWriter(path, problem) as writer:
        writer.append_step(
            STEADY_TIME, result.T, dt=0.0, iterations=result.iterations,
            converged=result.converged, balance=balance,
            extras=flow_results(problem, result.T, STEADY_TIME),
        )
    if progress is not None:
        progress(
            StepInfo(0, STEADY_TIME, 0.0, result.iterations, result.converged, result.residual,
                     STEADY_TIME)
        )


#: The results file is flushed to disk after this many stored steps, so that a crashed
#: or cancelled run leaves a readable file.
FLUSH_EVERY = 10
_TIME_TOL = 1e-9


class OutputSelector:
    """Decides which steps of a transient run are stored (``settings.output``).

    * ``"all"``: every step;
    * ``"every_n"``: every ``output_every``-th step;
    * ``"times"``: the steps at the requested ``output_times``.

    The initial state and the last step are always stored.

    Parameters
    ----------
    settings : SolutionSettings
    """

    def __init__(self, settings: SolutionSettings) -> None:
        self.kind = settings.output
        self.every = int(settings.output_every)
        self.times = np.sort(np.asarray(settings.output_times, dtype=float))
        self.end = float(settings.end_time)

    def _is(self, t: float, target: float) -> bool:
        return abs(t - target) <= _TIME_TOL * max(1.0, abs(target))

    def wanted(self, step: int, t: float) -> bool:
        """True if the step numbered ``step`` at time ``t`` [s] is to be stored."""
        if step == 0 or self._is(t, self.end) or self.kind == "all":
            return True
        if self.kind == "every_n":
            return step % self.every == 0
        if self.times.size == 0:
            return False
        nearest = self.times[np.argmin(np.abs(self.times - t))]
        return self._is(t, float(nearest))


def run_transient(
    problem: CompiledProblem,
    path: str | Path,
    progress: ProgressCallback | None = None,
    T0: ndarray | float | None = None,
    t0: float = 0.0,
) -> TransientResult:
    """Solve a transient problem, streaming the selected steps to a results file.

    The initial state is stored first; each stored step carries its energy balance and
    the heat flow of every boundary condition. The file is flushed every
    :data:`FLUSH_EVERY` stored steps, and it is closed properly whether the run finishes,
    is cancelled by the progress callback or fails, so it is always readable.

    Parameters
    ----------
    problem : CompiledProblem
    path : str or Path
        Results file to create.
    progress : callable, optional
        ``progress(info: StepInfo) -> bool``, called after every step; returning ``False``
        cancels the run cleanly (the last computed step is stored).
    T0 : ndarray or float, optional
        Initial temperatures [K]; by default the model's initial condition.
    t0 : float
        Start time [s].

    Returns
    -------
    TransientResult
        Without the stored temperatures (they are in the file).

    Raises
    ------
    ConvergenceError, SolverError
        If the solution fails; the steps stored before the failure remain in the file.
    """
    settings = problem.settings
    selector = OutputSelector(settings)
    start, _ = initial_state(problem, T0, t0)
    heats = term_heats(problem, start, t0)
    last: dict[str, object] = {"balance": None}

    with ResultsWriter(path, problem) as writer:
        writer.append_step(
            t0, start, dt=0.0, iterations=0, converged=True,
            extras=flow_results(problem, start, t0),
        )
        writer.flush()

        def store(record: StepRecord, balance: EnergyBalance, extras: dict) -> None:
            writer.append_step(
                record.t, record.T, dt=record.dt, iterations=record.iterations,
                converged=record.converged, balance=balance, extras=extras,
            )
            if writer.n_steps % FLUSH_EVERY == 0:
                writer.flush()

        def on_step(record: StepRecord) -> bool:
            nonlocal heats
            balance, heats = step_energy_balance(
                problem, record.theta, record.t, record.dt, record.T, record.T_prev,
                record.system.residual(record.T), record.g_prev, record.capacitance_rate, heats,
            )
            stored = selector.wanted(record.step, record.t)
            # taken now: the flow solution moves on with the next step
            extras = flow_results(problem, record.T, record.t, record.T_prev, record.dt)
            if stored:
                store(record, balance, extras)
            last.update(record=record, balance=balance, stored=stored, extras=extras)
            if progress is None:
                return True
            keep_going = progress(
                StepInfo(record.step, record.t, record.dt, record.iterations, record.converged,
                         record.residual, float(settings.end_time))
            )
            return keep_going is not False

        # the driver gets the original T0, so that it can see a jump of a prescribed
        # temperature at the start
        result = solve_transient(problem, T0, on_step, t0=t0, store=False)
        if result.cancelled and not last.get("stored", True):
            store(last["record"], last["balance"], last["extras"])  # type: ignore[arg-type]

    if last["balance"] is not None:
        log_balance(last["balance"])  # type: ignore[arg-type]
    log.info(
        "transient run %s at t = %.6g s: %d step(s), %d rejected, %d Newton failure(s)",
        "cancelled" if result.cancelled else "finished", result.times[-1], result.n_steps,
        result.rejected, result.newton_failures,
    )
    return result
