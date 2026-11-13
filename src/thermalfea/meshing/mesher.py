"""Mesh generation with gmsh and extraction into a plain :class:`Mesh` (Data §2).

``generate(model, built)`` meshes the geometry held by the gmsh session, then copies the
result into NumPy arrays: nodes renumbered to dense 0-based indices, elements grouped by
registered element type, and one facet per element side lying on a geometry curve,
oriented with its parent element on the left.
"""

from __future__ import annotations

import logging
from types import ModuleType

import numpy as np
from numpy import ndarray

from ..core.errors import MeshError, ModelError
from ..core.mesh import ElementBlock, FacetBlock, Mesh, jacobians
from ..core.registry import ElementType, element, element_by_gmsh_type
from ..geometry.builder import BuiltGeometry
from ..geometry.gmsh_session import GmshSession
from ..model.model import Model
from ..model.selections import StaleSelectionError, resolve

log = logging.getLogger(__name__)

_ALGORITHMS = {"delaunay": 5, "frontal": 6, "frontal_quad": 8}
_SPATIAL = 3  # gmsh always returns three coordinates per node
_LINE_ENDS = 2  # a line facet is identified by its two end nodes (stored first)
_MAX_SIDES_PER_EDGE = 2  # boundary edge: one element; interface edge: two


def _top_dim(built: BuiltGeometry) -> int:
    """Dimension of the meshed entities: the highest dimension that has entities."""
    for dim in (2, 1, 0):
        if built.entities(dim):
            return dim
    raise MeshError("the geometry is empty; there is nothing to mesh")


# ------------------------------------------------------------------------- generation


def apply_settings(gmsh: ModuleType, model: Model, built: BuiltGeometry, dim: int) -> None:
    """Translate the model's :class:`MeshSettings` into gmsh options and constraints."""
    settings = model.mesh_settings
    option = gmsh.option.setNumber
    option("Mesh.MeshSizeMin", 0.0)
    option("Mesh.MeshSizeMax", settings.global_size)
    option("Mesh.MeshSizeExtendFromBoundary", 1)
    option("Mesh.MeshSizeFromPoints", 1)
    option("Mesh.MeshSizeFromCurvature", 0)
    option("Mesh.Algorithm", _ALGORITHMS[settings.algorithm])
    option("Mesh.ElementOrder", settings.order)
    option("Mesh.SecondOrderIncomplete", 1)  # 8-node, not 9-node, quads
    option("Mesh.Smoothing", settings.smoothing_passes)
    option("Mesh.RecombineAll", 0)
    gmsh.model.mesh.setSize(gmsh.model.getEntities(0), settings.global_size)
    if settings.element_shape == "quad":
        for tag in built.entities(dim):
            gmsh.model.mesh.setRecombine(dim, tag)


# ------------------------------------------------------------------------- extraction


def _reversal_permutation(et: ElementType) -> ndarray:
    """Node permutation that reverses the orientation of an element with line facets.

    The corners are reversed keeping the first one, and each mid-side node follows the
    side it lies on. Derived from the registered facet table, so it holds for any element
    whose facets form a closed chain of lines.
    """
    facets = np.asarray(et.facets)
    corners = facets[:, 0]
    new_corners = np.concatenate([corners[:1], corners[:0:-1]])
    perm = list(new_corners)
    by_ends = {frozenset((int(f[0]), int(f[1]))): f for f in facets}
    n = len(new_corners)
    for i in range(n):  # loop over the sides of one reference element
        side = by_ends[frozenset((int(new_corners[i]), int(new_corners[(i + 1) % n])))]
        perm.extend(int(v) for v in side[:1:-1])
    return np.asarray(perm, dtype=np.int64)


