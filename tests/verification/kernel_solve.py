"""Helper for the M1 gate cases: steady conduction straight from the FE kernel.

Until the model, term and driver layers exist (M2, M3), the verification cases of the
kernel set nodal values directly on a mesh. Everything here goes through the public
kernel pieces: ``geometry`` -> ``conduction`` -> ``DofMap``/``Assembler`` ->
``solve_partitioned``. Nothing depends on the space dimension or the element type.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from thermalfea.core.mesh import Mesh
from thermalfea.physics.conduction import conduction
from thermalfea.physics.kernel import geometry, gfactor
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.dofs import DofMap
from thermalfea.solver.linear import solve_partitioned


def solve_conduction(
    mesh: Mesh, k: float, fixed_nodes: ndarray, fixed_values: ndarray, thickness: float = 1.0
) -> ndarray:
    """Solve steady isotropic conduction with prescribed nodal temperatures.

    Parameters
    ----------
    mesh : Mesh
        Any mesh of registered elements.
    k : float
        Conductivity [W/(m K)].
    fixed_nodes : ndarray of int
        Nodes with a prescribed temperature.
    fixed_values : ndarray
        Their temperatures [K].
    thickness : float
        Planar thickness [m].

    Returns
    -------
    ndarray, shape (n_nodes,)
        Nodal temperatures [K].
    """
    dofs = DofMap()
    dofs.add_field("T", mesh.n_nodes)
    asm = Assembler(dofs.n_dofs)
    for block in mesh.blocks:
        geom = geometry(block, mesh.nodes)
        d = np.broadcast_to(k * np.eye(mesh.dim), (*geom.dV.shape, mesh.dim, mesh.dim))
        g = gfactor(geom.xgp, mesh.axisymmetric, thickness, mesh.dim)
        asm.add_matrix(dofs.node_dofs("T", block.conn), conduction(geom, d, g))
    u = solve_partitioned(
        asm.matrix(),
        asm.vector(),
        dofs.node_dofs("T", fixed_nodes),
        fixed_values,
        symmetric=True,
    )
    return u[dofs.field_dofs("T")]


def gauss_point_flux(mesh: Mesh, k: float, temperature: ndarray) -> list[ndarray]:
    """Heat flux ``q = -k grad T`` at every integration point, one array per block.

    Returns
    -------
    list of ndarray, each of shape (e, gp, dim)
        Flux [W/m^2].
    """
    out = []
    for block in mesh.blocks:
        geom = geometry(block, mesh.nodes)
        out.append(-k * np.einsum("epin,en->epi", geom.dNdx, temperature[block.conn]))
    return out


def boundary_nodes(mesh: Mesh) -> ndarray:
    """Sorted indices of the nodes on any facet block."""
    return np.unique(np.concatenate([fb.conn.ravel() for fb in mesh.facets]))
