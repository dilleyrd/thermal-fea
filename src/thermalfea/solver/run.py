"""Runs a compiled problem and streams its results to a file."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..post.energy import EnergyBalance, energy_balance
from .problem import CompiledProblem
from .results_writer import ResultsWriter
from .steady import STEADY_TIME, steady_solution

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
        )
    if progress is not None:
        progress(
            StepInfo(0, STEADY_TIME, 0.0, result.iterations, result.converged, result.residual,
                     STEADY_TIME)
        )
