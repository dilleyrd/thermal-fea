"""M3.9 — recovery of gradient and flux (Theory §7)."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, make_problem

from thermalfea.core.functions import Expression
from thermalfea.materials.material import Material
from thermalfea.model.bcs import FixedTemperature
from thermalfea.post.recovery import element_flux, element_gradient, gradient, nodal_flux
from thermalfea.solver.problem import RegionData
from thermalfea.solver.steady import solve_steady

GRAD = np.array([120.0, -75.0])


def linear_field(problem) -> np.ndarray:
    return 300.0 + problem.mesh.nodes @ GRAD


@pytest.mark.parametrize("etype", TYPES)
def test_linear_field_is_recovered_exactly(etype: str) -> None:
    problem = make_problem(etype, k=50.0, distortion=0.2)
    mesh = problem.mesh
    u = linear_field(problem)
    flux = nodal_flux(mesh, problem, u)
    assert list(flux) == [1]
    nodes, q = flux[1]
    np.testing.assert_array_equal(nodes, np.arange(mesh.n_nodes))
    assert q.shape == (mesh.n_nodes, mesh.dim)
    np.testing.assert_allclose(q, np.broadcast_to(-50.0 * GRAD, q.shape), rtol=1e-10)
    _, g = gradient(mesh, problem, u)[1]
    np.testing.assert_allclose(g, np.broadcast_to(GRAD, g.shape), rtol=1e-10)
    qe = element_flux(mesh, problem, u)
    assert qe.shape == (mesh.n_elements, mesh.dim)
    np.testing.assert_allclose(qe, np.broadcast_to(-50.0 * GRAD, qe.shape), rtol=1e-10)
    np.testing.assert_allclose(
        element_gradient(mesh, problem, u), np.broadcast_to(GRAD, qe.shape), rtol=1e-10
    )


@pytest.mark.parametrize("etype", ["T6", "Q8"])
def test_quadratic_field_gradient_is_exact_at_the_nodes(etype: str) -> None:
    """Quadratic elements represent T = x^2 + 3xy - 2y^2 exactly, so B T_e is exact."""
    problem = make_problem(etype, k=2.0)
    mesh = problem.mesh
    x, y = mesh.nodes.T
    u = x**2 + 3 * x * y - 2 * y**2
    _, g = gradient(mesh, problem, u)[1]
    exact = np.column_stack([2 * x + 3 * y, 3 * x - 4 * y])
    np.testing.assert_allclose(g, exact, atol=1e-11)
    _, q = nodal_flux(mesh, problem, u)[1]
    np.testing.assert_allclose(q, -2.0 * exact, atol=1e-11)


@pytest.mark.parametrize("etype", ["T3", "Q4"])
def test_linear_elements_average_the_element_values(etype: str) -> None:
    problem = make_problem(etype, k=1.0, cells=(8, 4))
    mesh = problem.mesh
    x, y = mesh.nodes.T
    u = x**2  # dT/dx = 2x: piecewise constant in x within each linear element
    _, g = gradient(mesh, problem, u)[1]
    # a fully interior node has as many elements on its left as on its right, so the
    # plain average of their (piecewise constant) gradients is the central difference
    interior = (x > 1e-9) & (x < 2.0 - 1e-9) & (y > 1e-9) & (y < 1.0 - 1e-9)
    assert interior.sum() == 7 * 3
    np.testing.assert_allclose(g[interior, 0], 2 * x[interior], atol=1e-11)
    left = np.isclose(x, 0.0)
    np.testing.assert_allclose(g[left, 0], 0.25, atol=1e-11)  # one-sided at the boundary
    np.testing.assert_allclose(g[:, 1], 0.0, atol=1e-11)
    centroids = mesh.element_centroids()
    np.testing.assert_allclose(
        element_gradient(mesh, problem, u)[:, 0], 2 * centroids[:, 0], atol=0.26
    )


@pytest.mark.parametrize("etype", TYPES)
def test_interface_node_has_one_flux_value_per_region(etype: str) -> None:
    """V-11: two layers in series, k1 = 50 and k2 = 5; the flux is the same in both."""
    length = 0.1
    problem = make_problem(etype, size=(length, length / 10), cells=(20, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    mesh = problem.mesh
    block = mesh.blocks[0]
    right_half = mesh.nodes[block.conn].mean(axis=1)[:, 0] > length / 2
    block.region[right_half] = 2
    problem.regions[2] = RegionData(Material("poor", 5.0, 1.0, 1.0))
    problem.cache.clear()
    for term in problem.terms:
        term.setup(problem)

    u = solve_steady(problem)
    q_exact = 100.0 / (0.05 / 50.0 + 0.05 / 5.0)
    t_interface = 400.0 - q_exact * 0.05 / 50.0
    x = mesh.nodes[:, 0]
    on_interface = np.flatnonzero(np.isclose(x, length / 2))
    np.testing.assert_allclose(u[on_interface], t_interface, rtol=1e-10)

    flux = nodal_flux(mesh, problem, u)
    assert sorted(flux) == [1, 2]
    for region in (1, 2):
        nodes, q = flux[region]
        np.testing.assert_allclose(q[:, 0], q_exact, rtol=1e-10)
        np.testing.assert_allclose(q[:, 1], 0.0, atol=1e-8 * q_exact)
        assert set(on_interface) <= set(nodes)  # interface nodes are in both regions
    shared = set(flux[1][0]) & set(flux[2][0])
    assert shared == set(on_interface)
    # the gradient, unlike the flux, jumps by the conductivity ratio at the interface
    g1 = dict(zip(*gradient(mesh, problem, u)[1], strict=True))
    g2 = dict(zip(*gradient(mesh, problem, u)[2], strict=True))
    for node in on_interface:
        assert g2[node][0] == pytest.approx(10.0 * g1[node][0], rel=1e-9)
    np.testing.assert_allclose(element_flux(mesh, problem, u)[:, 0], q_exact, rtol=1e-10)


def test_orthotropic_flux_is_minus_d_grad() -> None:
    k1, k2, theta = 50.0, 5.0, np.radians(30.0)
    problem = make_problem("Q8", k=k1, k2=k2, angle=theta, distortion=0.15)
    u = linear_field(problem)
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, -s], [s, c]])
    expected = -(rotation @ np.diag([k1, k2]) @ rotation.T) @ GRAD
    _, q = nodal_flux(problem.mesh, problem, u)[1]
    np.testing.assert_allclose(q, np.broadcast_to(expected, q.shape), rtol=1e-10)
    # the flux is not parallel to the gradient
    assert abs(expected[0] * GRAD[1] - expected[1] * GRAD[0]) > 1.0


def test_flux_uses_conductivity_at_the_local_temperature() -> None:
    problem = make_problem("Q4", k=Expression("T/10"), cells=(4, 1))
    mesh = problem.mesh
    u = 300.0 + 50.0 * mesh.nodes[:, 0]  # 300 .. 400 K, gradient (50, 0)
    _, q = nodal_flux(mesh, problem, u)[1]
    np.testing.assert_allclose(q[:, 0], -(u / 10.0) * 50.0, rtol=1e-12)
    centroids = mesh.element_centroids()
    np.testing.assert_allclose(
        element_flux(mesh, problem, u)[:, 0], -(30.0 + 5.0 * centroids[:, 0]) * 50.0, rtol=1e-12
    )


def test_axisymmetric_recovery_is_the_same_cartesian_gradient() -> None:
    problem = make_problem("T6", origin=(0.5, 0.0), axisymmetric=True, k=3.0)
    u = linear_field(problem)
    _, q = nodal_flux(problem.mesh, problem, u)[1]
    np.testing.assert_allclose(q, np.broadcast_to(-3.0 * GRAD, q.shape), rtol=1e-10)
