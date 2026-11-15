"""Material properties evaluated at integration points (Theory §2).

Temperature-dependent properties are evaluated at each integration point from the
interpolated temperature ``N T_e``.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..core.functions import Function
from ..materials.material import Material

_ORTHOTROPIC_DIM = 2  # the rotation R(theta) of Theory §2 is defined in the plane


def _values(fn: Function, T: ndarray) -> ndarray:
    return np.broadcast_to(np.asarray(fn(T=T), dtype=float), T.shape)


def conductivity_matrix(material: Material, angle: float, T: ndarray, dim: int) -> ndarray:
    """Conductivity matrix ``D`` at integration points.

    Isotropic: ``D = k I``. Orthotropic with principal conductivities ``k1`` (along the
    material axis) and ``k2`` (across it) and material angle ``theta``, counter-clockwise
    from x: ``D = R diag(k1, k2) R^T`` with ``R = [[cos, -sin], [sin, cos]]``.

    Parameters
    ----------
    material : Material
        ``material.k`` is ``k1``; ``material.k2``, when set, makes it orthotropic.
    angle : float
        Material angle ``theta`` [rad]; ignored for isotropic materials.
    T : ndarray, shape (e, gp)
        Temperature at the integration points [K].
    dim : int
        Space dimension.

    Returns
    -------
    ndarray, shape (e, gp, dim, dim)
        ``D`` [W/(m K)].

    Raises
    ------
    ModelError
        For an orthotropic material in a model that is not two-dimensional.
    """
    k1 = _values(material.k, T)
    if material.k2 is None:
        return k1[..., None, None] * np.eye(dim)
    if dim != _ORTHOTROPIC_DIM:
        raise ModelError(
            f"material {material.name!r}: orthotropic conductivity is defined for "
            "two-dimensional models only"
        )
    k2 = _values(material.k2, T)
    c, s = np.cos(angle), np.sin(angle)
    rotation = np.array([[c, -s], [s, c]])
    principal = np.zeros((*T.shape, dim, dim))
    principal[..., 0, 0] = k1
    principal[..., 1, 1] = k2
    return rotation @ principal @ rotation.T


def density(material: Material, T: ndarray) -> ndarray:
    """Density at integration points.

    Parameters
    ----------
    material : Material
    T : ndarray, shape (e, gp)
        Temperature [K].

    Returns
    -------
    ndarray, shape (e, gp)
        Density [kg/m^3].
    """
    return _values(material.rho, T)


def specific_heat(material: Material, T: ndarray) -> ndarray:
    """Specific heat at integration points.

    Parameters
    ----------
    material : Material
    T : ndarray, shape (e, gp)
        Temperature [K].

    Returns
    -------
    ndarray, shape (e, gp)
        Specific heat [J/(kg K)].
    """
    return _values(material.cp, T)


def volumetric_heat_capacity(material: Material, T: ndarray) -> ndarray:
    """``rho c`` at integration points.

    Parameters
    ----------
    material : Material
    T : ndarray, shape (e, gp)
        Temperature [K].

    Returns
    -------
    ndarray, shape (e, gp)
        Volumetric heat capacity [J/(m^3 K)].
    """
    return density(material, T) * specific_heat(material, T)
