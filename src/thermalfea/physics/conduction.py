"""Conduction element matrices (Theory §2)."""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from .kernel import ElemGeom


def conduction(geom: ElemGeom, D: ndarray, g: ndarray) -> ndarray:
    """Conduction matrices ``K_e = sum_gp B^T D B g |J| w`` of a block of elements.

    Parameters
    ----------
    geom : ElemGeom
        Integration data of the block.
    D : ndarray, shape (e, gp, dim, dim)
        Conductivity matrix at each integration point [W/(m K)].
    g : ndarray, shape (e, gp)
        Geometry factor at each integration point (thickness [m], ``2 pi r`` [m], or 1).

    Returns
    -------
    ndarray, shape (e, n, n)
        Element conduction matrices [W/K].
    """
    return np.einsum(
        "epin,epij,epjm,ep->enm", geom.dNdx, D, geom.dNdx, g * geom.dV, optimize=True
    )