def _element_blocks(
    gmsh: ModuleType, built: BuiltGeometry, dim: int, index_of: ndarray, nodes: ndarray
) -> list[ElementBlock]:
    conn_by_type: dict[str, list[ndarray]] = {}
    region_by_type: dict[str, list[ndarray]] = {}
    for tag in sorted(built.entities(dim)):
        types, _, node_tags = gmsh.model.mesh.getElements(dim, tag)
        for gmsh_type, flat in zip(types, node_tags, strict=True):
            try:
                et = element_by_gmsh_type(int(gmsh_type))
            except ModelError:
                raise MeshError(
                    f"gmsh produced elements of unsupported type {int(gmsh_type)}"
                ) from None
            if et.dim != dim:
                raise MeshError(f"element type {et.name} cannot be used in a {dim}D mesh")
            conn = index_of[np.asarray(flat, dtype=np.int64).reshape(-1, et.n_nodes)]
            conn_by_type.setdefault(et.name, []).append(conn)
            region_by_type.setdefault(et.name, []).append(
                np.full(conn.shape[0], tag, dtype=np.int32)
            )
    blocks: list[ElementBlock] = []
    next_id = 0
    for name in sorted(conn_by_type):
        et = element(name)
        conn = np.concatenate(conn_by_type[name])
        # gmsh orients elements with the surface normal, which may point to -z
        centre = et.quadrature[0].mean(axis=0, keepdims=True)
        inverted = np.linalg.det(jacobians(name, nodes[conn], centre)[:, 0]) < 0.0
        if inverted.any():
            conn[inverted] = conn[inverted][:, _reversal_permutation(et)]
        n = conn.shape[0]
        blocks.append(
            ElementBlock(
                etype=name,
                conn=conn,
                region=np.concatenate(region_by_type[name]),
                elem_ids=np.arange(next_id, next_id + n, dtype=np.int64),
            )
        )
        next_id += n
    if not blocks:
        raise MeshError("gmsh produced no elements")
    return blocks


def _side_table(blocks: list[ElementBlock], n_nodes: int) -> dict[str, tuple[ndarray, ...]]:
    """All element sides, per facet type, sorted by (end-node key, region, element id)."""
    parts: dict[str, list[tuple[ndarray, ndarray, ndarray]]] = {}
    for b in blocks:
        et = element(b.etype)
        sides = b.conn[:, et.facets]  # (e, n_sides, n_side_nodes)
        n_sides = sides.shape[1]
        flat = sides.reshape(-1, sides.shape[-1])
        parts.setdefault(et.facet_type, []).append(
            (flat, np.repeat(b.elem_ids, n_sides), np.repeat(b.region, n_sides))
        )
    table: dict[str, tuple[ndarray, ...]] = {}
    for facet_type, items in parts.items():
        conn = np.concatenate([i[0] for i in items])
        elem = np.concatenate([i[1] for i in items])
        region = np.concatenate([i[2] for i in items])
        key = _end_key(conn, n_nodes)
        order = np.lexsort((elem, region, key))
        table[facet_type] = (key[order], conn[order], elem[order])
    return table


def _end_key(conn: ndarray, n_nodes: int) -> ndarray:
    """One integer per side or edge, the same for both directions of travel."""
    ends = np.sort(conn[:, :_LINE_ENDS], axis=1)
    return ends[:, 0] * np.int64(n_nodes) + ends[:, 1]


def _facet_blocks(
    gmsh: ModuleType,
    built: BuiltGeometry,
    dim: int,
    index_of: ndarray,
    blocks: list[ElementBlock],
    n_nodes: int,
) -> list[FacetBlock]:
    sides = _side_table(blocks, n_nodes)
    collected: dict[str, list[tuple[ndarray, ndarray, ndarray]]] = {}
    for tag in sorted(built.entities(dim - 1)):
        types, _, node_tags = gmsh.model.mesh.getElements(dim - 1, tag)
        for gmsh_type, flat in zip(types, node_tags, strict=True):
            try:
                ft = element_by_gmsh_type(int(gmsh_type))
            except ModelError:
                raise MeshError(
                    f"gmsh produced boundary elements of unsupported type {int(gmsh_type)}"
                ) from None
            if ft.name not in sides:
                raise MeshError(f"boundary elements of type {ft.name} match no element side")
            edges = index_of[np.asarray(flat, dtype=np.int64).reshape(-1, ft.n_nodes)]
            key, side_conn, side_elem = sides[ft.name]
            wanted = _end_key(edges, n_nodes)
            first = np.searchsorted(key, wanted, side="left")
            count = np.searchsorted(key, wanted, side="right") - first
            bad = (count < 1) | (count > _MAX_SIDES_PER_EDGE)
            if bad.any():
                raise MeshError(
                    f"curve {tag}: {int(bad.sum())} edge(s) do not lie on exactly one or "
                    "two elements"
                )
            # the first match has the lowest region id; its side is already oriented with
            # that element on the left, mid-side node included
            collected.setdefault(ft.name, []).append(
                (side_conn[first], np.full(edges.shape[0], tag, dtype=np.int32), side_elem[first])
            )
    return [
        FacetBlock(
            etype=name,
            conn=np.concatenate([c[0] for c in items]),
            entity=np.concatenate([c[1] for c in items]),
            parent_elem=np.concatenate([c[2] for c in items]),
        )
        for name, items in sorted(collected.items())
    ]


