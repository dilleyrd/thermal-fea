"""M3.6 — radiation to ambient (Theory §5): residual, and tangent against finite differences."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state

from thermalfea.core.constants import STEFAN_BOLTZMANN as SIGMA
from thermalfea.core.functions import Expression, Table
from thermalfea.model.bcs import RadiationAmbient
from thermalfea.physics.radiation_ambient import RadiationAmbientTerm
from thermalfea.solver.terms import Term

W, H, X0 = 2.0, 1.0, 0.5


def problem_with(bc, etype: str, axisymmetric: bool = False, thickness: float = 0.25):
    return make_problem(etype, origin=(X0, 0.0), thickness=thickness,
                        axisymmetric=axisymmetric, distortion=0.15, bcs=(bc,))


def channels(problem, u):
    term = problem.terms[-1]
    asm = assemble(problem, make_state(problem, u), [term])
    return asm.residual(), asm.tangent(), asm


def test_sigma() -> None:
    assert SIGMA == pytest.approx(5.67e-8, rel=1e-4)


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_residual_of_a_uniform_temperature(etype: str, axisymmetric: bool) -> None:
    eps, t_inf, temp = 0.8, 300.0, 800.0
    problem = problem_with(RadiationAmbient("rad", "right", emissivity=eps, T_inf=t_inf),
                           etype, axisymmetric)
    term = problem.terms[-1]
    assert isinstance(term, RadiationAmbientTerm) and isinstance(term, Term)
    assert not term.is_linear and not term.is_time_dependent and term.symmetric
    assert not problem.is_linear
    r, k_rad, asm = channels(problem, temp)
    area = 2 * np.pi * (X0 + W) * H if axisymmetric else H * 0.25
    flux = eps * SIGMA * (temp**4 - t_inf**4)
    assert r.sum() == pytest.approx(-flux * area, rel=1e-13)  # heat leaves: negative residual
    assert term.boundary_heat(make_state(problem, temp)) == pytest.approx(-flux * area, rel=1e-13)
    assert k_rad.sum() == pytest.approx(4 * eps * SIGMA * temp**3 * area, rel=1e-13)
    assert abs(k_rad - k_rad.T).max() < 1e-12 * k_rad.max()
    # radiation is kept out of K and F (Theory §5)
    assert asm.matrix().nnz == 0 and not asm.vector().any()
    # only the nodes of that edge take part
    rows = np.unique(k_rad.nonzero()[0])
    np.testing.assert_allclose(problem.mesh.nodes[rows, 0], X0 + W)
    # equilibrium with the surroundings
    r0, _, _ = channels(problem, t_inf)
    np.testing.assert_allclose(r0, 0.0, atol=1e-9)


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_tangent_matches_finite_difference_of_the_residual(etype: str, axisymmetric: bool) -> None:
    """K_rad = -d r_rad / dT, to 1e-5 relative."""
    problem = problem_with(RadiationAmbient("rad", "top", emissivity=0.8, T_inf=300.0),
                           etype, axisymmetric)
    rng = np.random.default_rng(42)
    u = 600.0 + 300.0 * rng.random(problem.dofs.n_dofs)  # a non-uniform field, 600 .. 900 K
    _, k_rad, _ = channels(problem, u)
    k_rad = k_rad.toarray()

    step = 1e-3
    fd = np.zeros_like(k_rad)
    active = np.unique(k_rad.nonzero()[1])
    for j in active:  # loop over the DOFs of one edge (test only)
        up, down = u.copy(), u.copy()
        up[j] += step
        down[j] -= step
        fd[:, j] = -(channels(problem, up)[0] - channels(problem, down)[0]) / (2 * step)
    assert np.abs(fd - k_rad).max() <= 1e-5 * np.abs(k_rad).max()
    # and the residual does not depend on any other DOF
    others = np.setdiff1d(np.arange(u.size), active)
    bumped = u.copy()
    bumped[others] += 50.0
    np.testing.assert_array_equal(channels(problem, bumped)[0], channels(problem, u)[0])


def test_tangent_predicts_the_change_of_the_residual() -> None:
    problem = problem_with(RadiationAmbient("rad", "left", emissivity=0.5, T_inf=250.0), "Q8")
    u = 500.0 + 100.0 * problem.mesh.nodes[:, 1]
    r, k_rad, _ = channels(problem, u)
    du = 1e-4 * np.sin(7.0 * problem.mesh.nodes[:, 1])
    r_new, _, _ = channels(problem, u + du)
    np.testing.assert_allclose(r_new - r, -k_rad @ du, rtol=1e-5, atol=1e-12)


def test_functions_of_time_and_temperature() -> None:
    bc = RadiationAmbient("rad", "bottom", emissivity=Expression("0.5 + T/2000"),
                          T_inf=Table([0.0, 10.0], [300.0, 400.0], "t"))
    problem = problem_with(bc, "Q4", thickness=1.0)
    term = problem.terms[-1]
    assert term.is_time_dependent and term.breakpoints() == [0.0, 10.0]
    s = make_state(problem, 1000.0, t=5.0)  # eps = 1.0, T_inf = 350
    expected = -1.0 * SIGMA * (1000.0**4 - 350.0**4) * W
    assert term.boundary_heat(s) == pytest.approx(expected, rel=1e-13)
    asm = assemble(problem, s, [term])
    assert asm.residual().sum() == pytest.approx(expected, rel=1e-13)
    # modified Newton: the emissivity's own temperature derivative is left out of the tangent
    assert asm.tangent().sum() == pytest.approx(4 * 1.0 * SIGMA * 1000.0**3 * W, rel=1e-13)


def test_heat_enters_when_surroundings_are_hotter() -> None:
    problem = problem_with(RadiationAmbient("rad", "top", emissivity=1.0, T_inf=1000.0), "T6")
    assert problem.terms[-1].boundary_heat(make_state(problem, 300.0)) > 0.0
    r, _, _ = channels(problem, 300.0)
    assert r.sum() > 0.0
