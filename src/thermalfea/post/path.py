"""Sampling of results along a path (M5.4).

Each sample point is located in the mesh by a nearest-centroid search followed by the
inverse isoparametric map (Newton iteration in the reference coordinates), then the field
is interpolated with the element's shape functions. Temperature is continuous across
elements; the gradient and flux are evaluated inside the element that holds the point, so
they are discontinuous across element and region boundaries, as in the recovered fields.

Everything is vectorised: the Python loops run over element blocks, candidate ranks and
Newton iterations (all small and fixed), never over points or elements.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from numpy import ndarray
from scipy.spatial import cKDTree

from ..core.errors import ModelError
from ..core.mesh import Mesh
from ..core.registry import ElementType, element
from ..physics.properties import conductivity_matrix
from .results import Results

log = logging.getLogger(__name__)

#: Number of nearest element centroids tried as candidates for every point.
N_CANDIDATES = 8
#: Newton iteration cap and tolerance (reference coordinates) of the inverse mapping.
MAX_NEWTON = 30
NEWTON_TOL = 1e-10
#: A point is inside the reference element when it is at most this far outside (reference
#: coordinates, scaled by the edge length).
INSIDE_TOL = 1e-8

#: Path fields: name -> (source, component or None for the magnitude). Values are SI.
PATH_FIELDS: dict[str, tuple[str, int | None]] = {
    "T": ("T", None),
    "qx": ("flux", 0),
    "qy": ("flux", 1),
    "qmag": ("flux", None),
    "gradx": ("grad", 0),
    "grady": ("grad", 1),
    "gradmag": ("grad", None),
}


@dataclass
class Located:
    """Where each sample point lies in the mesh.

    Attributes
    ----------
    elem_ids : ndarray of int, shape (n_points,)
        Global id of the element containing each point; -1 if outside the mesh.
    block : ndarray of int, shape (n_points,)
        Index into ``mesh.blocks``; -1 if outside.
    row : ndarray of int, shape (n_points,)
        Row of the element within its block.
    local : ndarray, shape (n_points, dim)
        Reference coordinates in the element; NaN if outside.
    """

    elem_ids: ndarray
    block: ndarray
    row: ndarray
    local: ndarray


class _Index(NamedTuple):
    tree: cKDTree
    ids: ndarray  # global element id of each tree entry
    id_block: ndarray
    id_row: ndarray


_CACHE: dict[int, tuple[Mesh, _Index]] = {}
_CACHE_SIZE = 8


def _index(mesh: Mesh) -> _Index:
    """Centroid tree and element-id lookup of a mesh, built once per mesh object."""
    cached = _CACHE.get(id(mesh))
    if cached is not None and cached[0] is mesh:
        return cached[1]
    centroids = mesh.element_centroids()
    ids = np.flatnonzero(np.all(np.isfinite(centroids), axis=1))
    id_block = np.full(centroids.shape[0], -1, dtype=np.int64)
    id_row = np.zeros(centroids.shape[0], dtype=np.int64)
    for ib, block in enumerate(mesh.blocks):
        id_block[block.elem_ids] = ib
        id_row[block.elem_ids] = np.arange(block.conn.shape[0])
    index = _Index(cKDTree(centroids[ids]), ids, id_block, id_row)
    if len(_CACHE) >= _CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[id(mesh)] = (mesh, index)
    return index


def _inside_polygon(et: ElementType, xi: ndarray) -> ndarray:
    """Whether reference points lie inside a 2D element (convex polygon).

    The polygon's corners are the first node of each facet, counter-clockwise (taken from
    the registry); a point is inside when it is on the left of, or within ``INSIDE_TOL`` of,
    every edge. Valid for elements whose facets are lines, i.e. 2D elements; a 3D element
    needs only a different inside test here.

    Parameters
    ----------
    et : ElementType
    xi : ndarray, shape (m, 2)
        Reference coordinates.

    Returns
    -------
    ndarray of bool, shape (m,)
    """
    if et.facets is None:
        raise ModelError(f"element type {et.name!r} has no facets; cannot test containment")
    corners = np.asarray(et.node_coords)[np.asarray(et.facets)[:, 0]]
    a = corners
    b = np.roll(corners, -1, axis=0)
    edge = b - a  # (f, 2)
    rel = xi[:, None, :] - a[None, :, :]  # (m, f, 2)
    cross = edge[None, :, 0] * rel[:, :, 1] - edge[None, :, 1] * rel[:, :, 0]
    return np.all(cross >= -INSIDE_TOL, axis=1)


def _newton(
    et: ElementType, X: ndarray, points: ndarray, tol: float = NEWTON_TOL
) -> tuple[ndarray, ndarray]:
    """Inverse isoparametric map of many points, each in its own element.

    Parameters
    ----------
    et : ElementType
    X : ndarray, shape (m, n_nodes, dim)
        Node coordinates of the element of each point [m].
    points : ndarray, shape (m, dim)
        Physical positions [m].
    tol : float
        Convergence tolerance on the largest change of a reference coordinate.

    Returns
    -------
    xi : ndarray, shape (m, dim)
        Reference coordinates.
    ok : ndarray of bool, shape (m,)
        True where the iteration converged to a finite result.
    """
    m = points.shape[0]
    xi = np.tile(np.asarray(et.quadrature[0]).mean(axis=0), (m, 1))
    active = np.ones(m, dtype=bool)
    ok = np.zeros(m, dtype=bool)
    eye = np.eye(points.shape[1])
    with np.errstate(all="ignore"):
        for _ in range(MAX_NEWTON):
            idx = np.flatnonzero(active)
            if idx.size == 0:
                break
            x = xi[idx]
            Xe = X[idx]
            res = points[idx] - np.einsum("mn,mni->mi", et.shape(x), Xe)
            jac = np.einsum("man,mni->mia", et.dshape(x), Xe)
            det = np.linalg.det(jac)
            good = np.isfinite(det) & (np.abs(det) > 0.0) & np.all(np.isfinite(res), axis=1)
            safe = np.where(good[:, None, None], jac, eye)
            delta = np.linalg.solve(safe, res[:, :, None])[:, :, 0]
            good &= np.all(np.isfinite(delta), axis=1)
            delta = np.where(good[:, None], delta, 0.0)
            xi[idx] = x + delta
            done = good & (np.max(np.abs(delta), axis=1) < tol)
            ok[idx[done]] = True
            active[idx[done | ~good]] = False
    ok &= np.all(np.isfinite(xi), axis=1)
    return xi, ok


def locate(mesh: Mesh, points: ndarray, tol: float = NEWTON_TOL) -> Located:
    """Find the element containing each point and its reference coordinates there.

    Parameters
    ----------
    mesh : Mesh
    points : ndarray, shape (n_points, dim)
        Positions [m].
    tol : float
        Newton tolerance on the reference coordinates (default 1e-10).

    Returns
    -------
    Located
        Points outside the mesh have ``elem_ids == -1`` and NaN local coordinates.
    """
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    if pts.ndim != 2 or pts.shape[1] != mesh.dim:
        raise ModelError(f"points must have shape (n, {mesh.dim})")
    n = pts.shape[0]
    out = Located(
        np.full(n, -1, dtype=np.int64),
        np.full(n, -1, dtype=np.int64),
        np.zeros(n, dtype=np.int64),
        np.full((n, mesh.dim), np.nan),
    )
    index = _index(mesh)
    if n == 0 or index.ids.size == 0:
        return out
    k = min(N_CANDIDATES, index.ids.size)
    finite = np.all(np.isfinite(pts), axis=1)
    cand = np.full((n, k), -1, dtype=np.int64)
    _, nearest = index.tree.query(pts[finite], k=k)
    cand[finite] = index.ids[np.asarray(nearest).reshape(-1, k)]

    pending = finite.copy()
    for rank in range(k):
        todo = np.flatnonzero(pending)
        if todo.size == 0:
            break
        ge = cand[todo, rank]
        blk = index.id_block[ge]
        for ib in np.unique(blk):
            sel = todo[blk == ib]
            block = mesh.blocks[int(ib)]
            et = element(block.etype)
            rows = index.id_row[cand[sel, rank]]
            X = mesh.nodes[block.conn[rows]]
            xi, ok = _newton(et, X, pts[sel], tol)
            ok &= _inside_polygon(et, np.where(ok[:, None], xi, 0.0))
            hit = sel[ok]
            out.elem_ids[hit] = cand[hit, rank]
            out.block[hit] = ib
            out.row[hit] = rows[ok]
            out.local[hit] = xi[ok]
            pending[hit] = False
    return out


def _by_block(mesh: Mesh, located: Located):
    """Yield ``(block, element type, point indices, rows)`` for each block with points."""
    for ib in np.unique(located.block[located.block >= 0]):
        sel = np.flatnonzero(located.block == ib)
        block = mesh.blocks[int(ib)]
        yield block, element(block.etype), sel, located.row[sel]


def interpolate(mesh: Mesh, located: Located, nodal: ndarray) -> ndarray:
    """Interpolate nodal values at located points with the element shape functions.

    Parameters
    ----------
    mesh : Mesh
    located : Located
        From :func:`locate`.
    nodal : ndarray, shape (n_nodes,) or (n_nodes, k)
        Nodal values.

    Returns
    -------
    ndarray, shape (n_points,) or (n_points, k)
        NaN for points outside the mesh.
    """
    nodal = np.asarray(nodal, dtype=float)
    out = np.full((located.elem_ids.size, *nodal.shape[1:]), np.nan)
    for block, et, sel, rows in _by_block(mesh, located):
        N = et.shape(located.local[sel])  # (m, n)
        vals = nodal[block.conn[rows]]  # (m, n, ...)
        out[sel] = np.einsum("mn,mn...->m...", N, vals)
    return out


def polyline_points(polyline: Sequence[Sequence[float]], n: int = 200) -> tuple[ndarray, ndarray]:
    """Points equally spaced in arc length along a polyline.

    Parameters
    ----------
    polyline : sequence of (x, y)
        At least two vertices [m].
    n : int
        Number of points, ends included (at least 2).

    Returns
    -------
    s : ndarray, shape (n,)
        Arc-length coordinate [m].
    xy : ndarray, shape (n, dim)
        Positions [m].

    Raises
    ------
    ModelError
        For fewer than two vertices, zero total length or ``n < 2``.
    """
    try:
        verts = np.asarray(polyline, dtype=float)
    except (TypeError, ValueError):
        raise ModelError("the path must be a sequence of (x, y) vertices") from None
    if verts.ndim != 2 or verts.shape[0] < 2:
        raise ModelError("a path needs at least two (x, y) vertices")
    if n < 2:
        raise ModelError(f"a path needs at least 2 sample points, not {n}")
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(verts, axis=0), axis=1))])
    if not cum[-1] > 0.0:
        raise ModelError("the path has zero length")
    s = np.linspace(0.0, cum[-1], int(n))
    xy = np.stack([np.interp(s, cum, verts[:, c]) for c in range(verts.shape[1])], axis=1)
    return s, xy


def _gradient_flux(
    results: Results, located: Located, T: ndarray, source: str
) -> ndarray:
    """Gradient [K/m] or flux [W/m^2] at located points, shape (n_points, dim)."""
    mesh = results.mesh
    out = np.full((located.elem_ids.size, mesh.dim), np.nan)
    for block, et, sel, rows in _by_block(mesh, located):
        xi = located.local[sel]
        conn = block.conn[rows]
        Te = T[conn]  # (m, n)
        jac = np.einsum("man,mni->mia", et.dshape(xi), mesh.nodes[conn])
        dNdx = np.einsum("man,mai->min", et.dshape(xi), np.linalg.inv(jac))
        grad = np.einsum("min,mn->mi", dNdx, Te)
        if source == "grad":
            out[sel] = grad
            continue
        T_pts = np.einsum("mn,mn->m", et.shape(xi), Te)
        regions = block.region[rows]
        for region_id in np.unique(regions):
            pick = regions == region_id
            data = results.problem.regions[int(region_id)]
            D = conductivity_matrix(data.material, data.material_angle, T_pts[pick, None], mesh.dim)
            out[sel[pick]] = -np.einsum("mij,mj->mi", D[:, 0], grad[pick])
    return out


def _evaluate(results: Results, step: int, points: ndarray, field: str) -> ndarray:
    """Field values (SI) at points; NaN outside the mesh."""
    if field not in PATH_FIELDS:
        raise ModelError(f"unknown field {field!r}; choose from {', '.join(PATH_FIELDS)}")
    source, component = PATH_FIELDS[field]
    mesh = results.mesh
    if component is not None and component >= mesh.dim:
        raise ModelError(f"field {field!r} needs a {component + 1}D mesh")
    T = np.asarray(results.temperature(step), dtype=float)
    located = locate(mesh, points)
    if source == "T":
        return interpolate(mesh, located, T)
    vec = _gradient_flux(results, located, T, source)
    return np.linalg.norm(vec, axis=1) if component is None else vec[:, component]


def sample(
    results: Results,
    step: int,
    polyline: Sequence[Sequence[float]],
    n: int = 200,
    field: str = "T",
) -> tuple[ndarray, ndarray]:
    """Sample a field at equally spaced points along a polyline.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    polyline : sequence of (x, y)
        Vertices [m], at least two.
    n : int
        Number of sample points.
    field : str
        ``T``, ``qx``, ``qy``, ``qmag``, ``gradx``, ``grady`` or ``gradmag``. Flux and
        gradient are evaluated inside the element holding each point.

    Returns
    -------
    s : ndarray, shape (n,)
        Arc length along the path [m].
    values : ndarray, shape (n,)
        Field in SI units (K, W/m^2, K/m); NaN where the path is outside the mesh.

    Raises
    ------
    ModelError
        For an unknown field or step, or an invalid polyline.
    """
    s, xy = polyline_points(polyline, n)
    return s, _evaluate(results, step, xy, field)


def value_at(results: Results, step: int, point: Sequence[float], field: str = "T") -> float:
    """Field value at one point (SI units), NaN outside the mesh.

    Parameters
    ----------
    results : Results
    step : int
    point : sequence of float
        Position [m].
    field : str
        See :func:`sample`.
    """
    xy = np.asarray(point, dtype=float).reshape(1, -1)
    return float(_evaluate(results, step, xy, field)[0])
