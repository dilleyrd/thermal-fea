"""Mesh quality measures.

Three measures per element, computed for whole blocks at once:

* **minimum angle** [degrees]: the smallest interior angle between the straight lines
  joining consecutive corner nodes (60 for an equilateral triangle, 90 for a rectangle);
* **aspect ratio** (dimensionless): longest corner-to-corner side divided by the shortest
  (1 is best);
* **Jacobian ratio** (dimensionless): smallest Jacobian determinant divided by the largest,
  sampled at the integration points and the nodes (1 for an undistorted element; zero or
  negative means the element is invalid).

The corners of an element are taken from its registered facet table, so the measures work
for any element whose facets are lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy import ndarray

from ..core.mesh import Mesh, jacobians
from ..core.registry import element


@dataclass
class QualityReport:
    """Quality of every element of a mesh. Arrays are ordered by global element id.

    Attributes
    ----------
    elem_ids : ndarray of int64, shape (n_elem,)
        Global element ids, ascending.
    etype : ndarray of str, shape (n_elem,)
        Element type of each element.
    min_angle : ndarray, shape (n_elem,)
        Smallest interior angle [degrees].
    aspect_ratio : ndarray, shape (n_elem,)
        Longest side over shortest side (dimensionless).
    jacobian_ratio : ndarray, shape (n_elem,)
        Smallest over largest Jacobian determinant (dimensionless).
    counts : dict of str to int
        Number of elements per element type.
    n_nodes : int
        Number of nodes of the mesh.
    """

    elem_ids: ndarray
    etype: ndarray
    min_angle: ndarray
    aspect_ratio: ndarray
    jacobian_ratio: ndarray
    counts: dict[str, int] = field(default_factory=dict)
    n_nodes: int = 0

    @property
    def n_elements(self) -> int:
        """Total number of elements."""
        return int(self.elem_ids.size)

    def worst(self, n: int = 10, by: str = "min_angle") -> list[int]:
        """Global ids of the ``n`` worst elements, worst first.

        Parameters
        ----------
        n : int
            Number of elements to return.
        by : {"min_angle", "aspect_ratio", "jacobian_ratio"}
            Measure to rank by (small angles, large aspect ratios and small Jacobian
            ratios are bad).
        """
        values = getattr(self, by)
        order = np.argsort(-values if by == "aspect_ratio" else values, kind="stable")
        return [int(i) for i in self.elem_ids[order[:n]]]

    def summary(self) -> dict[str, float]:
        """Extreme and mean values of the three measures."""
        if self.n_elements == 0:
            return {}
        return {
            "min_angle_min": float(self.min_angle.min()),
            "min_angle_mean": float(self.min_angle.mean()),
            "aspect_ratio_max": float(self.aspect_ratio.max()),
            "aspect_ratio_mean": float(self.aspect_ratio.mean()),
            "jacobian_ratio_min": float(self.jacobian_ratio.min()),
            "jacobian_ratio_mean": float(self.jacobian_ratio.mean()),
        }


def report(mesh: Mesh) -> QualityReport:
    """Compute the quality measures of every element.

    Parameters
    ----------
    mesh : Mesh
        Node coordinates in metres.

    Returns
    -------
    QualityReport
    """
    ids, types, angles, aspects, ratios = [], [], [], [], []
    counts: dict[str, int] = {}
    for b in mesh.blocks:
        et = element(b.etype)
        n = b.conn.shape[0]
        counts[b.etype] = counts.get(b.etype, 0) + n
        if n == 0:
            continue
        corners = mesh.nodes[b.conn[:, np.asarray(et.facets)[:, 0]]]  # (e, n_corner, dim)
        to_next = np.roll(corners, -1, axis=1) - corners
        to_prev = np.roll(corners, 1, axis=1) - corners
        len_next = np.linalg.norm(to_next, axis=-1)
        len_prev = np.linalg.norm(to_prev, axis=-1)
        with np.errstate(divide="ignore", invalid="ignore"):
            cos = np.einsum("eci,eci->ec", to_next, to_prev) / (len_next * len_prev)
            aspect = len_next.max(axis=1) / len_next.min(axis=1)
        angle = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))

        sample = np.vstack([et.quadrature[0], et.node_coords])
        det = np.linalg.det(jacobians(b.etype, mesh.nodes[b.conn], sample))
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = det.min(axis=1) / det.max(axis=1)
        ratio = np.where(det.max(axis=1) > 0.0, ratio, -np.inf)

        ids.append(b.elem_ids)
        types.append(np.full(n, b.etype))
        angles.append(np.nan_to_num(angle.min(axis=1), nan=0.0))
        aspects.append(np.nan_to_num(aspect, nan=np.inf))
        ratios.append(ratio)

    if not ids:
        empty = np.empty(0)
        return QualityReport(
            np.empty(0, dtype=np.int64), np.empty(0, dtype=str), empty, empty, empty,
            counts, mesh.n_nodes,
        )
    elem_ids = np.concatenate(ids)
    order = np.argsort(elem_ids, kind="stable")
    return QualityReport(
        elem_ids=elem_ids[order],
        etype=np.concatenate(types)[order],
        min_angle=np.concatenate(angles)[order],
        aspect_ratio=np.concatenate(aspects)[order],
        jacobian_ratio=np.concatenate(ratios)[order],
        counts=counts,
        n_nodes=mesh.n_nodes,
    )


#: Per-element measures of :class:`QualityReport`, by attribute name.
MEASURES: tuple[str, ...] = ("min_angle", "aspect_ratio", "jacobian_ratio")


def values_in_block_order(mesh: Mesh, quality: QualityReport, measure: str) -> ndarray:
    """One measure per element, in the order of the concatenated element blocks.

    :meth:`thermalfea.gui.scene.SceneView.set_mesh` takes ``color_by`` in this order, while
    the report is ordered by global element id. Non-finite values (an invalid or degenerate
    element) become NaN, which a colour map draws as "no value".

    Parameters
    ----------
    mesh : Mesh
        The mesh the report was made from.
    quality : QualityReport
        ``report(mesh)``.
    measure : {"min_angle", "aspect_ratio", "jacobian_ratio"}
        Attribute of the report to take.

    Returns
    -------
    ndarray, shape (n_elements,)
        Values in the element order of ``mesh.blocks``.
    """
    if measure not in MEASURES:
        raise ValueError(f"unknown quality measure {measure!r}; use one of {MEASURES}")
    values = np.asarray(getattr(quality, measure), dtype=float)
    if not mesh.blocks:
        return np.empty(0)
    ids = np.concatenate([b.elem_ids for b in mesh.blocks])
    if ids.size == 0:
        return np.empty(0)
    picked = values[np.searchsorted(quality.elem_ids, ids)]
    return np.where(np.isfinite(picked), picked, np.nan)
