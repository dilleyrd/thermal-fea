"""M3.10 — reaction heat flows and the energy balance (Theory §4, §7)."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, make_problem

from thermalfea.core.constants import STEFAN_BOLTZMANN as SIGMA
from thermalfea.core.functions import Expression
from thermalfea.model.bcs import (
    Convection,
    FixedTemperature,
    HeatFlow,
    HeatFlux,
    HeatGeneration,
    HeatPower,
    RadiationAmbient,
)
from thermalfea.post.energy import EnergyBalance, energy_balance
from thermalfea.post.reactions import heat_flows, reaction_vector
from thermalfea.solver.steady import steady_solution

L, HGT = 0.1, 0.01  # the "1D" strip: length L, height L/10, thickness 1


def strip(etype: str, bcs, n: int = 10, **kw):
    return make_problem(etype, size=(L, HGT), cells=(n, 1), bcs=bcs, **kw)


def solved(problem):
    result = steady_solution(problem)
    return result, energy_balance(problem, result.T, system=result.system)


@pytest.mark.parametrize("etype", TYPES)
def test_slab_between_two_fixed_temperatures(etype: str) -> None:
    """V-01: the reactions carry k dT / L in at the hot face and out at the cold face."""
    problem = strip(etype, (FixedTemperature("hot", "left", T=400.0),
                            FixedTemperature("cold", "right", T=300.0)))
    result, balance = solved(problem)
    q = 50.0 * 100.0 / L * HGT
    assert balance.flows["hot"] == pytest.approx(q, rel=1e-10)
    assert balance.flows["cold"] == pytest.approx(-q, rel=1e-10)
    assert list(balance.flows) == ["hot", "cold"]
    assert abs(balance.relative_imbalance) < 1e-8
    assert balance.heat_in == pytest.approx(q) and balance.heat_out == pytest.approx(q)
    assert balance.throughput == pytest.approx(q) and balance.stored_rate == 0.0
    # reactions vanish at the free DOFs and sum to zero overall
    reaction = reaction_vector(result.system, result.T)
    idx, _ = problem.prescribed(0.0)
    free = np.setdiff1d(np.arange(reaction.size), idx)
    assert np.abs(reaction[free]).max() < 1e-9 * q
    assert abs(reaction.sum()) < 1e-9 * q


@pytest.mark.parametrize("etype", TYPES)
def test_convection_slab(etype: str) -> None:
    """V-02: heat flow = k (T0 - T(L)) / L, in at the fixed face, out by convection."""
    h, t0, t_inf, k = 100.0, 400.0, 300.0, 50.0
    problem = strip(etype, (FixedTemperature("hot", "left", T=t0),
                            Convection("conv", "right", h=h, T_inf=t_inf)))
    _, balance = solved(problem)
    t_end = t_inf + (t0 - t_inf) / (1.0 + h * L / k)
    q = k * (t0 - t_end) / L * HGT
    assert balance.flows["conv"] == pytest.approx(-q, rel=1e-10)
    assert balance.flows["hot"] == pytest.approx(q, rel=1e-10)
    assert abs(balance.relative_imbalance) < 1e-8


@pytest.mark.parametrize("etype", TYPES)
def test_generation_flux_and_power(etype: str) -> None:
    problem = strip(etype, (
        FixedTemperature("cold", "right", T=300.0),
        HeatFlux("flux", "left", q=5000.0),
        HeatGeneration("gen", "all", Q=1.0e6),
        HeatPower("power", "all", P=30.0),
        HeatFlow("flow", "top", P=-12.0),
    ))
    _, balance = solved(problem)
    expected = {"flux": 5000.0 * HGT, "gen": 1.0e6 * L * HGT, "power": 30.0, "flow": -12.0}
    for name, value in expected.items():
        assert balance.flows[name] == pytest.approx(value, rel=1e-12)
    assert balance.flows["cold"] == pytest.approx(-sum(expected.values()), rel=1e-9)
    assert abs(balance.relative_imbalance) < 1e-8
    assert list(balance.flows) == ["flux", "gen", "power", "flow", "cold"]


@pytest.mark.parametrize("etype", TYPES)
def test_nonlinear_radiation_balance(etype: str) -> None:
    problem = strip(etype, (
        FixedTemperature("hot", "left", T=1000.0),
        RadiationAmbient("rad", "right", emissivity=0.98, T_inf=300.0),
    ), k=55.6)
    result, balance = solved(problem)
    t_end = result.T[np.isclose(problem.mesh.nodes[:, 0], L)].mean()
    q = 0.98 * SIGMA * (t_end**4 - 300.0**4) * HGT
    assert balance.flows["rad"] == pytest.approx(-q, rel=1e-9)
    assert balance.flows["hot"] == pytest.approx(q, rel=1e-6)
    assert abs(balance.relative_imbalance) < 1e-3  # V-34 limit for nonlinear cases
    assert abs(balance.relative_imbalance) < 1e-6  # and in fact far better


@pytest.mark.parametrize("etype", TYPES)
def test_axisymmetric_cylinder_heat_flow(etype: str) -> None:
    """V-05: heat flow per height = 2 pi k (Ti - To) / ln(ro / ri)."""
    ri, ro, height = 0.05, 0.1, 0.02
    problem = make_problem(etype, origin=(ri, 0.0), size=(ro - ri, height), cells=(40, 1),
                           axisymmetric=True, bcs=(
                               FixedTemperature("inner", "left", T=400.0),
                               FixedTemperature("outer", "right", T=300.0)))
    _, balance = solved(problem)
    exact = 2 * np.pi * 50.0 * 100.0 / np.log(ro / ri) * height
    tol = 1e-3 if etype in ("T3", "Q4") else 1e-5
    assert balance.flows["inner"] == pytest.approx(exact, rel=tol)
    assert balance.flows["outer"] == pytest.approx(-exact, rel=tol)
    assert abs(balance.relative_imbalance) < 1e-8


def test_shared_node_is_counted_once() -> None:
    """Two fixed temperatures meeting at a corner: the corner reaction goes to the later."""
    problem = make_problem("Q4", cells=(4, 4), size=(1.0, 1.0), bcs=(
        FixedTemperature("bottom", "bottom", T=400.0),
        FixedTemperature("left", "left", T=400.0),
        Convection("conv", "right", h=20.0, T_inf=300.0),
    ))
    _, balance = solved(problem)
    assert abs(balance.relative_imbalance) < 1e-8
    assert balance.flows["bottom"] + balance.flows["left"] == pytest.approx(
        -balance.flows["conv"], rel=1e-9)
    assert balance.flows["bottom"] > 0 and balance.flows["left"] > 0


def test_temperature_dependent_loads_use_the_solution() -> None:
    problem = strip("Q8", (
        FixedTemperature("cold", "right", T=300.0),
        HeatGeneration("gen", "all", Q=Expression("1e5*(1 + (T - 300)/100)")),
        Convection("conv", "top", h=Expression("10 + 0.1*(T - 300)"), T_inf=300.0),
    ))
    result, balance = solved(problem)
    assert balance.flows["gen"] > 1e5 * L * HGT  # hotter than 300 K, so more than nominal
    assert balance.flows["conv"] < 0.0
    assert abs(balance.relative_imbalance) < 1e-6
    assert heat_flows(problem, result.T) == pytest.approx(balance.flows)  # assembles itself


def test_transient_terms_enter_the_balance() -> None:
    """With C dT/dt supplied, reactions and the stored-energy rate include it."""
    problem = strip("Q4", (FixedTemperature("hot", "left", T=400.0),))
    result = steady_solution(problem)  # uniform 400 K: nothing flows
    rate = np.full(problem.dofs.n_dofs, 2.5)  # pretend C dT/dt = 2.5 W at every DOF
    balance = energy_balance(problem, result.T, system=result.system, capacitance_rate=rate)
    assert balance.stored_rate == pytest.approx(2.5 * problem.dofs.n_dofs)
    n_fixed = problem.prescribed(0.0)[0].size
    assert balance.flows["hot"] == pytest.approx(2.5 * n_fixed, abs=1e-9)
    assert balance.imbalance == pytest.approx(2.5 * (n_fixed - problem.dofs.n_dofs), abs=1e-9)


def test_balance_object() -> None:
    balance = EnergyBalance({"in": 100.0, "out": -60.0, "leak": -39.0}, stored_rate=0.5)
    assert (balance.heat_in, balance.heat_out, balance.net) == (100.0, 99.0, 1.0)
    assert balance.throughput == 100.0
    assert balance.imbalance == pytest.approx(0.5)
    assert balance.relative_imbalance == pytest.approx(0.005)
    rows = balance.table()
    assert rows[:3] == [("in", 100.0), ("out", -60.0), ("leak", -39.0)]
    assert [name for name, _ in rows[3:]] == ["net heat in", "stored energy rate", "imbalance"]
    text = balance.format()
    assert "relative imbalance" in text and text.count("\n") == len(rows)
    assert all(line.rstrip().endswith("W") for line in text.splitlines()[:-1])
    empty = EnergyBalance()
    assert empty.relative_imbalance == 0.0 and empty.throughput == 0.0 and empty.net == 0
