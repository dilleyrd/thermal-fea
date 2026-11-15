"""Batches of elements and facets with their integration data, shared by all terms.

A batch is a group of elements (or facets) of one type with everything a term needs to
integrate over it: node and DOF connectivity, geometry, and the geometry factor ``g``
(Theory §1). Element batches are split by region because properties differ per region;
they are computed once per problem and reused by every term.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..core.mesh import ElementBlock
from .kernel import ElemGeom, FacetGeom, facet_geometry, geometry, gfactor

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem, RegionData

FIELD = "T"


@dataclass
class ElementBatch:
    """Elements of one type in one region.

    Attributes
    ----------
    region_id : int
    region : RegionData
        Material, thickness and material angle of the region.
    conn : ndarray, shape (e, n)
        Node indices.
    dofs : ndarray, shape (e, n)
        Temperature DOF numbers.
    elem_ids : ndarray, shape (e,)
        Global element ids.
    geom : ElemGeom
    g : ndarray, shape (e, gp)
        Geometry factor (thickness [m], ``2 pi r`` [m], or 1).
    etype : str
    """

    region_id: int
    region: RegionData
    conn: ndarray
    dofs: ndarray
    elem_ids: ndarray
    geom: ElemGeom
    g: ndarray
    etype: str


@dataclass
class FacetBatch:
    """Facets of one type on a set of geometry entities.

    Attributes
    ----------
    conn : ndarray, shape (f, n)
        Node indices.
    dofs : ndarray, shape (f, n)
        Temperature DOF numbers.
    entity : ndarray, shape (f,)
        Geometry tag of each facet.
    geom : FacetGeom
    g : ndarray, shape (f, gp)
        Geometry factor; the planar thickness is that of the parent element's region.
    etype : str
    """

    conn: ndarray
    dofs: ndarray
    entity: ndarray
    geom: FacetGeom
    g: ndarray
    etype: str


def element_batches(
    problem: CompiledProblem, region_ids: Sequence[int] | None = None
) -> list[ElementBatch]:
    """Return the element batches of a problem, optionally only for some regions.

    Parameters
    ----------
    problem : CompiledProblem
    region_ids : sequence of int, optional
        Region ids to keep; all regions by default.

    Raises
    ------
    ModelError
        If an element belongs to a region that has no properties.
    """
    cache = problem.cache
    if "element_batches" not in cache:
        mesh = problem.mesh
        batches: list[ElementBatch] = []
        for block in mesh.blocks:
            for region_id in np.unique(block.region):
                region = problem.regions.get(int(region_id))
                if region is None:
                    raise ModelError(
                        f"region {int(region_id)} has no material assigned (no region "
                        "assignment covers that surface)"
                    )
                mask = block.region == region_id
                sub = ElementBlock(
                    block.etype, block.conn[mask], block.region[mask], block.elem_ids[mask]
                )
                geom = geometry(sub, mesh.nodes)
                batches.append(
                    ElementBatch(
                        region_id=int(region_id),
                        region=region,
                        conn=sub.conn,
                        dofs=problem.dofs.node_dofs(FIELD, sub.conn),
                        elem_ids=sub.elem_ids,
                        geom=geom,
                        g=gfactor(geom.xgp, mesh.axisymmetric, region.thickness, mesh.dim),
                        etype=block.etype,
                    )
                )
        cache["element_batches"] = batches
    batches = cache["element_batches"]
    if region_ids is None:
        return list(batches)
    wanted = {int(r) for r in region_ids}
    return [b for b in batches if b.region_id in wanted]


def element_thickness(problem: CompiledProblem) -> ndarray:
    """Planar thickness [m] of every element, indexed by global element id."""
    cache = problem.cache
    if "element_thickness" not in cache:
        mesh = problem.mesh
        n = 1 + max((int(b.elem_ids.max()) for b in mesh.blocks if b.elem_ids.size), default=-1)
        out = np.ones(n)
        for batch in element_batches(problem):
            out[batch.elem_ids] = batch.region.thickness
        cache["element_thickness"] = out
    return cache["element_thickness"]


def facet_batches(problem: CompiledProblem, entity_tags: Sequence[int]) -> list[FacetBatch]:
    """Return the facets lying on the given geometry entities, with integration data.

    Parameters
    ----------
    problem : CompiledProblem
    entity_tags : sequence of int
        Tags of curves (2D) or surfaces (3D).
    """
    mesh = problem.mesh
    thickness = element_thickness(problem)
    out: list[FacetBatch] = []
    for fb in mesh.facets_on(entity_tags):
        geom = facet_geometry(fb, mesh.nodes)
        out.append(
            FacetBatch(
                conn=fb.conn,
                dofs=problem.dofs.node_dofs(FIELD, fb.conn),
                entity=fb.entity,
                geom=geom,
                g=gfactor(
                    geom.xgp, mesh.axisymmetric, thickness[fb.parent_elem][:, None], mesh.dim
                ),
                etype=fb.etype,
            )
        )
    return out
