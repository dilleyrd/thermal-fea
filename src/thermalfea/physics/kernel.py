"""Element geometry kernel: everything the element integrals need, for whole blocks at once.

Nothing here assumes a space dimension (Plan §7). Element blocks give volume integration
data; facet blocks give the data for boundary integrals, with the measure
``sqrt(det(J^T J))`` that is the edge length factor in 2D and the area factor in 3D.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy import ndarray

from ..core.errors import MeshError
from ..core.mesh import ElementBlock, FacetBlock, jacobians
from ..core.registry import element

_PLANAR_DIM = 2  # the only dimension with a thickness or an axisymmetric factor


@dataclass
class ElemGeom:
    """Integration data of a block of elements.

    Attributes
    ----------
    N : ndarray, shape (gp, n)
        Shape functions at the integration points (dimensionless).
    dNdx : ndarray, shape (e, gp, dim, n)
        Shape-function derivatives with respect to the physical coordinates [1/m].
    dV : ndarray, shape (e, gp)
        ``|J| * w``: area [m^2] in 2D, volume [m^3] in 3D, per integration point.
    xgp : ndarray, shape (e, gp, dim)
        Physical coordinates of the integration points [m].
    """

    N: ndarray
    dNdx: ndarray
    dV: ndarray
    xgp: ndarray


@dataclass
class FacetGeom:
    """Integration data of a block of facets.

    Attributes
    ----------
    N : ndarray, shape (gp, n)
        Facet shape functions at the integration points (dimensionless).
    dS : ndarray, shape (f, gp)
        ``sqrt(det(J^T J)) * w``: length [m] in 2D, area [m^2] in 3D.
    xgp : ndarray, shape (f, gp, dim)
        Physical coordinates of the integration points [m].
    """

    N: ndarray
    dS: ndarray
    xgp: ndarray


def geometry(block: ElementBlock, nodes: ndarray) -> ElemGeom:
    """Compute the integration data of an element block.

    Parameters
    ----------
    block : ElementBlock
        Elements of one type.
    nodes : ndarray, shape (n_nodes, dim)
        Node coordinates of the mesh [m].

    Returns
    -------
    ElemGeom

    Raises
    ------
    MeshError
        If an element has a non-positive Jacobian determinant.
    """
    et = element(block.etype)
    pts, w = et.quadrature
    coords = nodes[block.conn]  # (e, n, dim)
    shape = et.shape(pts)  # (gp, n)
    dshape = et.dshape(pts)  # (gp, a, n)
    jac = jacobians(block.etype, coords, pts)  # (e, gp, i, a)
    det = np.linalg.det(jac)
    if not np.all(det > 0.0):
        raise MeshError(
            f"block {block.etype!r}: {int(np.any(~(det > 0.0), axis=1).sum())} element(s) "
            "with non-positive Jacobian"
        )
    inv = np.linalg.inv(jac)  # (e, gp, a, i) = d xi_a / d x_i
    return ElemGeom(
        N=shape,
        dNdx=np.einsum("pan,epai->epin", dshape, inv),
        dV=det * w,
        xgp=np.einsum("pn,eni->epi", shape, coords),
    )


def facet_geometry(block: FacetBlock, nodes: ndarray) -> FacetGeom:
    """Compute the integration data of a facet block.

    Parameters
    ----------
    block : FacetBlock
        Facets of one type.
    nodes : ndarray, shape (n_nodes, dim)
        Node coordinates of the mesh [m].

    Returns
    -------
    FacetGeom
    """
    ft = element(block.etype)
    pts, w = ft.quadrature
    coords = nodes[block.conn]  # (f, n, dim)
    shape = ft.shape(pts)
    jac = jacobians(block.etype, coords, pts)  # (f, gp, dim, dim - 1)
    metric = np.einsum("fpia,fpib->fpab", jac, jac)
    return FacetGeom(
        N=shape,
        dS=np.sqrt(np.linalg.det(metric)) * w,
        xgp=np.einsum("pn,fni->fpi", shape, coords),
    )


def gfactor(
    xgp: ndarray, axisymmetric: bool, thickness: float | ndarray, dim: int
) -> ndarray:
    """Geometry factor ``g`` carried by every integral (Theory §1).

    Parameters
    ----------
    xgp : ndarray, shape (..., dim)
        Integration-point coordinates [m].
    axisymmetric : bool
        True for an axisymmetric model, where x is the radius.
    thickness : float or ndarray broadcastable to ``xgp.shape[:-1]``
        Planar thickness [m]; ignored for axisymmetric and 3D models.
    dim : int
        Space dimension of the model.

    Returns
    -------
    ndarray, shape ``xgp.shape[:-1]``
        Planar: the thickness [m]. Axisymmetric: ``2 pi r`` [m]. 3D: 1 (dimensionless).
        With this factor every assembled load is in watts.
    """
    shape = xgp.shape[:-1]
    if dim != _PLANAR_DIM:
        return np.ones(shape)
    if axisymmetric:
        return 2.0 * np.pi * xgp[..., 0]
    return np.broadcast_to(np.asarray(thickness, dtype=float), shape).copy()
