"""Recovered quantities: temperature gradient and heat flux (Theory §7).

* Gradient at any element point: ``grad T = B T_e``. Flux ``q = -D grad T``.
* Nodal flux: ``q`` is evaluated at each element's own nodes (``B`` at the node's local
  coordinates) and the contributions of all elements sharing the node *that belong to the
  same region* are averaged. A node on a material interface therefore has one flux value
  per region.
* Element flux: the value at the element centroid.

Everything is computed for whole element batches at once and works in any dimension.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..core.mesh import Mesh, jacobians
from ..core.registry import element
from ..physics.batches import ElementBatch, element_batches
from ..physics.properties import conductivity_matrix
from ..solver.problem import TEMPERATURE, CompiledProblem


def _at_points(
    problem: CompiledProblem, batch: ElementBatch, nodal_T: ndarray, pts: ndarray
) -> tuple[ndarray, ndarray]:
    """Gradient and flux of a batch at reference points.

    Returns
    -------
    grad : ndarray, shape (e, p, dim)
        Temperature gradient [K/m].
    q : ndarray, shape (e, p, dim)
        Heat flux [W/m^2].
    """
    mesh = problem.mesh
    et = element(batch.etype)
    Te = nodal_T[batch.conn]  # (e, n)
    jac = jacobians(batch.etype, mesh.nodes[batch.conn], pts)  # (e, p, i, a)
    dNdx = np.einsum("pan,epai->epin", et.dshape(pts), np.linalg.inv(jac))
    grad = np.einsum("epin,en->epi", dNdx, Te)
    T_pts = np.einsum("pn,en->ep", et.shape(pts), Te)
    D = conductivity_matrix(batch.region.material, batch.region.material_angle, T_pts, mesh.dim)
    return grad, -np.einsum("epij,epj->epi", D, grad)


def _nodal_temperature(problem: CompiledProblem, T: ndarray) -> ndarray:
    """Node temperatures [K] from a solution vector over all DOFs."""
    return np.asarray(T, dtype=float)[problem.dofs.field_dofs(TEMPERATURE)]


def _nodal(
    mesh: Mesh, problem: CompiledProblem, T: ndarray, which: int
) -> dict[int, tuple[ndarray, ndarray]]:
    """Region-wise nodal average of the gradient (``which = 0``) or the flux (``1``)."""
    nodal_T = _nodal_temperature(problem, T)
    total: dict[int, ndarray] = {}
    count: dict[int, ndarray] = {}
    for batch in element_batches(problem):
        values = _at_points(problem, batch, nodal_T, element(batch.etype).node_coords)[which]
        acc = total.setdefault(batch.region_id, np.zeros((mesh.n_nodes, mesh.dim)))
        cnt = count.setdefault(batch.region_id, np.zeros(mesh.n_nodes))
        np.add.at(acc, batch.conn.ravel(), values.reshape(-1, mesh.dim))
        np.add.at(cnt, batch.conn.ravel(), 1.0)
    out: dict[int, tuple[ndarray, ndarray]] = {}
    for region_id, acc in total.items():
        nodes = np.flatnonzero(count[region_id] > 0)
        out[region_id] = (nodes, acc[nodes] / count[region_id][nodes, None])
    return out


def nodal_flux(
    mesh: Mesh, problem: CompiledProblem, T: ndarray
) -> dict[int, tuple[ndarray, ndarray]]:
    """Heat flux at the nodes, averaged within each region (Theory §7).

    Parameters
    ----------
    mesh : Mesh
        The mesh of ``problem``.
    problem : CompiledProblem
        Supplies the materials of each region.
    T : ndarray, shape (n_dofs,)
        Solution vector [K].

    Returns
    -------
    dict of int to (node_idx, q)
        For each region id: the indices of its nodes, ascending, and the flux
        ``q`` [W/m^2] of shape ``(n, dim)`` at them. A node on an interface appears in
        both regions, with one value each.
    """
    return _nodal(mesh, problem, T, 1)


def gradient(
    mesh: Mesh, problem: CompiledProblem, T: ndarray
) -> dict[int, tuple[ndarray, ndarray]]:
    """Temperature gradient at the nodes, averaged within each region.

    Parameters and return value are as for :func:`nodal_flux`, with the gradient
    ``grad T`` [K/m] in place of the flux.
    """
    return _nodal(mesh, problem, T, 0)


def _elemental(mesh: Mesh, problem: CompiledProblem, T: ndarray, which: int) -> ndarray:
    nodal_T = _nodal_temperature(problem, T)
    n = 1 + max((int(b.elem_ids.max()) for b in mesh.blocks if b.elem_ids.size), default=-1)
    out = np.full((n, mesh.dim), np.nan)
    for batch in element_batches(problem):
        centroid = element(batch.etype).quadrature[0].mean(axis=0, keepdims=True)
        out[batch.elem_ids] = _at_points(problem, batch, nodal_T, centroid)[which][:, 0]
    return out


def element_flux(mesh: Mesh, problem: CompiledProblem, T: ndarray) -> ndarray:
    """Heat flux at the centroid of every element.

    Parameters
    ----------
    mesh, problem, T
        As for :func:`nodal_flux`.

    Returns
    -------
    ndarray, shape (n_elements, dim)
        Flux [W/m^2], indexed by global element id.
    """
    return _elemental(mesh, problem, T, 1)


def element_gradient(mesh: Mesh, problem: CompiledProblem, T: ndarray) -> ndarray:
    """Temperature gradient [K/m] at the centroid of every element, by global element id."""
    return _elemental(mesh, problem, T, 0)
