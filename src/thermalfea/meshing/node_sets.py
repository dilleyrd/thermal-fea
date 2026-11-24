"""Node sets of the selections, found again on an existing mesh (no gmsh).

The mesher writes one node set per selection when it meshes. Selections that are added,
renamed or redefined afterwards (in the GUI, without a remesh) would leave those sets out
of date, and the results file stores them. :func:`node_sets_of` recomputes them from the
mesh arrays alone, so the GUI can refresh them just before a solve.

A selection of the domain dimension takes the nodes of the elements whose region is one
of its entities; one dimension lower, the nodes of the facets on its entities; points,
the node at each point. Each includes the entity's boundary, as ``gmsh.model.mesh.getNodes
(dim, tag, includeBoundary=True)`` does in the mesher.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core.mesh import Mesh
from ..model.selections import StaleSelectionError, resolve

if TYPE_CHECKING:
    from ..geometry.builder import BuiltGeometry
    from ..model.model import Model


def _nodes_on(mesh: Mesh, dim: int, tags: list[int]) -> ndarray | None:
    """Node indices on the entities ``(dim, tags)``; ``None`` if this mesh cannot tell."""
    wanted = np.asarray(sorted(tags), dtype=np.int64)
    found: list[ndarray] = []
    if dim == mesh.dim:
        for block in mesh.blocks:
            found.append(block.conn[np.isin(block.region, wanted)].reshape(-1))
    elif dim == mesh.dim - 1:
        for facets in mesh.facets:
            found.append(facets.conn[np.isin(facets.entity, wanted)].reshape(-1))
    elif dim == 0:
        found.append(
            np.asarray([mesh.point_nodes[t] for t in tags if t in mesh.point_nodes], dtype=int)
        )
    else:
        return None  # an edge of a 3D model: not stored in the mesh arrays
    if not found:
        return np.empty(0, dtype=np.int64)
    return np.unique(np.concatenate(found).astype(np.int64))


def node_sets_of(mesh: Mesh, model: Model, built: BuiltGeometry) -> dict[str, ndarray]:
    """Node set of every resolvable selection of ``model`` on ``mesh``.

    Parameters
    ----------
    mesh : Mesh
        A mesh generated from ``built``.
    model : Model
        Supplies the selections.
    built : BuiltGeometry
        The build the mesh was made from.

    Returns
    -------
    dict of str to ndarray
        Selection name -> sorted node indices. A stale selection is left out (validation
        reports it), as in the mesher; a selection of a dimension the mesh does not store
        keeps the mesher's set if there is one.
    """
    sets: dict[str, ndarray] = {}
    for name, selection in model.selections.items():
        try:
            tags = resolve(selection, built)
        except StaleSelectionError:
            continue
        nodes = _nodes_on(mesh, int(selection.dim), tags)
        if nodes is None:
            if name in mesh.node_sets:
                sets[name] = mesh.node_sets[name]
            continue
        sets[name] = nodes
    return sets
