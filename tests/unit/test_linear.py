"""M1.6 — linear solve with prescribed values (Theory §4)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from thermalfea.core.errors import SolverError
from thermalfea.core.meshgen import rect_mesh
from thermalfea.physics.conduction import conduction
from thermalfea.physics.kernel import geometry, gfactor
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.linear import (
    SuperLUFactorization,
    SuperLUSolver,
    default_solver,
    solve_partitioned,
    split_dofs,
)


def bar(n_elem: int, k: float = 1.0) -> csr_matrix:
    """Conductance matrix of a chain of ``n_elem`` two-node bars, each of conductance k."""
    asm = Assembler(n_elem + 1)
    conn = np.column_stack([np.arange(n_elem), np.arange(1, n_elem + 1)])
    unit = k * np.array([[1.0, -1.0], [-1.0, 1.0]])
    asm.add_matrix(conn, np.broadcast_to(unit, (n_elem, 2, 2)))
    return asm.matrix()


def test_bar_fixed_end_and_end_flux() -> None:
    """T(0) = 10, heat 6 W into the far end, conductance 2 W/K per element."""
    k = bar(3, 2.0)
    f = np.array([0.0, 0.0, 0.0, 6.0])
    t = solve_partitioned(k, f, np.array([0]), np.array([10.0]))
    np.testing.assert_allclose(t, [10.0, 13.0, 16.0, 19.0], rtol=1e-14)
    # reaction at the prescribed node balances the applied heat (Theory §4)
    reaction = (k @ t - f)[0]
    assert reaction == pytest.approx(-6.0)


def test_bar_two_fixed_ends_and_internal_load() -> None:
    k = bar(2)
    f = np.array([0.0, 4.0, 0.0])
    t = solve_partitioned(k, f, np.array([2, 0]), np.array([30.0, 10.0]))
    # middle node: 2 T1 - T0 - T2 = 4  ->  T1 = (4 + 10 + 30) / 2
    np.testing.assert_allclose(t, [10.0, 22.0, 30.0], rtol=1e-14)


def test_all_dofs_prescribed_and_none_prescribed() -> None:
    k = bar(2)
    t = solve_partitioned(k, np.zeros(3), np.array([0, 1, 2]), np.array([1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(t, [1.0, 2.0, 3.0])
    spd = (k + csr_matrix(np.eye(3))).tocsr()
    t = solve_partitioned(spd, np.array([1.0, 2.0, 3.0]), np.array([], dtype=int), np.array([]))
    np.testing.assert_allclose(spd @ t, [1.0, 2.0, 3.0], rtol=1e-13)


def test_singular_system_raises() -> None:
    k = bar(3)
    with pytest.raises(SolverError, match="singular"):
        solve_partitioned(k, np.array([1.0, 0.0, 0.0, -1.0]), np.array([], dtype=int), np.array([]))
    with pytest.raises(SolverError, match="singular"):
        SuperLUFactorization(csr_matrix((4, 4)))
    # a node connected to nothing
    asm = Assembler(3)
    asm.add_matrix(np.array([[0, 1]]), np.array([[[1.0, -1.0], [-1.0, 1.0]]]))
    with pytest.raises(SolverError, match="singular"):
        solve_partitioned(asm.matrix(), np.zeros(3), np.array([0]), np.array([1.0]))


@pytest.mark.parametrize("etype", ["T3", "Q4", "T6", "Q8"])
def test_singular_fe_matrix_without_temperature_reference(etype: str) -> None:
    mesh = rect_mesh(0.0, 0.0, 1.0, 1.0, 6, 5, etype)
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    d = np.broadcast_to(np.eye(mesh.dim), (*geom.dV.shape, mesh.dim, mesh.dim))
    asm = Assembler(mesh.n_nodes)
    asm.add_matrix(block.conn, conduction(geom, d, gfactor(geom.xgp, False, 1.0, mesh.dim)))
    k = asm.matrix()
    with pytest.raises(SolverError, match="singular"):
        solve_partitioned(k, np.zeros(mesh.n_nodes), np.array([], dtype=int), np.array([]))
    # one prescribed node is enough to make it solvable
    t = solve_partitioned(k, np.zeros(mesh.n_nodes), np.array([0]), np.array([7.0]), symmetric=True)
    np.testing.assert_allclose(t, 7.0, rtol=1e-10)


def test_nan_raises() -> None:
    k = bar(2)
    with pytest.raises(SolverError, match="non-finite"):
        solve_partitioned(k, np.array([0.0, np.nan, 0.0]), np.array([0]), np.array([1.0]))
    with pytest.raises(SolverError, match="non-finite"):
        solve_partitioned(k, np.zeros(3), np.array([0]), np.array([np.inf]))
    bad = k.copy().astype(float)
    bad.data[0] = np.nan
    with pytest.raises(SolverError, match="non-finite"):
        solve_partitioned(bad, np.zeros(3), np.array([2]), np.array([1.0]))


def test_bad_arguments_raise() -> None:
    k = bar(2)
    with pytest.raises(SolverError, match="duplicates"):
        solve_partitioned(k, np.zeros(3), np.array([0, 0]), np.array([1.0, 1.0]))
    with pytest.raises(SolverError, match="range"):
        solve_partitioned(k, np.zeros(3), np.array([3]), np.array([1.0]))
    with pytest.raises(SolverError, match="lengths"):
        solve_partitioned(k, np.zeros(3), np.array([0]), np.array([1.0, 2.0]))
    with pytest.raises(SolverError, match="mismatch"):
        solve_partitioned(k, np.zeros(4), np.array([0]), np.array([1.0]))
    with pytest.raises(SolverError, match="square"):
        SuperLUFactorization(csr_matrix((2, 3)))


def test_factorization_is_reusable_and_handles_unsymmetric_matrices() -> None:
    a = csr_matrix(np.array([[4.0, 1.0, 0.0], [2.0, 5.0, 1.0], [0.0, -3.0, 6.0]]))
    fact = default_solver().factorize(a, symmetric=False)
    assert isinstance(default_solver(), SuperLUSolver)
    for b in (np.array([1.0, 2.0, 3.0]), np.array([-5.0, 0.5, 9.0])):
        np.testing.assert_allclose(a @ fact.solve(b), b, rtol=1e-13)
    many = np.arange(6.0).reshape(3, 2)
    np.testing.assert_allclose(a @ fact.solve(many), many, atol=1e-13)
    with pytest.raises(SolverError):
        fact.solve(np.zeros(4))


def test_custom_solver_is_used() -> None:
    calls: list[tuple[tuple[int, int], bool]] = []

    class Recording:
        def factorize(self, A, symmetric):
            calls.append((A.shape, symmetric))
            return SuperLUFactorization(A, symmetric)

    t = solve_partitioned(
        bar(3), np.zeros(4), np.array([0, 3]), np.array([0.0, 3.0]),
        symmetric=True, solver=Recording(),
    )
    np.testing.assert_allclose(t, [0.0, 1.0, 2.0, 3.0], atol=1e-14)
    assert calls == [((2, 2), True)]


def test_split_dofs() -> None:
    free, fixed = split_dofs(5, np.array([3, 1]))
    np.testing.assert_array_equal(free, [0, 2, 4])
    np.testing.assert_array_equal(fixed, [3, 1])
