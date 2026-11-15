"""Material properties evaluated at integration points (Theory §2)."""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..materials.material import Material


def conductivity_matrix(material: Material, angle: float, T: ndarray, dim: int) -> ndarray:
    """Conductivity matrix ``D`` at integration points.

    Parameters
    ----------
    material : Material
    angle : float
        Angle of the material axis [rad], counter-clockwise from x (orthotropic only).
    T : ndarray, shape (e, gp)
        Temperature at the integration points [K].
    dim : int
        Space dimension.

    Returns
    -------
    ndarray, shape (e, gp, dim, dim)
        ``D`` [W/(m K)]. Isotropic: ``k I``.
    """
    if material.k2 is not None:
        raise ModelError(
            f"material {material.name!r} is orthotropic; orthotropic conductivity is not "
            "available yet"
        )
    k = np.broadcast_to(np.asarray(material.k(T=T), dtype=float), T.shape)
    return k[..., None, None] * np.eye(dim)
