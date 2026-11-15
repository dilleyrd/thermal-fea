"""Evaluation of load functions at integration points.

The one place that maps integration-point coordinates onto the ``x`` and ``y`` arguments
of a :class:`~thermalfea.core.functions.Function` (Data §1).
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..core.functions import Function


def at_points(fn: Function, t: float, xgp: ndarray, T: ndarray | float = 0.0) -> ndarray:
    """Evaluate a function at integration points.

    Parameters
    ----------
    fn : Function
    t : float
        Time [s].
    xgp : ndarray, shape (..., dim)
        Integration-point coordinates [m].
    T : ndarray of shape ``xgp.shape[:-1]``, or float
        Temperature at the points [K].

    Returns
    -------
    ndarray, shape ``xgp.shape[:-1]``
        Function values in the SI unit of the quantity.
    """
    shape = xgp.shape[:-1]
    x = xgp[..., 0]
    y = xgp[..., 1] if xgp.shape[-1] > 1 else np.zeros(shape)
    return np.broadcast_to(np.asarray(fn(t=t, x=x, y=y, T=T), dtype=float), shape)


def interpolate(N: ndarray, nodal: ndarray) -> ndarray:
    """Interpolate nodal values to integration points: ``(gp, n), (e, n) -> (e, gp)``."""
    return np.einsum("pn,en->ep", N, nodal)
