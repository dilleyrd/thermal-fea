"""V-01 — slab with two fixed faces (temperature part; the flux part follows in M3.G).

Slab L = 0.1 m modelled as a strip L x L/10, T(0) = 400 K, T(L) = 300 K, k = 50 W/(m K),
10 elements along x. T(x) is linear. Tolerance 1e-10 (relative).
"""

from __future__ import annotations

import numpy as np
import pytest
from kernel_solve import gauss_point_flux, solve_conduction

from thermalfea.core.meshgen import LEFT, RIGHT, rect_mesh

L, K, T0, TL, TOL = 0.1, 50.0, 400.0, 300.0, 1e-10


@pytest.mark.parametrize("etype", ["T3", "Q4", "T6", "Q8"])
def test_v01_temperature_is_linear(etype: str) -> None:
    mesh = rect_mesh(0.0, 0.0, L, L / 10.0, 10, 1, etype)
    mesh.validate()
    (left,) = mesh.facets_on([LEFT])
    (right,) = mesh.facets_on([RIGHT])
    left_nodes, right_nodes = np.unique(left.conn), np.unique(right.conn)
    fixed = np.concatenate([left_nodes, right_nodes])
    values = np.concatenate([np.full(left_nodes.size, T0), np.full(right_nodes.size, TL)])

    temperature = solve_conduction(mesh, K, fixed, values)

    exact = T0 + (TL - T0) * mesh.nodes[:, 0] / L
    assert np.max(np.abs(temperature - exact) / exact) < TOL

    # flux q = k dT/L everywhere, in the +x direction (checked here at the Gauss points;
    # the recovered nodal flux is verified in M3.G)
    q_exact = K * (T0 - TL) / L
    for q in gauss_point_flux(mesh, K, temperature):
        assert np.max(np.abs(q[..., 0] - q_exact)) / q_exact < TOL
        assert np.max(np.abs(q[..., 1])) / q_exact < TOL
