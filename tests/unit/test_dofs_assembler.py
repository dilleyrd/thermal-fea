"""M1.5 — DOF map (Data §13) and assembler."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse import issparse

from thermalfea.core.errors import ModelError, SolverError
from thermalfea.core.meshgen import rect_mesh
from thermalfea.physics.conduction import conduction
from thermalfea.physics.kernel import geometry, gfactor
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.dofs import DofMap

# ---------------------------------------------------------------------------- DofMap


def test_single_scalar_field() -> None:
    dofs = DofMap()
    assert dofs.n_dofs == 0
    dofs.add_field("T", 5)
    assert dofs.n_dofs == 5
    np.testing.assert_array_equal(dofs.node_dofs("T", np.array([4, 0, 2])), [4, 0, 2])
    conn = np.array([[0, 1, 2], [2, 3, 4]])
    out = dofs.node_dofs("T", conn)
    assert out.shape == conn.shape
    assert out.dtype == np.int64
    np.testing.assert_array_equal(dofs.field_dofs("T"), np.arange(5))


def test_fields_extras_and_components_do_not_overlap() -> None:
    dofs = DofMap()
    dofs.add_extra("pre", 2)
    dofs.add_field("T", 4)
    dofs.add_extra("stream-1", 3)
    dofs.add_field("u", 4, components=2)
    dofs.add_extra("empty", 0)
    assert dofs.n_dofs == 2 + 4 + 3 + 8
    assert dofs.fields == ["T", "u"]
    assert dofs.extras == ["pre", "stream-1", "empty"]
    assert dofs.components("u") == 2
    assert dofs.n_nodes("T") == 4
    nodes = np.arange(4)
    groups = [
        dofs.extra_dofs("pre"),
        dofs.node_dofs("T", nodes),
        dofs.extra_dofs("stream-1"),
        dofs.node_dofs("u", nodes, 0),
        dofs.node_dofs("u", nodes, component=1),
        dofs.extra_dofs("empty"),
    ]
    everything = np.concatenate(groups)
    assert np.unique(everything).size == everything.size == dofs.n_dofs
    np.testing.assert_array_equal(np.sort(everything), np.arange(dofs.n_dofs))
    # the node index is not the DOF index once anything precedes the field
    assert dofs.node_dofs("T", np.array([0]))[0] == 2
    np.testing.assert_array_equal(dofs.node_dofs("u", np.array([1]), 1), [2 + 4 + 3 + 3])


def test_dofmap_errors() -> None:
    dofs = DofMap()
    dofs.add_field("T", 3)
    dofs.add_extra("g", 1)
    for call in (
        lambda: dofs.add_field("T", 3),
        lambda: dofs.add_extra("T", 3),
        lambda: dofs.add_field("g", 3),
        lambda: dofs.add_field("x", 3, components=0),
        lambda: dofs.add_extra("h", -1),
        lambda: dofs.node_dofs("nope", np.array([0])),
        lambda: dofs.node_dofs("T", np.array([3])),
        lambda: dofs.node_dofs("T", np.array([-1])),
        lambda: dofs.node_dofs("T", np.array([0]), component=1),
        lambda: dofs.extra_dofs("nope"),
    ):
        with pytest.raises(ModelError):
            call()


# -------------------------------------------------------------------------- Assembler


def test_two_elements_by_hand() -> None:
    """Two bar elements 0-1 and 1-2 with stiffness 2 and 3."""
    asm = Assembler(3)
    conn = np.array([[0, 1], [1, 2]])
    unit = np.array([[1.0, -1.0], [-1.0, 1.0]])
    asm.add_matrix(conn, np.stack([2.0 * unit, 3.0 * unit]))
    asm.add_vector(conn, np.array([[10.0, 20.0], [30.0, 40.0]]))
    k = asm.matrix()
    assert issparse(k)
    assert k.format == "csr"
    assert k.has_canonical_format
    expected = np.array([[2.0, -2.0, 0.0], [-2.0, 5.0, -3.0], [0.0, -3.0, 3.0]])
    np.testing.assert_array_equal(k.toarray(), expected)
    assert k.nnz == 7  # duplicates were summed, structural zeros not stored
    f = asm.vector()
    assert isinstance(f, np.ndarray)
    np.testing.assert_array_equal(f, [10.0, 50.0, 40.0])


def test_batches_accumulate_and_reset() -> None:
    asm = Assembler(4)
    asm.add_matrix(np.array([[0, 1]]), np.array([[[1.0, 2.0], [3.0, 4.0]]]))
    asm.add_matrix(np.array([[1, 3, 2]]), np.arange(9.0).reshape(1, 3, 3))
    asm.add_vector(np.array([[3, 3]]), np.array([[1.0, 2.0]]))
    expected = np.zeros((4, 4))
    expected[np.ix_([0, 1], [0, 1])] += [[1.0, 2.0], [3.0, 4.0]]
    expected[np.ix_([1, 3, 2], [1, 3, 2])] += np.arange(9.0).reshape(3, 3)
    np.testing.assert_array_equal(asm.matrix().toarray(), expected)
    np.testing.assert_array_equal(asm.vector(), [0.0, 0.0, 0.0, 3.0])
    asm.reset()
    assert asm.matrix().nnz == 0
    assert asm.matrix().shape == (4, 4)
    np.testing.assert_array_equal(asm.vector(), np.zeros(4))


def test_rectangular_coupling_block_is_unsymmetric() -> None:
    asm = Assembler(5)
    rows = np.array([[0, 1]])
    cols = np.array([[2, 3, 4]])
    block = np.array([[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]])
    asm.add_matrix(rows, block, cols=cols)
    k = asm.matrix().toarray()
    np.testing.assert_array_equal(k[np.ix_([0, 1], [2, 3, 4])], block[0])
    assert np.count_nonzero(k) == 6


def test_assembler_errors() -> None:
    asm = Assembler(3)
    with pytest.raises(SolverError):
        asm.add_matrix(np.array([[0, 3]]), np.zeros((1, 2, 2)))
    with pytest.raises(SolverError):
        asm.add_matrix(np.array([[0, 1]]), np.zeros((1, 3, 3)))
    with pytest.raises(SolverError):
        asm.add_vector(np.array([[0, -1]]), np.zeros((1, 2)))
    with pytest.raises(SolverError):
        asm.add_vector(np.array([[0, 1]]), np.zeros((1, 3)))


@pytest.mark.parametrize("etype", ["T3", "Q4", "T6", "Q8"])
def test_assembled_conduction_matrix_through_dofmap(etype: str) -> None:
    """Global K from a mesh: symmetric, zero row sums, correct energy, shifted DOFs."""
    mesh = rect_mesh(0.0, 0.0, 2.0, 1.0, 3, 2, etype)
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    d = np.broadcast_to(3.0 * np.eye(mesh.dim), (*geom.dV.shape, mesh.dim, mesh.dim))
    ke = conduction(geom, d, gfactor(geom.xgp, False, 1.0, mesh.dim))

    dofs = DofMap()
    dofs.add_extra("before", 2)
    dofs.add_field("T", mesh.n_nodes)
    asm = Assembler(dofs.n_dofs)
    asm.add_matrix(dofs.node_dofs("T", block.conn), ke)
    k = asm.matrix()
    assert k.shape == (mesh.n_nodes + 2, mesh.n_nodes + 2)
    dense = k.toarray()
    np.testing.assert_array_equal(dense[:2], 0.0)
    np.testing.assert_array_equal(dense[:, :2], 0.0)
    np.testing.assert_allclose(dense, dense.T, atol=1e-13)
    np.testing.assert_allclose(dense.sum(axis=1), 0.0, atol=1e-12)
    u = np.zeros(dofs.n_dofs)
    u[dofs.field_dofs("T")] = 1.0 + 2.0 * mesh.nodes[:, 0] - 4.0 * mesh.nodes[:, 1]
    assert u @ k @ u == pytest.approx(3.0 * (2.0**2 + 4.0**2) * 2.0 * 1.0, rel=1e-12)
