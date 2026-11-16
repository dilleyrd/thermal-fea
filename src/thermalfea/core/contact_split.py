"""Duplicate the nodes along contact interfaces of a mesh (task M10.1, Theory §11).

Thermal contact needs two sets of nodes along an interface, one per side. The mesher
makes conformal meshes with shared interface nodes, so the interface is opened afterwards:

* the side with the higher region id gets the new nodes;
* an end point of the contact curve is duplicated only if it lies on the outer boundary.

Both rules follow from one construction, which also covers several contact curves meeting
at a point. Around every node of a contact facet, the elements that hold the node are
grouped: two elements belong to the same group when they share a side that contains the
node and is *not* a contact facet. Each group gets its own copy of the node; the group
that contains the lowest region id keeps the original. At an end point inside the body the
elements can be walked all the way round the node without crossing the contact, so there
is one group and no duplication; on the outer boundary the walk is interrupted and the two
sides separate.

The functions work on a plain :class:`~thermalfea.core.mesh.Mesh` in any space dimension;
element sides come from the element registry.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy import ndarray
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .errors import MeshError
from .mesh import ElementBlock, FacetBlock, Mesh
from .registry import element


@dataclass
class SplitMesh:
    """A mesh with opened contact interfaces.

    Attributes
    ----------
    mesh : Mesh
        Copy of the input with the new nodes appended (original nodes keep their index),
        and element and facet connectivity pointing at the right copies. The facets of a
        contact entity keep the nodes of their parent element (the lower region id).
    partner : dict of int to ndarray
        For each contact entity tag, an array over all nodes: ``partner[tag][a]`` is the
        node on the far side that faces node ``a`` of that entity's facets, and -1 for
        nodes that are not on them. Where a node was not duplicated (an interior end
        point) the partner is the node itself.
    origin : ndarray, shape (n_nodes,)
        For every node of the new mesh, the node of the input mesh it came from.
    """

    mesh: Mesh
    partner: dict[int, ndarray] = field(default_factory=dict)
    origin: ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))

    @property
    def n_new(self) -> int:
        """Number of nodes added."""
        return int(np.count_nonzero(self.origin != np.arange(self.origin.size)))


def _sorted_rows(a: ndarray) -> ndarray:
    return np.sort(a, axis=1)


def _row_ids(*arrays: ndarray) -> list[ndarray]:
    """Number equal rows equally across several (n_i, k) integer arrays."""
    stacked = np.vstack(arrays)
    _, inverse = np.unique(stacked, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    bounds = np.cumsum([0] + [a.shape[0] for a in arrays])
    return [inverse[bounds[i] : bounds[i + 1]] for i in range(len(arrays))]


def split_interfaces(mesh: Mesh, entity_tags: Sequence[int]) -> SplitMesh:
    """Open the interfaces that lie on the given geometry entities.

    Parameters
    ----------
    mesh : Mesh
        Conformal mesh; it is not modified.
    entity_tags : sequence of int
        Tags of the contact curves (2D) or surfaces (3D). Every facet on them must be an
        interface between two elements of different regions.

    Returns
    -------
    SplitMesh

    Raises
    ------
    MeshError
        If a facet on a contact entity does not separate two regions.
    """
    tags = sorted({int(t) for t in entity_tags})
    n_nodes = mesh.n_nodes
    origin = np.arange(n_nodes, dtype=np.int64)
    contact_facets = mesh.facets_on(tags)
    if not contact_facets:
        partner = {t: np.full(n_nodes, -1, dtype=np.int64) for t in tags}
        return SplitMesh(_copy(mesh, mesh.nodes, None), partner, origin)

    on_contact = np.zeros(n_nodes, dtype=bool)
    for fb in contact_facets:
        on_contact[fb.conn] = True

    # ---- (element, node) incidences at contact nodes, and the sides of those elements
    n_ids = 1 + max(int(b.elem_ids.max()) for b in mesh.blocks if b.elem_ids.size)
    elem_region = np.zeros(n_ids, dtype=np.int64)
    pair_elem: list[ndarray] = []
    pair_node: list[ndarray] = []
    sides: dict[int, list[tuple[ndarray, ndarray]]] = {}  # nodes per side -> (nodes, elem)
    for b in mesh.blocks:
        elem_region[b.elem_ids] = b.region
        touching = on_contact[b.conn]
        rows = touching.any(axis=1)
        if not rows.any():
            continue
        conn, ids = b.conn[rows], b.elem_ids[rows]
        mask = touching[rows]
        pair_elem.append(np.broadcast_to(ids[:, None], conn.shape)[mask])
        pair_node.append(conn[mask])
        local = element(b.etype).facets
        side_nodes = conn[:, local]  # (e, n_sides, k)
        k = side_nodes.shape[-1]
        sides.setdefault(k, []).append(
            (side_nodes.reshape(-1, k), np.repeat(ids, side_nodes.shape[1]))
        )
    p_elem = np.concatenate(pair_elem)
    p_node = np.concatenate(pair_node)
    keys = p_elem * n_nodes + p_node
    order = np.argsort(keys)
    keys, p_elem, p_node = keys[order], p_elem[order], p_node[order]

    def pair_index(elems: ndarray, nodes: ndarray) -> ndarray:
        return np.searchsorted(keys, elems * n_nodes + nodes)

    # ---- link the incidences of one node across every shared side that is not a contact
    link_a: list[ndarray] = []
    link_b: list[ndarray] = []
    other_of: dict[int, tuple[ndarray, ndarray, ndarray]] = {}  # k -> side ids, elem pairs
    facet_side: dict[int, list[tuple[FacetBlock, ndarray]]] = {}
    for k, parts in sides.items():
        nodes_k = np.vstack([p[0] for p in parts])
        elem_k = np.concatenate([p[1] for p in parts])
        facets_k = [fb for fb in contact_facets if fb.conn.shape[1] == k]
        ids = _row_ids(_sorted_rows(nodes_k), *[_sorted_rows(fb.conn) for fb in facets_k])
        side_id = ids[0]
        for fb, fid in zip(facets_k, ids[1:], strict=True):
            facet_side.setdefault(k, []).append((fb, fid))
        contact_ids = (
            np.unique(np.concatenate(ids[1:])) if facets_k else np.empty(0, dtype=np.int64)
        )
        srt = np.argsort(side_id, kind="stable")
        sid = side_id[srt]
        twin = np.flatnonzero(sid[1:] == sid[:-1])  # sides held by two elements
        first, second = srt[twin], srt[twin + 1]
        shared_id = sid[twin]
        other_of[k] = (shared_id, elem_k[first], elem_k[second])
        free = ~np.isin(shared_id, contact_ids)
        f1, f2 = first[free], second[free]
        nodes = nodes_k[f1]  # (m, k): the nodes of each shared, non-contact side
        e1 = np.broadcast_to(elem_k[f1][:, None], nodes.shape)
        e2 = np.broadcast_to(elem_k[f2][:, None], nodes.shape)
        use = on_contact[nodes]
        link_a.append(pair_index(e1[use], nodes[use]))
        link_b.append(pair_index(e2[use], nodes[use]))
    for fb in contact_facets:
        if fb.conn.shape[1] not in sides:
            raise MeshError("a facet on a contact curve belongs to no element")

    n_pairs = keys.size
    a = np.concatenate(link_a) if link_a else np.empty(0, dtype=np.int64)
    b_ = np.concatenate(link_b) if link_b else np.empty(0, dtype=np.int64)
    graph = coo_matrix((np.ones(a.size), (a, b_)), shape=(n_pairs, n_pairs))
    n_groups, group = connected_components(graph, directed=False)

    # ---- one node per group: the group with the lowest region keeps the original
    group_node = np.zeros(n_groups, dtype=np.int64)
    group_node[group] = p_node
    group_region = np.full(n_groups, np.iinfo(np.int64).max)
    np.minimum.at(group_region, group, elem_region[p_elem])
    rank = np.lexsort((np.arange(n_groups), group_region, group_node))
    first_of_node = np.ones(n_groups, dtype=bool)
    first_of_node[1:] = group_node[rank][1:] != group_node[rank][:-1]
    new_groups = rank[~first_of_node]
    group_new = group_node.copy()
    group_new[new_groups] = n_nodes + np.arange(new_groups.size)
    pair_new = group_new[group]
    origin = np.concatenate([origin, group_node[new_groups]])
    nodes_out = np.vstack([mesh.nodes, mesh.nodes[group_node[new_groups]]])

    def remap(elems: ndarray, conn: ndarray) -> ndarray:
        """Node numbers of ``conn`` as seen from the elements ``elems`` (one per row)."""
        out = conn.copy()
        mask = on_contact[conn]
        if mask.any():
            e = np.broadcast_to(np.asarray(elems)[:, None], conn.shape)[mask]
            out[mask] = pair_new[pair_index(e, conn[mask])]
        return out

    # ---- partners: the same facet seen from the element on the far side
    partner = {t: np.full(nodes_out.shape[0], -1, dtype=np.int64) for t in tags}
    for k, entries in facet_side.items():
        shared_id, e_first, e_second = other_of[k]
        lookup = np.argsort(shared_id)
        for fb, fid in entries:
            pos = np.searchsorted(shared_id[lookup], fid)
            pos = np.clip(pos, 0, max(shared_id.size - 1, 0))
            found = shared_id.size > 0
            hit = lookup[pos] if found else pos
            ok = found and bool(np.all(shared_id[hit] == fid))
            if not ok:
                raise MeshError(
                    "a facet on a contact curve does not lie between two elements; a "
                    "contact must be an interface between two regions"
                )
            one, two = e_first[hit], e_second[hit]
            far = np.where(one == fb.parent_elem, two, one)
            if np.any((one != fb.parent_elem) & (two != fb.parent_elem)):
                raise MeshError("a contact facet is not a side of its parent element")
            if np.any(elem_region[far] == elem_region[fb.parent_elem]):
                raise MeshError(
                    "a facet on a contact curve has the same region on both sides; a "
                    "contact must be an interface between two regions"
                )
            near_nodes = remap(fb.parent_elem, fb.conn)
            far_nodes = remap(far, fb.conn)
            for tag in np.unique(fb.entity):
                rows = fb.entity == tag
                partner[int(tag)][near_nodes[rows]] = far_nodes[rows]

    return SplitMesh(_copy(mesh, nodes_out, remap), partner, origin)


def _copy(
    mesh: Mesh, nodes: ndarray, remap: Callable[[ndarray, ndarray], ndarray] | None
) -> Mesh:
    """The mesh with new nodes and (when ``remap`` is given) remapped connectivity."""
    blocks = []
    for b in mesh.blocks:
        conn = b.conn.copy() if remap is None else remap(b.elem_ids, b.conn)
        blocks.append(ElementBlock(b.etype, conn, b.region.copy(), b.elem_ids.copy()))
    facets = []
    for fb in mesh.facets:
        conn = fb.conn.copy() if remap is None else remap(fb.parent_elem, fb.conn)
        facets.append(FacetBlock(fb.etype, conn, fb.entity.copy(), fb.parent_elem.copy()))
    return Mesh(
        dim=mesh.dim,
        nodes=np.array(nodes, dtype=float),
        blocks=blocks,
        facets=facets,
        node_sets={name: np.array(idx) for name, idx in mesh.node_sets.items()},
        point_nodes=dict(mesh.point_nodes),
        axisymmetric=mesh.axisymmetric,
    )
