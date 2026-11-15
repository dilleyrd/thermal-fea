"""V-33 — patch test.

An irregular 8-element patch with a linear temperature field imposed on the boundary:
interior nodes exact to 1e-12, flux constant to 1e-10, all element types. Solved with
``ConductionTerm`` and the steady driver; the flux comes from ``post/recovery``.
"""

from __future__ import annotations

import numpy as np
import pytest
from cases import TYPES, boundary_nodes, conduction_problem

from thermalfea.core.meshgen import distort, rect_mesh
from thermalfea.core.registry import element
from thermalfea.post.energy import energy_balance
from thermalfea.post.recovery import element_flux, nodal_flux
from thermalfea.solver.steady import steady_solution

K = 50.0
GRAD = np.array([120.0, -75.0])  # K/m
T_REF = 300.0
BOX = (0.2, -0.1, 1.3, 0.8)


def grid(etype: str) -> tuple[int, int]:
    """Cells giving eight elements: 2 x 2 cells of two triangles, or 4 x 2 quads."""
    return (2, 2) if len(element(etype).facets) == 3 else (4, 2)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("etype", TYPES)
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

    problem = conduction_problem(mesh, K, fixed, exact[fixed])
    result = steady_solution(problem)
    assert result.iterations == 1  # linear: one solve
    temperature = result.T

    assert np.max(np.abs(temperature[interior] - exact[interior]) / exact[interior]) < 1e-12
    q_exact = -K * GRAD
    scale = np.linalg.norm(q_exact)
    (_, q_nodes), = nodal_flux(mesh, problem, temperature).values()
    assert np.max(np.abs(q_nodes - q_exact)) / scale < 1e-10
    assert np.max(np.abs(element_flux(mesh, problem, temperature) - q_exact)) / scale < 1e-10
    # V-34
    balance = energy_balance(problem, temperature, system=result.system)
    assert abs(balance.relative_imbalance) < 1e-8
