"""V-33 — patch test.

An irregular 8-element patch with a linear temperature field imposed on the boundary:
interior nodes exact to 1e-12, flux constant to 1e-10, all element types.
"""

from __future__ import annotations

import numpy as np
import pytest
from kernel_solve import boundary_nodes, gauss_point_flux, solve_conduction

from thermalfea.core.meshgen import distort, rect_mesh
from thermalfea.core.registry import element

K = 50.0
GRAD = np.array([120.0, -75.0])  # K/m
T_REF = 300.0
BOX = (0.2, -0.1, 1.3, 0.8)


def grid(etype: str) -> tuple[int, int]:
    """Cells giving eight elements: 2 x 2 cells of two triangles, or 4 x 2 quads."""
    return (2, 2) if len(element(etype).facets) == 3 else (4, 2)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("etype", ["T3", "Q4", "T6", "Q8"])
def test_v33_patch(etype: str, seed: int) -> None:
    regular = rect_mesh(*BOX, *grid(etype), etype)
    mesh = distort(regular, 0.2, seed)
    mesh.validate()
    assert mesh.n_elements == 8

    exact = T_REF + mesh.nodes @ GRAD
    fixed = boundary_nodes(mesh)
    interior = np.setdiff1d(np.arange(mesh.n_nodes), fixed)
    assert interior.size >= 1
    # the patch really is irregular: every interior node is off the regular lattice
    assert np.all(np.any(regular.nodes[interior] != mesh.nodes[interior], axis=1))

    temperature = solve_conduction(mesh, K, fixed, exact[fixed])

    assert np.max(np.abs(temperature[interior] - exact[interior]) / exact[interior]) < 1e-12
    q_exact = -K * GRAD
    scale = np.linalg.norm(q_exact)
    for q in gauss_point_flux(mesh, K, temperature):
        assert np.max(np.abs(q - q_exact)) / scale < 1e-10