def extract(gmsh: ModuleType, model: Model, built: BuiltGeometry, dim: int) -> Mesh:
    """Copy the current gmsh mesh into a :class:`Mesh`."""
    all_tags, coords, _ = gmsh.model.mesh.getNodes()
    all_tags = np.asarray(all_tags, dtype=np.int64)
    if all_tags.size == 0:
        raise MeshError("gmsh produced no nodes")
    coords = np.asarray(coords, dtype=float).reshape(-1, _SPATIAL)

    # nodes used by the elements, renumbered densely in order of their gmsh tag
    used_tags = []
    for tag in built.entities(dim):
        _, _, node_tags = gmsh.model.mesh.getElements(dim, tag)
        used_tags.extend(np.asarray(t, dtype=np.int64) for t in node_tags)
    if not used_tags:
        raise MeshError("gmsh produced no elements")
    used = np.unique(np.concatenate(used_tags))
    index_of = np.full(int(all_tags.max()) + 1, -1, dtype=np.int64)
    index_of[used] = np.arange(used.size)
    position = np.full(int(all_tags.max()) + 1, -1, dtype=np.int64)
    position[all_tags] = np.arange(all_tags.size)
    nodes = coords[position[used], :dim].copy()

    blocks = _element_blocks(gmsh, built, dim, index_of, nodes)
    facets = _facet_blocks(gmsh, built, dim, index_of, blocks, used.size)

    point_nodes: dict[int, int] = {}
    for tag in built.points:
        tags, _, _ = gmsh.model.mesh.getNodes(0, tag)
        if len(tags) and index_of[int(tags[0])] >= 0:
            point_nodes[tag] = int(index_of[int(tags[0])])

    node_sets: dict[str, ndarray] = {}
    for name, selection in model.selections.items():
        try:
            tags = resolve(selection, built)
        except StaleSelectionError:
            continue  # reported by validation, not here
        found = [
            np.asarray(gmsh.model.mesh.getNodes(selection.dim, t, includeBoundary=True)[0])
            for t in tags
        ]
        idx = index_of[np.concatenate(found).astype(np.int64)] if found else np.empty(0, int)
        node_sets[name] = np.unique(idx[idx >= 0])

    return Mesh(
        dim=dim,
        nodes=nodes,
        blocks=blocks,
        facets=facets,
        node_sets=node_sets,
        point_nodes=point_nodes,
        axisymmetric=model.axisymmetric,
    )


def generate(model: Model, built: BuiltGeometry) -> Mesh:
    """Mesh a built geometry.

    Parameters
    ----------
    model : Model
        Supplies the mesh settings, the selections and the analysis type.
    built : BuiltGeometry
        The current build of the model; its gmsh model must still be in the session.

    Returns
    -------
    Mesh
        Validated mesh. The region id of an element is the tag of its surface; the
        entity of a facet is the tag of its curve.

    Raises
    ------
    MeshError
        If gmsh fails or produces something unusable.
    GeometryError
        If the geometry has been rebuilt since ``built`` was made.
    """
    dim = _top_dim(built)
    with GmshSession.get().use(built.serial) as gmsh:
        try:
            gmsh.model.mesh.clear()
            apply_settings(gmsh, model, built, dim)
            gmsh.model.mesh.generate(dim)
        except MeshError:
            raise
        except Exception as exc:  # gmsh raises plain Exception
            raise MeshError(f"gmsh could not mesh the geometry: {exc}") from exc
        mesh = extract(gmsh, model, built, dim)
    mesh.validate()
    log.info("mesh: %d nodes, %d elements", mesh.n_nodes, mesh.n_elements)
    return mesh
