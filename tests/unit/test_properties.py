"""M3.5 — temperature-dependent properties and the orthotropic conductivity matrix."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.materials.material import Material
from thermalfea.physics.properties import (
    conductivity_matrix,
    density,
    specific_heat,
    volumetric_heat_capacity,
)

T = np.full((3, 4), 300.0)


def conduction_matrix(problem, u=300.0) -> np.ndarray:
    return assemble(problem, make_state(problem, u)).matrix().toarray()


# ------------------------------------------------------------------------------ D matrix


def test_isotropic() -> None:
    d = conductivity_matrix(Material("m", 50.0, 1.0, 1.0), 0.7, T, 2)
    assert d.shape == (3, 4, 2, 2)
    np.testing.assert_array_equal(d, np.broadcast_to(50.0 * np.eye(2), d.shape))
    d3 = conductivity_matrix(Material("m", 50.0, 1.0, 1.0), 0.0, T, 3)
    np.testing.assert_array_equal(d3, np.broadcast_to(50.0 * np.eye(3), (3, 4, 3, 3)))


def test_orthotropic_aligned_and_rotated() -> None:
    m = Material("o", 50.0, 1.0, 1.0, k2=5.0)
    np.testing.assert_allclose(conductivity_matrix(m, 0.0, T, 2)[0, 0], [[50.0, 0.0], [0.0, 5.0]])
    # V-12 matrix check: rotating by 90 degrees swaps the roles of k1 and k2
    np.testing.assert_allclose(
        conductivity_matrix(m, np.pi / 2, T, 2)[0, 0], [[5.0, 0.0], [0.0, 50.0]], atol=1e-14
    )
    swapped = Material("s", 5.0, 1.0, 1.0, k2=50.0)
    np.testing.assert_allclose(
        conductivity_matrix(m, np.pi / 2, T, 2), conductivity_matrix(swapped, 0.0, T, 2), atol=1e-14
    )
    # 180 degrees is the identity for a symmetric tensor
    np.testing.assert_allclose(
        conductivity_matrix(m, np.pi, T, 2), conductivity_matrix(m, 0.0, T, 2), atol=1e-13
    )


def test_orthotropic_at_30_degrees_matches_the_formula() -> None:
    k1, k2, theta = 50.0, 5.0, np.radians(30.0)
    d = conductivity_matrix(Material("o", k1, 1.0, 1.0, k2=k2), theta, T, 2)[1, 2]
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, -s], [s, c]])
    np.testing.assert_allclose(d, rotation @ np.diag([k1, k2]) @ rotation.T, rtol=1e-15)
    np.testing.assert_allclose(d, d.T, atol=1e-15)
    np.testing.assert_allclose(np.sort(np.linalg.eigvalsh(d)), [k2, k1], rtol=1e-13)
    # conductivity along the material axis is k1, across it k2
    axis, across = np.array([c, s]), np.array([-s, c])
    assert axis @ d @ axis == pytest.approx(k1)
    assert across @ d @ across == pytest.approx(k2)
    assert d[0, 1] == pytest.approx((k1 - k2) * s * c)


def test_temperature_dependence_at_each_point() -> None:
    temps = np.array([[300.0, 350.0], [400.0, 500.0]])
    m = Material("m", Table([300.0, 400.0], [10.0, 20.0], "T"), Expression("8000 - T"),
                 Expression("400 + 0.5*T"), k2=Expression("T/100"))
    d = conductivity_matrix(m, 0.0, temps, 2)
    np.testing.assert_allclose(d[..., 0, 0], [[10.0, 15.0], [20.0, 20.0]])  # table holds at 500
    np.testing.assert_allclose(d[..., 1, 1], [[3.0, 3.5], [4.0, 5.0]])
    np.testing.assert_array_equal(d[..., 0, 1], 0.0)
    np.testing.assert_allclose(density(m, temps), 8000.0 - temps)
    np.testing.assert_allclose(specific_heat(m, temps), 400.0 + 0.5 * temps)
    np.testing.assert_allclose(
        volumetric_heat_capacity(m, temps), (8000.0 - temps) * (400.0 + 0.5 * temps)
    )
    const = Material("c", 1.0, 7800.0, 500.0)
    np.testing.assert_array_equal(volumetric_heat_capacity(const, temps), 7800.0 * 500.0)
    assert density(const, temps).shape == temps.shape


def test_orthotropic_is_refused_in_3d() -> None:
    with pytest.raises(ModelError, match="two-dimensional"):
        conductivity_matrix(Material("o", 1.0, 1.0, 1.0, k2=2.0), 0.0, T, 3)


# -------------------------------------------------------------- through ConductionTerm


@pytest.mark.parametrize("etype", TYPES)
def test_rotating_the_material_by_90_degrees_swaps_k1_and_k2_in_the_matrix(etype: str) -> None:
    rotated = make_problem(etype, k=50.0, k2=5.0, angle=np.pi / 2, distortion=0.15)
    swapped = make_problem(etype, k=5.0, k2=50.0, angle=0.0, distortion=0.15)
    k_rot, k_swap = conduction_matrix(rotated), conduction_matrix(swapped)
    np.testing.assert_allclose(k_rot, k_swap, atol=1e-10 * np.abs(k_swap).max())
    aligned = conduction_matrix(make_problem(etype, k=50.0, k2=5.0, distortion=0.15))
    assert np.abs(aligned - k_rot).max() > 1.0  # the angle really matters


@pytest.mark.parametrize("etype", TYPES)
def test_orthotropic_energy_of_a_linear_field(etype: str) -> None:
    """u^T K u = integral of grad(T) . D grad(T) g dA for T = a x + b y."""
    k1, k2, theta, thickness = 50.0, 5.0, np.radians(30.0), 0.2
    problem = make_problem(etype, k=k1, k2=k2, angle=theta, thickness=thickness, distortion=0.15)
    assert problem.is_linear
    grad = np.array([3.0, -2.0])
    u = problem.mesh.nodes @ grad  # no offset: K annihilates constants only to round-off
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, -s], [s, c]])
    d = rotation @ np.diag([k1, k2]) @ rotation.T
    k = conduction_matrix(problem)
    assert u @ k @ u == pytest.approx(grad @ d @ grad * 2.0 * 1.0 * thickness, rel=1e-12)
    np.testing.assert_allclose(k, k.T, atol=1e-11)
    np.testing.assert_allclose(k.sum(axis=1), 0.0, atol=1e-10)


def test_orthotropic_temperature_dependent_material_is_nonlinear() -> None:
    problem = make_problem("Q8", k=50.0, k2=Expression("5 + T/100"), angle=0.0)
    assert not problem.is_linear
    y = problem.mesh.nodes[:, 1]
    u = 10.0 * y  # gradient across the material axis: only k2 matters
    cold = u @ conduction_matrix(problem, 300.0) @ u  # k2 = 8
    hot = u @ conduction_matrix(problem, 500.0) @ u  # k2 = 10
    assert cold == pytest.approx(8.0 * 100.0 * 2.0, rel=1e-12)
    assert hot == pytest.approx(10.0 * 100.0 * 2.0, rel=1e-12)
