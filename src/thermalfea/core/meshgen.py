"""Hand-built test meshes that need no geometry kernel.

:func:`rect_mesh` meshes a rectangle with any registered planar element type and
:func:`distort` perturbs the interior nodes. Both are used by the unit and verification
tests of the FE kernel.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from .errors import MeshError
from .mesh import ElementBlock, FacetBlock, Mesh
from .registry import ElementType, element

BOTTOM, RIGHT, TOP, LEFT = 1, 2, 3, 4

# Vertices (in unit-cell coordinates) of the reference shapes that tile one grid cell.
_CELL_SPLITS: dict[int, ndarray] = {
    # simplex reference element (three facets): two triangles per cell
    3: np.array([[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]], [[0.0, 0.0], [1.0, 1.0], [0.0, 1.0]]]),
    # bi-unit square reference element (four facets): the cell itself
    4: np.array([[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]]),
}


def _cell_node_offsets(et: ElementType) -> ndarray:
    """Integer lattice offsets of the nodes of each element in one grid cell.

    The lattice has ``et.order`` intervals per cell side. The offsets are found by mapping
    the reference node coordinates through the linear (corner) map of each sub-shape.

    Returns
    -------
    ndarray, shape (n_sub, n_nodes, 2), int64
    """
    if et.facets is None or len(et.facets) not in _CELL_SPLITS:
        raise MeshError(f"rect_mesh does not support element type {et.name!r}")
    corners = _CELL_SPLITS[len(et.facets)]  # (n_sub, n_corner, 2)
    # Affine map of the reference element onto each sub-shape, fixed by the images of the
    # first, second and last corner (the sub-shapes are parallelograms or triangles).
    ref = et.node_coords
    last = corners.shape[1] - 1
    ref_edges = np.stack([ref[1] - ref[0], ref[last] - ref[0]], axis=-1)
    cell_edges = np.stack(
        [corners[:, 1] - corners[:, 0], corners[:, last] - corners[:, 0]], axis=-1
    )
    affine = cell_edges @ np.linalg.inv(ref_edges)  # (n_sub, 2, 2)
    unit = corners[:, :1] + np.einsum("sij,nj->sni", affine, ref - ref[0])
    offsets = unit * et.order
    rounded = np.rint(offsets)
    if not np.allclose(offsets, rounded, atol=1e-12):
        raise MeshError(f"nodes of element type {et.name!r} do not lie on a regular lattice")
    return rounded.astype(np.int64)


def rect_mesh(
    x0: float,
    y0: float,
    w: float,
    h: float,
    nx: int,
    ny: int,
    etype: str,
    region: int = 1,
) -> Mesh:
    """Structured mesh of an axis-aligned rectangle.

    Parameters
    ----------
    x0, y0 : float
        Lower-left corner [m].
    w, h : float
        Width and height [m].
    nx, ny : int
        Number of grid cells in x and y. Triangle types give two elements per cell.
    etype : str
        Registered planar element type, e.g. ``"T3"``, ``"Q4"``, ``"T6"``, ``"Q8"``.
    region : int
        Region id given to every element.

    Returns
    -------
    Mesh
        Facets are tagged with entity 1 (bottom), 2 (right), 3 (top), 4 (left) and
        oriented with the parent element on the left. ``point_nodes`` maps the corner
        points 1..4 (counter-clockwise from the lower-left corner) to their nodes.
    """
    if nx < 1 or ny < 1:
        raise MeshError("rect_mesh needs nx >= 1 and ny >= 1")
    if w <= 0.0 or h <= 0.0:
        raise MeshError("rect_mesh needs positive width and height")
    et = element(etype)
    offsets = _cell_node_offsets(et)  # (n_sub, n_nodes, 2)
    n_sub = offsets.shape[0]
    imax, jmax = et.order * nx, et.order * ny

    cx, cy = np.meshgrid(np.arange(nx), np.arange(ny), indexing="xy")
    origin = et.order * np.stack([cx.ravel(), cy.ravel()], axis=-1)  # (n_cells, 2)
    ij = (origin[:, None, None, :] + offsets[None]).reshape(-1, et.n_nodes, offsets.shape[-1])
    lattice_id = ij[..., 0] + (imax + 1) * ij[..., 1]  # (n_elem, n_nodes)

    used, conn = np.unique(lattice_id, return_inverse=True)
    conn = conn.reshape(lattice_id.shape).astype(np.int64)
    li, lj = used % (imax + 1), used // (imax + 1)
    nodes = np.column_stack([x0 + w * li / imax, y0 + h * lj / jmax])

    n_elem = nx * ny * n_sub
    block = ElementBlock(
        etype=etype,
        conn=conn,
        region=np.full(n_elem, region, dtype=np.int32),
        elem_ids=np.arange(n_elem, dtype=np.int64),
    )

    # boundary facets: element facets whose nodes all lie on one side of the rectangle
    fi = ij[:, et.facets, 0]  # (n_elem, n_facets, n_facet_nodes)
    fj = ij[:, et.facets, 1]
    fconn = conn[:, et.facets]
    sides = [
        (BOTTOM, (fj == 0).all(-1)),
        (RIGHT, (fi == imax).all(-1)),
        (TOP, (fj == jmax).all(-1)),
        (LEFT, (fi == 0).all(-1)),
    ]
    f_conn, f_entity, f_parent = [], [], []
    for tag, mask in sides:
        elem_idx, _ = np.nonzero(mask)
        f_conn.append(fconn[mask])
        f_entity.append(np.full(elem_idx.size, tag, dtype=np.int32))
        f_parent.append(block.elem_ids[elem_idx])
    facets = FacetBlock(
        etype=et.facet_type,
        conn=np.concatenate(f_conn),
        entity=np.concatenate(f_entity),
        parent_elem=np.concatenate(f_parent),
    )

    lattice_to_node = {int(v): k for k, v in enumerate(used)}
    corners = [(0, 0), (imax, 0), (imax, jmax), (0, jmax)]
    point_nodes = {
        tag: lattice_to_node[i + (imax + 1) * j] for tag, (i, j) in enumerate(corners, start=1)
    }
    return Mesh(
        dim=et.dim,
        nodes=nodes,
        blocks=[block],
        facets=[facets],
        point_nodes=point_nodes,
    )


def distort(mesh: Mesh, amplitude: float, seed: int) -> Mesh:
    """Return a copy of a mesh with its interior nodes randomly displaced.

    Nodes on any facet block (the boundary and interfaces) stay where they are, so the
    shape of the domain is unchanged.

    Parameters
    ----------
    mesh : Mesh
        Mesh to perturb; it is not modified.
    amplitude : float
        Largest displacement per coordinate, as a fraction of the shortest distance
        between two nodes of the same element (dimensionless). Values up to about 0.2
        keep the elements valid.
    seed : int
        Seed of the random generator, for reproducible meshes.

    Returns
    -------
    Mesh
        New mesh sharing no arrays with the input.
    """
    spacing = np.inf
    for b in mesh.blocks:
        x = mesh.nodes[b.conn]
        d = np.linalg.norm(x[:, :, None, :] - x[:, None, :, :], axis=-1)
        d[:, np.arange(d.shape[1]), np.arange(d.shape[1])] = np.inf
        spacing = min(spacing, float(d.min()))
    interior = np.ones(mesh.n_nodes, dtype=bool)
    for fb in mesh.facets:
        interior[fb.conn] = False
    rng = np.random.default_rng(seed)
    shift = rng.uniform(-1.0, 1.0, size=mesh.nodes.shape) * amplitude * spacing
    nodes = mesh.nodes.copy()
    nodes[interior] += shift[interior]
    return Mesh(
        dim=mesh.dim,
        nodes=nodes,
        blocks=[
            ElementBlock(b.etype, b.conn.copy(), b.region.copy(), b.elem_ids.copy())
            for b in mesh.blocks
        ],
        facets=[
            FacetBlock(f.etype, f.conn.copy(), f.entity.copy(), f.parent_elem.copy())
            for f in mesh.facets
        ],
        node_sets={k: np.array(v) for k, v in mesh.node_sets.items()},
        point_nodes=dict(mesh.point_nodes),
        axisymmetric=mesh.axisymmetric,
    )
