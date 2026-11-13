"""Shape functions of the built-in element types (Theory §3).

Node ordering is gmsh ordering: corners counter-clockwise, then mid-side nodes in the
order (0-1, 1-2, 2-0) for triangles and (0-1, 1-2, 2-3, 3-0) for quads. The three-node
line is ordered (end, end, middle).

Importing this module registers T3, T6, Q4, Q8, L2 and L3 in :mod:`.registry`. The
module-level :func:`shape`, :func:`dshape` and :func:`node_coords` look the element type
up in the registry, so they also work for types registered elsewhere.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from . import quadrature
from .registry import ElementType, element, register_element

# --------------------------------------------------------------------------- triangles

_T3_NODES = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
_T6_NODES = np.array(
    [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
)


def _t3_shape(pts: ndarray) -> ndarray:
    xi, eta = pts[:, 0], pts[:, 1]
    return np.stack([1.0 - xi - eta, xi, eta], axis=-1)


def _t3_dshape(pts: ndarray) -> ndarray:
    dn = np.array([[-1.0, 1.0, 0.0], [-1.0, 0.0, 1.0]])
    return np.broadcast_to(dn, (pts.shape[0], *dn.shape)).copy()


def _t6_shape(pts: ndarray) -> ndarray:
    l2, l3 = pts[:, 0], pts[:, 1]
    l1 = 1.0 - l2 - l3
    return np.stack(
        [
            l1 * (2.0 * l1 - 1.0),
            l2 * (2.0 * l2 - 1.0),
            l3 * (2.0 * l3 - 1.0),
            4.0 * l1 * l2,
            4.0 * l2 * l3,
            4.0 * l3 * l1,
        ],
        axis=-1,
    )


def _t6_dshape(pts: ndarray) -> ndarray:
    l2, l3 = pts[:, 0], pts[:, 1]
    l1 = 1.0 - l2 - l3
    zero = np.zeros_like(l1)
    d_xi = np.stack(
        [
            -(4.0 * l1 - 1.0),
            4.0 * l2 - 1.0,
            zero,
            4.0 * (l1 - l2),
            4.0 * l3,
            -4.0 * l3,
        ],
        axis=-1,
    )
    d_eta = np.stack(
        [
            -(4.0 * l1 - 1.0),
            zero,
            4.0 * l3 - 1.0,
            -4.0 * l2,
            4.0 * l2,
            4.0 * (l1 - l3),
        ],
        axis=-1,
    )
    return np.stack([d_xi, d_eta], axis=1)


# ------------------------------------------------------------------------------- quads

_Q4_NODES = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
_Q8_NODES = np.array(
    [
        [-1.0, -1.0],
        [1.0, -1.0],
        [1.0, 1.0],
        [-1.0, 1.0],
        [0.0, -1.0],
        [1.0, 0.0],
        [0.0, 1.0],
        [-1.0, 0.0],
    ]
)
_Q8_CORNERS = slice(0, 4)
_Q8_MID_XI0 = np.array([4, 6])  # mid-side nodes with xi_i = 0
_Q8_MID_ETA0 = np.array([5, 7])  # mid-side nodes with eta_i = 0


def _q4_shape(pts: ndarray) -> ndarray:
    xi, eta = pts[:, :1], pts[:, 1:]
    xi_i, eta_i = _Q4_NODES[:, 0], _Q4_NODES[:, 1]
    return 0.25 * (1.0 + xi * xi_i) * (1.0 + eta * eta_i)


def _q4_dshape(pts: ndarray) -> ndarray:
    xi, eta = pts[:, :1], pts[:, 1:]
    xi_i, eta_i = _Q4_NODES[:, 0], _Q4_NODES[:, 1]
    d_xi = 0.25 * xi_i * (1.0 + eta * eta_i)
    d_eta = 0.25 * eta_i * (1.0 + xi * xi_i)
    return np.stack([d_xi, d_eta], axis=1)


def _q8_shape(pts: ndarray) -> ndarray:
    xi, eta = pts[:, :1], pts[:, 1:]
    out = np.empty((pts.shape[0], 8))
    xc, ec = _Q8_NODES[_Q8_CORNERS, 0], _Q8_NODES[_Q8_CORNERS, 1]
    out[:, _Q8_CORNERS] = (
        0.25 * (1.0 + xi * xc) * (1.0 + eta * ec) * (xi * xc + eta * ec - 1.0)
    )
    out[:, _Q8_MID_XI0] = 0.5 * (1.0 - xi**2) * (1.0 + eta * _Q8_NODES[_Q8_MID_XI0, 1])
    out[:, _Q8_MID_ETA0] = 0.5 * (1.0 + xi * _Q8_NODES[_Q8_MID_ETA0, 0]) * (1.0 - eta**2)
    return out


def _q8_dshape(pts: ndarray) -> ndarray:
    xi, eta = pts[:, :1], pts[:, 1:]
    out = np.empty((pts.shape[0], 2, 8))
    xc, ec = _Q8_NODES[_Q8_CORNERS, 0], _Q8_NODES[_Q8_CORNERS, 1]
    out[:, 0, _Q8_CORNERS] = 0.25 * xc * (1.0 + eta * ec) * (2.0 * xi * xc + eta * ec)
    out[:, 1, _Q8_CORNERS] = 0.25 * ec * (1.0 + xi * xc) * (xi * xc + 2.0 * eta * ec)
    em = _Q8_NODES[_Q8_MID_XI0, 1]
    out[:, 0, _Q8_MID_XI0] = -xi * (1.0 + eta * em)
    out[:, 1, _Q8_MID_XI0] = 0.5 * (1.0 - xi**2) * em
    xm = _Q8_NODES[_Q8_MID_ETA0, 0]
    out[:, 0, _Q8_MID_ETA0] = 0.5 * xm * (1.0 - eta**2)
    out[:, 1, _Q8_MID_ETA0] = -eta * (1.0 + xi * xm)
    return out


# ------------------------------------------------------------------------------- lines

_L2_NODES = np.array([[-1.0], [1.0]])
_L3_NODES = np.array([[-1.0], [1.0], [0.0]])


def _l2_shape(pts: ndarray) -> ndarray:
    xi = pts[:, 0]
    return np.stack([0.5 * (1.0 - xi), 0.5 * (1.0 + xi)], axis=-1)


def _l2_dshape(pts: ndarray) -> ndarray:
    dn = np.array([[-0.5, 0.5]])
    return np.broadcast_to(dn, (pts.shape[0], *dn.shape)).copy()


def _l3_shape(pts: ndarray) -> ndarray:
    xi = pts[:, 0]
    return np.stack([0.5 * xi * (xi - 1.0), 0.5 * xi * (xi + 1.0), 1.0 - xi**2], axis=-1)


def _l3_dshape(pts: ndarray) -> ndarray:
    xi = pts[:, 0]
    return np.stack([xi - 0.5, xi + 0.5, -2.0 * xi], axis=-1)[:, None, :]


# ------------------------------------------------------------------------ registration

register_element(
    ElementType(
        name="L2",
        dim=1,
        n_nodes=2,
        order=1,
        gmsh_type=1,
        shape=_l2_shape,
        dshape=_l2_dshape,
        node_coords=_L2_NODES,
        quadrature=quadrature.rule("L2"),
        facet_type=None,
        facets=None,
        display_simplices=np.array([[0, 1]]),
    )
)
register_element(
    ElementType(
        name="L3",
        dim=1,
        n_nodes=3,
        order=2,
        gmsh_type=8,
        shape=_l3_shape,
        dshape=_l3_dshape,
        node_coords=_L3_NODES,
        quadrature=quadrature.rule("L3"),
        facet_type=None,
        facets=None,
        display_simplices=np.array([[0, 2], [2, 1]]),
    )
)
register_element(
    ElementType(
        name="T3",
        dim=2,
        n_nodes=3,
        order=1,
        gmsh_type=2,
        shape=_t3_shape,
        dshape=_t3_dshape,
        node_coords=_T3_NODES,
        quadrature=quadrature.rule("T3"),
        facet_type="L2",
        facets=np.array([[0, 1], [1, 2], [2, 0]]),
        display_simplices=np.array([[0, 1, 2]]),
    )
)
register_element(
    ElementType(
        name="T6",
        dim=2,
        n_nodes=6,
        order=2,
        gmsh_type=9,
        shape=_t6_shape,
        dshape=_t6_dshape,
        node_coords=_T6_NODES,
        quadrature=quadrature.rule("T6"),
        facet_type="L3",
        facets=np.array([[0, 1, 3], [1, 2, 4], [2, 0, 5]]),
        display_simplices=np.array([[0, 3, 5], [3, 1, 4], [5, 4, 2], [3, 4, 5]]),
    )
)
register_element(
    ElementType(
        name="Q4",
        dim=2,
        n_nodes=4,
        order=1,
        gmsh_type=3,
        shape=_q4_shape,
        dshape=_q4_dshape,
        node_coords=_Q4_NODES,
        quadrature=quadrature.rule("Q4"),
        facet_type="L2",
        facets=np.array([[0, 1], [1, 2], [2, 3], [3, 0]]),
        display_simplices=np.array([[0, 1, 2], [0, 2, 3]]),
    )
)
register_element(
    ElementType(
        name="Q8",
        dim=2,
        n_nodes=8,
        order=2,
        gmsh_type=16,
        shape=_q8_shape,
        dshape=_q8_dshape,
        node_coords=_Q8_NODES,
        quadrature=quadrature.rule("Q8"),
        facet_type="L3",
        facets=np.array([[0, 1, 4], [1, 2, 5], [2, 3, 6], [3, 0, 7]]),
        display_simplices=np.array(
            [[0, 4, 7], [4, 1, 5], [5, 2, 6], [6, 3, 7], [4, 5, 6], [4, 6, 7]]
        ),
    )
)


# -------------------------------------------------------------------------- public API


def _as_points(pts: ndarray, dim: int) -> ndarray:
    return np.asarray(pts, dtype=float).reshape(-1, dim)


def shape(etype: str, pts: ndarray) -> ndarray:
    """Evaluate the shape functions of an element type.

    Parameters
    ----------
    etype : str
        Registered element-type name.
    pts : ndarray, shape (n_pts, dim)
        Reference coordinates (dimensionless).

    Returns
    -------
    ndarray, shape (n_pts, n_nodes)
        Shape-function values (dimensionless).
    """
    et = element(etype)
    return et.shape(_as_points(pts, et.dim))


def dshape(etype: str, pts: ndarray) -> ndarray:
    """Evaluate the shape-function derivatives with respect to the reference coordinates.

    Parameters
    ----------
    etype : str
        Registered element-type name.
    pts : ndarray, shape (n_pts, dim)
        Reference coordinates (dimensionless).

    Returns
    -------
    ndarray, shape (n_pts, dim, n_nodes)
        ``dN[p, a, i]`` is the derivative of shape function ``i`` with respect to
        reference coordinate ``a`` at point ``p`` (dimensionless).
    """
    et = element(etype)
    return et.dshape(_as_points(pts, et.dim))


def node_coords(etype: str) -> ndarray:
    """Return the reference coordinates of the nodes of an element type.

    Parameters
    ----------
    etype : str
        Registered element-type name.

    Returns
    -------
    ndarray, shape (n_nodes, dim)
        A copy of the reference node coordinates (dimensionless).
    """
    return element(etype).node_coords.copy()
