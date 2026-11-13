"""V-37 — extensibility guard: a 3D patch test through the unmodified kernel.

A 4-node tetrahedron ``Tet4`` is registered inside this test only. A unit cube is meshed
with tetrahedra (3 x 3 x 3 cells of six tetrahedra each, so there are interior nodes),
T = 300 + 10x + 20y + 30z is imposed on the boundary, k = 50.

Requirements: interior temperatures exact to 1e-10; flux = (-500, -1000, -1500) in every
element; the integral of a unit flux over one cube face (T3 facets, ``facet_geometry``)
is 1.0. No library code mentions ``Tet4`` or dim = 3.

The solve goes through ``geometry`` -> ``conduction`` -> ``DofMap``/``Assembler`` ->
``solve_partitioned``. ``ConductionTerm`` and the steady driver do not exist until M3;
this test is to be switched to them at M3.G (docs/OPEN_QUESTIONS.md, Q3).
"""

from __future__ import annotations

from itertools import permutations

import numpy as np
import pytest
from kernel_solve import boundary_nodes, gauss_point_flux, solve_conduction

from thermalfea.core import registry
from thermalfea.core.mesh import ElementBlock, FacetBlock, Mesh
from thermalfea.core.registry import ElementType
from thermalfea.physics.kernel import facet_geometry, geometry, gfactor

K = 50.0
GRAD = np.array([10.0, 20.0, 30.0])
N_CELLS = 3


def _tet4_shape(pts: np.ndarray) -> np.ndarray:
    return np.column_stack([1.0 - pts.sum(axis=1), pts])


def _tet4_dshape(pts: np.ndarray) -> np.ndarray:
    dn = np.hstack([-np.ones((3, 1)), np.eye(3)])
    return np.broadcast_to(dn, (pts.shape[0], 3, 4)).copy()


@pytest.fixture
def tet4():
    et = ElementType(
        name="Tet4",
        dim=3,
        n_nodes=4,
        order=1,
        gmsh_type=4,
        shape=_tet4_shape,
        dshape=_tet4_dshape,
        node_coords=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        ),
        quadrature=(np.full((1, 3), 0.25), np.array([1.0 / 6.0])),
        facet_type="T3",
        facets=np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]]),
        display_simplices=np.array([[0, 1, 2, 3]]),
    )
    registry.register_element(et)
    yield et
    registry._ELEMENTS.pop("Tet4")


def cube_mesh(et: ElementType, n: int) -> Mesh:
    """Unit cube of n^3 cells, each split into six tetrahedra, with boundary T3 facets."""
    line = np.arange(n + 1)
    ii, jj, kk = np.meshgrid(line, line, line, indexing="ij")
    ijk = np.column_stack([ii.ravel(), jj.ravel(), kk.ravel()])
    nodes = ijk / n
    node_id = lambda p: (p[..., 0] * (n + 1) + p[..., 1]) * (n + 1) + p[..., 2]  # noqa: E731

    origins = ijk[np.all(ijk < n, axis=1)]
    tets = []
    for perm in permutations(range(3)):
        corners = [np.zeros(3, dtype=int)]
        for axis in perm:
            corners.append(corners[-1] + np.eye(3, dtype=int)[axis])
        tets.append(node_id(origins[:, None, :] + np.array(corners)[None]))
    conn = np.concatenate(tets).astype(np.int64)
    # give every tetrahedron a positive Jacobian
    x = nodes[conn]
    negative = np.linalg.det(x[:, 1:] - x[:, :1]) < 0.0
    conn[negative] = conn[negative][:, [0, 2, 1, 3]]

    n_elem = conn.shape[0]
    block = ElementBlock(
        "Tet4", conn, np.ones(n_elem, dtype=np.int32), np.arange(n_elem, dtype=np.int64)
    )

    # boundary facets: element faces lying in one of the six cube planes
    fconn = conn[:, et.facets]  # (e, 4, 3)
    fx = nodes[fconn]  # (e, 4, 3, 3)
    f_conn, f_entity, f_parent = [], [], []
    tag = 0
    for axis in range(3):
        for value in (0.0, 1.0):
            tag += 1
            mask = np.all(fx[..., axis] == value, axis=-1)
            elem_idx, _ = np.nonzero(mask)
            f_conn.append(fconn[mask])
            f_entity.append(np.full(elem_idx.size, tag, dtype=np.int32))
            f_parent.append(block.elem_ids[elem_idx])
    facets = FacetBlock(
        "T3", np.concatenate(f_conn), np.concatenate(f_entity), np.concatenate(f_parent)
    )
    return Mesh(dim=3, nodes=nodes, blocks=[block], facets=[facets])


def test_v37_3d_patch_test(tet4: ElementType) -> None:
    mesh = cube_mesh(tet4, N_CELLS)
    mesh.validate()  # includes facet orientation by the general outward-normal rule
    assert mesh.n_elements == 6 * N_CELLS**3
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    assert geom.dNdx.shape == (mesh.n_elements, 1, 3, 4)
    assert geom.dV.sum() == pytest.approx(1.0, rel=1e-13)  # cube volume
    np.testing.assert_array_equal(gfactor(geom.xgp, False, 0.5, mesh.dim), 1.0)

    exact = 300.0 + mesh.nodes @ GRAD
    fixed = boundary_nodes(mesh)
    interior = np.setdiff1d(np.arange(mesh.n_nodes), fixed)
    assert interior.size == (N_CELLS - 1) ** 3

    temperature = solve_conduction(mesh, K, fixed, exact[fixed])

    assert np.max(np.abs(temperature[interior] - exact[interior]) / exact[interior]) < 1e-10
    (q,) = gauss_point_flux(mesh, K, temperature)
    np.testing.assert_allclose(
        q, np.broadcast_to([-500.0, -1000.0, -1500.0], q.shape), rtol=1e-10
    )


def test_v37_unit_flux_over_each_cube_face(tet4: ElementType) -> None:
    mesh = cube_mesh(tet4, N_CELLS)
    normals = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
    for tag, normal in enumerate(normals, start=1):
        (face,) = mesh.facets_on([tag])
        assert face.conn.shape == (2 * N_CELLS**2, 3)
        fg = facet_geometry(face, mesh.nodes)
        g = gfactor(fg.xgp, False, 1.0, mesh.dim)
        unit_flux = 1.0
        nodal_load = np.einsum("fp,pn->fn", unit_flux * g * fg.dS, fg.N)
        assert nodal_load.sum() == pytest.approx(1.0, rel=1e-13)
        np.testing.assert_allclose(
            mesh.outward_normals(face), np.tile(normal, (face.conn.shape[0], 1)), atol=1e-14
        )
