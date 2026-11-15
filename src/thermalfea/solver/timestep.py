"""Time-step control (Theory §6.1). Pure bookkeeping: it knows nothing about heat transfer.

After a converged step the predictor ``T_pred = T_n + (dt / dt_prev) (T_n - T_{n-1})`` is
compared with the solution:

    e = |T_{n+1} - T_pred|_inf / max(T_range, 1 K),   T_range = max(T) - min(T)

* ``e > 4 tol``: the step is rejected, ``dt <- dt / 2``, and redone.
* otherwise it is accepted and ``dt_next = dt * clip(0.9 sqrt(tol / e), 0.5, 2.0)``.
* the step is clamped to ``[dt_min, dt_max]``.
* a Newton failure gives ``dt <- dt / 4``; below ``dt_min`` a ``ConvergenceError`` is raised.
* a step is always shortened to land exactly on the next *mandatory time*: every requested
  output time, every breakpoint of every load table, and the end time.
* if ``max_dT_per_step`` is set, the step is limited so that the largest nodal change does
  not exceed it.

For the first step there is no predictor and the error test is skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import numpy as np
from numpy import ndarray

from ..core.errors import ConvergenceError, ModelError
from ..model.settings import SolutionSettings

log = logging.getLogger(__name__)

REJECT_FACTOR = 4.0  # reject when e > REJECT_FACTOR * tol
SAFETY, SHRINK_MIN, GROW_MAX = 0.9, 0.5, 2.0
NEWTON_CUT = 0.25
_TIME_EPS = 1e-12
_LAND_SLACK = 1e-9  # a remainder below this fraction of dt is merged into the step
_MIN_RANGE = 1.0  # K, floor of the temperature range in the error measure


def error_estimate(
    T_new: ndarray, T_n: ndarray, T_prev: ndarray | None, dt: float, dt_prev: float | None
) -> float | None:
    """Time-stepping error of a converged step (Theory §6.1).

    Parameters
    ----------
    T_new : ndarray
        Solution at the end of the step [K].
    T_n : ndarray
        Solution at its start [K].
    T_prev : ndarray or None
        Solution one step earlier [K]; ``None`` on the first step.
    dt : float
        Size of the step [s].
    dt_prev : float or None
        Size of the previous step [s].

    Returns
    -------
    float or None
        ``|T_new - T_pred|_inf / max(T_range, 1 K)`` with
        ``T_pred = T_n + (dt / dt_prev) (T_n - T_prev)``; ``None`` when there is no
        previous step to predict from.
    """
    if T_prev is None or dt_prev is None or not dt_prev > 0.0:
        return None
    predicted = T_n + (dt / dt_prev) * (T_n - T_prev)
    spread = float(T_new.max() - T_new.min())
    return float(np.abs(T_new - predicted).max()) / max(spread, _MIN_RANGE)


class StepController:
    """Chooses the size of each time step.

    Typical use::

        controller = StepController(settings, t0, mandatory, dt0)
        while not controller.finished:
            dt = controller.propose()
            ... attempt the step; on Newton failure: controller.newton_failed(); continue
            if controller.accept(error, max_change):
                ... commit the step

    Parameters
    ----------
    settings : SolutionSettings
        Uses ``end_time``, ``auto_timestep``, ``time_tol``, ``dt_min``, ``dt_max`` and
        ``max_dT_per_step``.
    t0 : float
        Start time [s].
    mandatory : iterable of float
        Times [s] a step must land on; the end time is always added. Times outside
        ``(t0, end_time]`` are ignored.
    dt0 : float
        First step size [s].
    """

    def __init__(
        self,
        settings: SolutionSettings,
        t0: float,
        mandatory: Iterable[float],
        dt0: float,
    ) -> None:
        self.settings = settings
        self.t = float(t0)
        self.end = float(settings.end_time)
        if not self.end > self.t:
            raise ModelError("the end time of a transient analysis must be after its start")
        if not dt0 > 0.0:
            raise ModelError("the first time step must be positive")
        self.adaptive = bool(settings.auto_timestep)
        self.dt_min = float(settings.dt_min)
        self.dt_max = float(settings.dt_max) if settings.dt_max is not None else np.inf
        span = self.end - self.t
        times = {float(m) for m in mandatory if self.t + _TIME_EPS * span < m < self.end}
        self.mandatory = sorted(times | {self.end})
        self.dt = self._clamp(float(dt0))  # the step the controller would like to take
        self._try = self.dt  # the step actually proposed (possibly shortened)
        self._shortened = False
        self.accepted = 0
        self.rejected = 0
        self.newton_failures = 0

    # ----------------------------------------------------------------------- helpers

    def _clamp(self, dt: float) -> float:
        return min(max(dt, self.dt_min), self.dt_max)

    @property
    def finished(self) -> bool:
        """True when the end time has been reached."""
        return self.end - self.t <= _TIME_EPS * max(abs(self.end), 1.0)

    @property
    def next_mandatory(self) -> float:
        """The next time [s] a step must land on."""
        for time in self.mandatory:
            if time - self.t > _TIME_EPS * max(abs(self.end), 1.0):
                return time
        return self.end

    # ------------------------------------------------------------------------- steps

    def propose(self) -> float:
        """Return the size [s] of the step to attempt next.

        The wanted step is shortened so that it lands exactly on the next mandatory time.
        """
        remaining = self.next_mandatory - self.t
        self._shortened = remaining <= self.dt * (1.0 + _LAND_SLACK)
        self._try = remaining if self._shortened else self.dt
        return self._try

    def accept(self, error: float | None = None, max_change: float | None = None) -> bool:
        """Judge the step just attempted and choose the next step size.

        Parameters
        ----------
        error : float or None
            The error measure of :func:`error_estimate`; ``None`` on the first step.
        max_change : float or None
            Largest nodal temperature change of the step [K], for ``max_dT_per_step``.

        Returns
        -------
        bool
            True when the step is accepted (time advances); False when it must be redone
            with the reduced step that :meth:`propose` will return.
        """
        dt = self._try
        if not self.adaptive:
            self.t = self.next_mandatory if self._shortened else self.t + dt
            self.accepted += 1
            return True

        tol = float(self.settings.time_tol)
        limit = self.settings.max_dT_per_step
        at_floor = dt <= self.dt_min * (1.0 + _LAND_SLACK)
        too_inaccurate = error is not None and error > REJECT_FACTOR * tol
        too_large = limit is not None and max_change is not None and max_change > limit * (
            1.0 + _LAND_SLACK
        )
        if (too_inaccurate or too_large) and not at_floor:
            reduced = dt * SHRINK_MIN
            if too_large:
                reduced = min(reduced, dt * SAFETY * limit / max_change)
            self.dt = self._clamp(reduced)
            self.rejected += 1
            log.debug("step of %.3g s rejected (error %s); next %.3g s", dt, error, self.dt)
            return False
        if (too_inaccurate or too_large) and at_floor:
            log.warning(
                "time step is at its minimum (%.3g s) but the step is still inaccurate; "
                "accepting it", self.dt_min,
            )

        if error is None:
            factor = 1.0
        elif error <= 0.0:
            factor = GROW_MAX
        else:
            factor = float(np.clip(SAFETY * np.sqrt(tol / error), SHRINK_MIN, GROW_MAX))
        wanted = dt * factor
        if self._shortened and factor >= 1.0:
            wanted = max(wanted, self.dt)  # a step cut short for a mandatory time
        if limit is not None and max_change is not None and max_change > 0.0:
            wanted = min(wanted, dt * limit / max_change)
        self.dt = self._clamp(wanted)
        self.t = self.next_mandatory if self._shortened else self.t + dt
        self.accepted += 1
        return True

    def newton_failed(self) -> None:
        """Cut the step after a failed nonlinear iteration: ``dt <- dt / 4``.

        Raises
        ------
        ConvergenceError
            If the reduced step is below ``dt_min`` (or stepping is not adaptive).
        """
        self.newton_failures += 1
        reduced = self._try * NEWTON_CUT
        if not self.adaptive or reduced < self.dt_min:
            raise ConvergenceError(
                f"the nonlinear iteration failed at t = {self.t:g} s with a step of "
                f"{self._try:g} s"
                + ("" if not self.adaptive else f", and the reduced step {reduced:g} s is "
                   f"below the minimum {self.dt_min:g} s")
            )
        self.dt = reduced
        log.debug("Newton failure: step cut to %.3g s", reduced)
