"""Temperature-dependent fluid properties (Data §6, Theory §8).

Properties are linear interpolations of the fluid's table against temperature. Outside the
table the end values are held (clamped) and a single warning is logged per :class:`Fluid`
object. The beta rule follows Theory §8: ``beta = 1/T`` for ideal gases, the table otherwise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..materials.material import Fluid

log = logging.getLogger(__name__)


@dataclass
class FluidProps:
    """Fluid properties evaluated at one or more temperatures.

    Every field has the shape of the temperature input (a 0-d array for a scalar input).

    Attributes
    ----------
    T : ndarray
        Temperature the properties were evaluated at [K] (as given, not clamped).
    rho : ndarray
        Density [kg/m^3].
    cp : ndarray
        Specific heat [J/(kg K)].
    mu : ndarray
        Dynamic viscosity [Pa s].
    k : ndarray
        Thermal conductivity [W/(m K)].
    beta : ndarray
        Volumetric expansion coefficient [1/K].
    clamped : ndarray
        Boolean; True where T lay outside the table and the end value was used.
    """

    T: ndarray
    rho: ndarray
    cp: ndarray
    mu: ndarray
    k: ndarray
    beta: ndarray
    clamped: ndarray

    @property
    def Pr(self) -> ndarray:  # noqa: N802 - established symbol for the Prandtl number
        """Prandtl number ``mu cp / k`` [-]."""
        return self.mu * self.cp / self.k

    @property
    def nu(self) -> ndarray:
        """Kinematic viscosity ``mu / rho`` [m^2/s]."""
        return self.mu / self.rho

    @property
    def alpha(self) -> ndarray:
        """Thermal diffusivity ``k / (rho cp)`` [m^2/s]."""
        return self.k / (self.rho * self.cp)


def reset_clamp_warning(fluid: Fluid) -> None:
    """Allow the out-of-range warning to be logged again for ``fluid``.

    Parameters
    ----------
    fluid : Fluid
        The fluid whose warned state is cleared (the solver calls this once per solve).
    """
    fluid._clamp_warned = False


def fluid_props(fluid: Fluid, T: float | ndarray) -> FluidProps:
    """Evaluate the properties of ``fluid`` at temperature ``T``.

    Parameters
    ----------
    fluid : Fluid
        Tabulated fluid.
    T : float or ndarray
        Absolute temperature(s) [K]; any shape.

    Returns
    -------
    FluidProps
        Fields with the same shape as ``T``.

    Raises
    ------
    ModelError
        If any temperature is non-finite or not positive (temperatures must be absolute).

    Notes
    -----
    Values outside the table are the end values; a warning naming the fluid is logged once
    per :class:`Fluid` object (see :func:`reset_clamp_warning`).
    """
    t = np.asarray(T, dtype=float)
    if not np.all(np.isfinite(t)) or np.any(t <= 0.0):
        raise ModelError(
            f"fluid {fluid.name!r}: temperatures must be absolute (finite and above 0 K)"
        )

    table_t = np.asarray(fluid.T, dtype=float)
    t_lo, t_hi = table_t[0], table_t[-1]
    clamped = (t < t_lo) | (t > t_hi)
    if np.any(clamped) and not fluid._clamp_warned:
        log.warning(
            "fluid %r: temperature %.4g..%.4g K is outside the property table %.4g..%.4g K; "
            "end values are used",
            fluid.name,
            float(t.min()),
            float(t.max()),
            t_lo,
            t_hi,
        )
        fluid._clamp_warned = True

    def interp(values: list[float]) -> ndarray:
        return np.asarray(np.interp(t, table_t, np.asarray(values, dtype=float)), dtype=float)

    if fluid.ideal_gas:
        beta = 1.0 / t
    else:
        if fluid.beta is None:  # guarded by Fluid validation; kept for safety
            raise ModelError(f"fluid {fluid.name!r} has no beta table")
        beta = interp(fluid.beta)

    return FluidProps(
        T=t,
        rho=interp(fluid.rho),
        cp=interp(fluid.cp),
        mu=interp(fluid.mu),
        k=interp(fluid.k),
        beta=np.asarray(beta, dtype=float),
        clamped=np.asarray(clamped, dtype=bool),
    )
