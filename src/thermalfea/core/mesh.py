"""Plain mesh container: the only mesh representation the solver and post-processor see.

Written for any space dimension (Data §2, Plan §7). A *facet* is a boundary element of
dimension ``dim - 1`` (an element edge in 2D); an *entity* is the geometry curve (2D) or
surface (3D) a facet lies on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy import ndarray

from .errors import MeshError
from .registry import element

_MATRIX_RANK = 2  # rank of the (n, k) node and connectivity arrays; not a space dimension


@dataclass
class ElementBlock:
    """All elements of one type.

    Attributes
    ----------
    etype : str
        Key into the element registry, e.g. ``"T3"``.
    conn : ndarray, shape (n_elem, n_nodes_per_elem), int64
        0-based node indices.
    region : ndarray, shape (n_elem,), int32
        Region id of each element.
    elem_ids : ndarray, shape (n_elem,), int64
        Global element numbers, 0-based and unique across blocks.
    """

    etype: str
    conn: ndarray
    region: ndarray
    elem_ids: ndarray


@dataclass
class FacetBlock:
    """Element facets of one type lying on geometry entities.

    Attributes
    ----------
    etype : str
        Key into the element registry, e.g. ``"L2"``.
    conn : ndarray, shape (n_facet, n_nodes_per_facet), int64
        0-based node indices, oriented so the natural normal points away from the parent
        element (in 2D: the parent element lies on the left).
    entity : ndarray, shape (n_facet,), int32
        Geometry tag of the curve (2D) or surface (3D) each facet lies on.
    parent_elem : ndarray, shape (n_facet,), int64
        Global id of the adjacent element (on an interface: the element on the lower
        region id).
    """

    etype: str
    conn: ndarray
    entity: ndarray
    parent_elem: ndarray


def jacobians(etype: str, coords: ndarray, pts: ndarray | None = None) -> ndarray:
    """Jacobian of the reference-to-physical map of a batch of elements.

    Parameters
    ----------
    etype : str
        Registered element-type name.
    coords : ndarray, shape (n_elem, n_nodes, dim)
        Node coordinates of each element [m].
    pts : ndarray, shape (n_pts, elem_dim), optional
        Reference points; defaults to the element type's quadrature points.

    Returns
    -------
    ndarray, shape (n_elem, n_pts, dim, elem_dim)
        ``J[e, p, i, a] = d x_i / d xi_a`` [m].
    """
    et = element(etype)
    if pts is None:
        pts = et.quadrature[0]
    return np.einsum("pan,eni->epia", et.dshape(pts), coords)


def natural_normals(jac: ndarray) -> ndarray:
    """Un-normalised normal of facets from their Jacobians.

    The normal is the generalised cross product of the ``dim - 1`` tangent columns: in 2D
    a tangent ``(dx, dy)`` gives ``(dy, -dx)`` (to the right of the direction of travel);
    in 3D two tangents give ``t1 x t2``. Its length is the facet measure factor
    ``sqrt(det(J^T J))``.

    Parameters
    ----------
    jac : ndarray, shape (..., dim, dim - 1)
        Facet Jacobians [m].

    Returns
    -------
    ndarray, shape (..., dim)
    """
    dim = jac.shape[-2]
    if jac.shape[-1] != dim - 1:
        raise MeshError(f"facet Jacobian has shape {jac.shape[-2:]}, expected {(dim, dim - 1)}")
    out = np.empty(jac.shape[:-1])
    rows = np.arange(dim)
    for i in range(dim):  # loop over space dimensions only
        minor = jac[..., rows != i, :]
        out[..., i] = (-1.0) ** i * np.linalg.det(minor)
    return out


@dataclass
class Mesh:
    """Finite-element mesh as NumPy arrays.

    Attributes
    ----------
    dim : int
        Space dimension.
    nodes : ndarray, shape (n_nodes, dim), float64
        Node coordinates [m].
    blocks : list of ElementBlock
        Elements grouped by type.
    facets : list of FacetBlock
        Every element facet lying on a geometry entity.
    node_sets : dict of str to ndarray
        Named selection -> node indices.
    point_nodes : dict of int to int
        Geometry point tag -> node index.
    axisymmetric : bool
        True when x is the radius and y the axis of an axisymmetric model.
    """

    dim: int
    nodes: ndarray
    blocks: list[ElementBlock]
    facets: list[FacetBlock] = field(default_factory=list)
    node_sets: dict[str, ndarray] = field(default_factory=dict)
    point_nodes: dict[int, int] = field(default_factory=dict)
    axisymmetric: bool = False

    # ------------------------------------------------------------------ basic queries

    @property
    def n_nodes(self) -> int:
        """Number of nodes."""
        return int(self.nodes.shape[0])

    @property
    def n_elements(self) -> int:
        """Total number of elements over all blocks."""
        return int(sum(b.conn.shape[0] for b in self.blocks))

    def facets_on(self, entity_tags: Sequence[int]) -> list[FacetBlock]:
        """Return the facets lying on the given geometry entities.

        Parameters
        ----------
        entity_tags : sequence of int
            Geometry tags of curves (2D) or surfaces (3D).

        Returns
        -------
        list of FacetBlock
            One block per facet type that has at least one matching facet.
        """
        tags = np.asarray(list(entity_tags), dtype=np.int64)
        out: list[FacetBlock] = []
        for fb in self.facets:
            mask = np.isin(fb.entity, tags)
            if mask.any():
                out.append(
                    FacetBlock(fb.etype, fb.conn[mask], fb.entity[mask], fb.parent_elem[mask])
                )
        return out

    def region_elements(self, region_id: int) -> list[ElementBlock]:
        """Return the elements of one region.

        Parameters
        ----------
        region_id : int
            Region id.

        Returns
        -------
        list of ElementBlock
            One block per element type that has at least one element in the region.
        """
        out: list[ElementBlock] = []
        for b in self.blocks:
            mask = b.region == region_id
            if mask.any():
                out.append(ElementBlock(b.etype, b.conn[mask], b.region[mask], b.elem_ids[mask]))
        return out

    def element_centroids(self) -> ndarray:
        """Mean node position of every element, indexed by global element id.

        Returns
        -------
        ndarray, shape (max_elem_id + 1, dim)
            Centroids [m]; rows of unused ids are NaN.
        """
        n = 1 + max((int(b.elem_ids.max()) for b in self.blocks if b.elem_ids.size), default=-1)
        out = np.full((n, self.dim), np.nan)
        for b in self.blocks:
            out[b.elem_ids] = self.nodes[b.conn].mean(axis=1)
        return out

    def _facet_normals(self, fb: FacetBlock) -> tuple[ndarray, ndarray]:
        """Natural normal and position at the reference centre of each facet."""
        ft = element(fb.etype)
        centre = ft.quadrature[0].mean(axis=0, keepdims=True)
        coords = self.nodes[fb.conn]
        normal = natural_normals(jacobians(fb.etype, coords, centre)[:, 0])
        position = np.einsum("n,fni->fi", ft.shape(centre)[0], coords)
        return normal, position

    def outward_normals(self, facet_block: FacetBlock) -> ndarray:
        """Unit normals of facets, pointing away from the parent element.

        The normal is evaluated at the reference centre of each facet and oriented away
        from the centroid of the parent element, which is valid in any space dimension.
        For a correctly oriented 2D facet this equals ``(dy, -dx) / length``.

        Parameters
        ----------
        facet_block : FacetBlock
            Facets of this mesh.

        Returns
        -------
        ndarray, shape (n_facet, dim)
            Unit outward normals (dimensionless).
        """
        normal, position = self._facet_normals(facet_block)
        away = position - self.element_centroids()[facet_block.parent_elem]
        sign = np.where(np.einsum("fi,fi->f", normal, away) < 0.0, -1.0, 1.0)
        length = np.linalg.norm(normal, axis=1)
        return normal * (sign / length)[:, None]

    # --------------------------------------------------------------------- validation

    def validate(self) -> None:
        """Check the mesh for consistency.

        Checks array shapes and index ranges, unique element ids, positive Jacobians at
        every integration point, absence of orphan nodes, and facet orientation (each
        facet's nodes belong to its parent element and its natural normal points away
        from that element).

        Raises
        ------
        MeshError
            On the first problem found.
        """
        nodes = self.nodes
        if nodes.ndim != _MATRIX_RANK or nodes.shape[1] != self.dim:
            raise MeshError(f"nodes must have shape (n_nodes, {self.dim}), got {nodes.shape}")
        if not np.all(np.isfinite(nodes)):
            raise MeshError("node coordinates contain non-finite values")
        if not self.blocks:
            raise MeshError("mesh has no elements")
        n_nodes = self.n_nodes

        used = np.zeros(n_nodes, dtype=bool)
        all_ids: list[ndarray] = []
        for b in self.blocks:
            et = element(b.etype)
            if et.dim != self.dim:
                raise MeshError(
                    f"element block {b.etype!r} has dimension {et.dim}, mesh has {self.dim}"
                )
            n_elem = b.conn.shape[0]
            if b.conn.ndim != _MATRIX_RANK or b.conn.shape[1] != et.n_nodes:
                raise MeshError(f"block {b.etype!r}: connectivity has shape {b.conn.shape}")
            if b.region.shape != (n_elem,) or b.elem_ids.shape != (n_elem,):
                raise MeshError(f"block {b.etype!r}: region/elem_ids length mismatch")
            if n_elem == 0:
                continue
            if b.conn.min() < 0 or b.conn.max() >= n_nodes:
                raise MeshError(f"block {b.etype!r}: node index out of range")
            if b.elem_ids.min() < 0:
                raise MeshError(f"block {b.etype!r}: negative element id")
            det = np.linalg.det(jacobians(b.etype, nodes[b.conn]))
            if not np.all(det > 0.0):
                bad = b.elem_ids[np.any(~(det > 0.0), axis=1)]
                raise MeshError(
                    f"block {b.etype!r}: {bad.size} element(s) with non-positive Jacobian "
                    f"(first ids: {bad[:5].tolist()})"
                )
            used[b.conn] = True
            all_ids.append(b.elem_ids)

        ids = np.concatenate(all_ids) if all_ids else np.empty(0, dtype=np.int64)
        if np.unique(ids).size != ids.size:
            raise MeshError("element ids are not unique across blocks")
        if not used.all():
            orphans = np.flatnonzero(~used)
            raise MeshError(
                f"{orphans.size} orphan node(s) not used by any element "
                f"(first: {orphans[:5].tolist()})"
            )

        # global element id -> (block index, row) lookup
        n_ids = int(ids.max()) + 1 if ids.size else 0
        id_block = np.full(n_ids, -1, dtype=np.int64)
        id_row = np.zeros(n_ids, dtype=np.int64)
        for ib, b in enumerate(self.blocks):
            id_block[b.elem_ids] = ib
            id_row[b.elem_ids] = np.arange(b.conn.shape[0])
        centroids = self.element_centroids()

        for fb in self.facets:
            ft = element(fb.etype)
            if ft.dim != self.dim - 1:
                raise MeshError(
                    f"facet block {fb.etype!r} has dimension {ft.dim}, expected {self.dim - 1}"
                )
            n_facet = fb.conn.shape[0]
            if fb.conn.ndim != _MATRIX_RANK or fb.conn.shape[1] != ft.n_nodes:
                raise MeshError(f"facet block {fb.etype!r}: connectivity has shape {fb.conn.shape}")
            if fb.entity.shape != (n_facet,) or fb.parent_elem.shape != (n_facet,):
                raise MeshError(f"facet block {fb.etype!r}: entity/parent_elem length mismatch")
            if n_facet == 0:
                continue
            if fb.conn.min() < 0 or fb.conn.max() >= n_nodes:
                raise MeshError(f"facet block {fb.etype!r}: node index out of range")
            parent = fb.parent_elem
            if parent.min() < 0 or parent.max() >= n_ids or np.any(id_block[parent] < 0):
                raise MeshError(f"facet block {fb.etype!r}: parent element id does not exist")
            belongs = np.zeros(n_facet, dtype=bool)
            for ib, b in enumerate(self.blocks):
                sel = id_block[parent] == ib
                if not sel.any():
                    continue
                pconn = b.conn[id_row[parent[sel]]]
                belongs[sel] = (fb.conn[sel][:, :, None] == pconn[:, None, :]).any(-1).all(-1)
            if not belongs.all():
                raise MeshError(
                    f"facet block {fb.etype!r}: {int((~belongs).sum())} facet(s) have nodes "
                    "that are not nodes of their parent element"
                )
            normal, position = self._facet_normals(fb)
            if not np.all(np.linalg.norm(normal, axis=1) > 0.0):
                raise MeshError(f"facet block {fb.etype!r}: degenerate facet")
            outward = np.einsum("fi,fi->f", normal, position - centroids[parent])
            if not np.all(outward > 0.0):
                raise MeshError(
                    f"facet block {fb.etype!r}: {int((~(outward > 0.0)).sum())} facet(s) are "
                    "oriented towards their parent element"
                )

        for name, idx in self.node_sets.items():
            idx = np.asarray(idx)
            if idx.size and (idx.min() < 0 or idx.max() >= n_nodes):
                raise MeshError(f"node set {name!r}: node index out of range")
        for tag, node in self.point_nodes.items():
            if not 0 <= node < n_nodes:
                raise MeshError(f"point {tag}: node index out of range")
