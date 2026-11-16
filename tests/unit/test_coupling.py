"""M7.4 — streams and network coupled to the solid through the flow-provider interface."""

from __future__ import annotations

import h5py
import numpy as np
import pytest
from handmade import make_problem, make_state

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression
from thermalfea.flow.coupling import HYDRAULICS_DT, StreamNetworkProvider, provider_of
from thermalfea.flow.network import solve_network
from thermalfea.flow.provider import FlowProvider
from thermalfea.flow.stream import StreamTerm
from thermalfea.materials import library
from thermalfea.model.bcs import (
    FixedTemperature,
    FlowNetwork,
    HeatFlux,
    NetBranch,
    NetNode,
    Stream,
)
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.energy import energy_balance
from thermalfea.solver.compile import attach_stream
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.steady import assemble, steady_solution
from thermalfea.solver.transient import initial_state

LENGTH, T_IN = 1.0, 300.0
CP_IN = float(library.fluid("Water").props(T_IN).cp)


def stream(**changes) -> Stream:
    base = dict(
        name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN, mass_flow=0.25,
        path=[(0.0, 0.0), (LENGTH, 0.0)],
    )
    return Stream(**{**base, **changes})


def network(dp: float = 300.0, **branch) -> FlowNetwork:
    return FlowNetwork(
        nodes=[NetNode("in", pressure=dp), NetNode("out", pressure=0.0)],
        branches=[NetBranch("duct", "in", "out", length=LENGTH, stream="coolant", **branch)],
    )


def coupled(streams, net=None, bcs=(), cells=(20, 2)):
    problem = make_problem("Q4", size=(LENGTH, 0.1), cells=cells, bcs=bcs)
    provider = StreamNetworkProvider(streams, net)
    problem.providers.append(provider)
    provider.setup(problem)
    return problem, provider


# ------------------------------------------------------------------------- interface


def test_provider_implements_the_interface() -> None:
    problem, provider = coupled([stream()])
    assert isinstance(provider, FlowProvider)
    (term,) = provider.terms()
    assert isinstance(term, StreamTerm) and problem.terms[-1] is term
    assert provider.term("coolant") is term
    with pytest.raises(ModelError, match="unknown stream"):
        provider.term("other")
    # the inlet constraint came with it
    assert problem.constraints[-1].name == "coolant: inlet"


def test_attach_stream_shares_one_provider() -> None:
    problem = make_problem("Q4", size=(LENGTH, 0.1), cells=(10, 2))
    attach_stream(problem, stream())
    attach_stream(problem, stream(name="second", walls=["top"], path=[(0.0, 0.1), (LENGTH, 0.1)]))
    assert len(problem.providers) == 1
    assert provider_of(problem) is problem.providers[0]
    assert [t.name for t in problem.providers[0].terms()] == ["coolant", "second"]
    with pytest.raises(ModelError, match="two streams"):
        attach_stream(problem, stream())


def test_the_drivers_update_the_provider_before_assembling() -> None:
    problem = make_problem("Q4", bcs=(FixedTemperature("w", "left", T=300.0),))
    calls = []

    class Spy:
        def update(self, s) -> None:
            calls.append((s.t, s.u.copy()))

        def results(self, s) -> dict:
            return {}

    problem.providers.append(Spy())
    assemble(problem, np.full(problem.dofs.n_dofs, 310.0), t=2.0)
    assert len(calls) == 1 and calls[0][0] == 2.0 and calls[0][1][0] == 310.0


# ------------------------------------------------------------------------ hydraulics


def test_network_feeds_the_stream() -> None:
    st = stream(mass_flow=None)
    problem, provider = coupled([st], network(), bcs=(FixedTemperature("w", "top", T=340.0),))
    term = provider.term("coolant")
    assert not term.is_linear and not problem.is_linear
    result = steady_solution(problem)
    assert result.converged
    flow = term.mass_flow(0.0)
    mean = float(np.mean(result.T[term.fluid_dofs]))
    # the flow is that of the network at a branch temperature within 1 K of the final one
    lo, _ = solve_network(network(), [st], mean - HYDRAULICS_DT)
    hi, _ = solve_network(network(), [st], mean + HYDRAULICS_DT)
    assert min(lo["duct"], hi["duct"]) <= flow <= max(lo["duct"], hi["duct"])
    assert provider.solution is not None and provider.solution.mass_flow["duct"] == flow
    # the balance closes with the enthalpy term of the stream
    balance = energy_balance(problem, result.T, system=result.system)
    fluid = result.T[term.fluid_dofs]
    assert balance.flows["coolant"] == pytest.approx(flow * CP_IN * (fluid[0] - fluid[-1]))
    assert abs(balance.relative_imbalance) < 1e-6


def test_hydraulics_are_solved_again_only_after_one_kelvin() -> None:
    problem, provider = coupled([stream(mass_flow=None)], network())
    term = provider.term("coolant")

    def state(fluid_T: float):
        s = make_state(problem, 320.0)
        s.u[term.fluid_dofs] = fluid_T
        return s

    provider.update(state(300.0))
    first = term.mass_flow(0.0)
    assert provider.hydraulic_solves == 1
    provider.update(state(300.0 + 0.9 * HYDRAULICS_DT))
    assert provider.hydraulic_solves == 1 and term.mass_flow(0.0) == first
    provider.update(state(300.0 + 1.5 * HYDRAULICS_DT))
    assert provider.hydraulic_solves == 2 and term.mass_flow(0.0) != first
    # the reference is the temperature of the last solve, not of the last call
    provider.update(state(300.0 + 0.8 * HYDRAULICS_DT))
    assert provider.hydraulic_solves == 2
    # an unusable trial state keeps the flows
    provider.update(state(float("nan")))
    assert provider.hydraulic_solves == 2


def test_without_a_network_update_does_nothing() -> None:
    problem, provider = coupled([stream()])
    provider.update(make_state(problem, 320.0))
    assert provider.hydraulic_solves == 0 and provider.solution is None


def test_network_errors() -> None:
    # a stream may lend its area to a duct and to a loss, but not to two ducts
    two = network()
    two.branches.append(NetBranch("entry", "in", "out", kind="loss", K_minor=1.0,
                                  stream="coolant"))
    _, provider = coupled([stream(mass_flow=None)], two)
    assert provider._branch_of == {"coolant": "duct"}
    two.branches.append(NetBranch("again", "in", "out", length=1.0, stream="coolant"))
    with pytest.raises(ModelError, match="one duct branch only"):
        coupled([stream(mass_flow=None)], two)
    with pytest.raises(ModelError, match="unknown stream"):
        coupled([stream(name="other", mass_flow=None)], network())
    # flow against the path
    backwards = FlowNetwork(
        nodes=[NetNode("in", pressure=0.0), NetNode("out", pressure=300.0)],
        branches=[NetBranch("duct", "in", "out", length=LENGTH, stream="coolant")],
    )
    problem, provider = coupled([stream(mass_flow=None)], backwards)
    with pytest.raises(ModelError, match="against the direction"):
        provider.update(make_state(problem, 320.0))


def test_through_plane_stream_on_a_network() -> None:
    st = stream(mode="through_plane", path=None, mass_flow=None, walls=["right"])
    problem, provider = coupled([st], network(), bcs=(FixedTemperature("w", "left", T=350.0),))
    result = steady_solution(problem)
    expected, _ = solve_network(network(), [st], T_IN)
    assert provider.term("coolant").mass_flow(0.0) == pytest.approx(expected["duct"], rel=1e-12)
    numbers = provider.results(make_state(problem, result.T))
    assert "T_fluid:coolant" not in numbers
    assert numbers["mass_flow:coolant"][0] == pytest.approx(expected["duct"])
    assert numbers["dp:coolant"][0] == pytest.approx(300.0)
    assert numbers["heat:coolant"][0] > 0.0  # the hot wall heats the stream
    assert provider.static() == {"coolant": {"mode": "through_plane"}}


# --------------------------------------------------------------------------- results


def test_results_of_an_in_plane_stream() -> None:
    q, h, m = 5000.0, 500.0, 0.06
    problem, provider = coupled(
        [stream(mass_flow=m, h_override=h)], bcs=(HeatFlux("heating", "top", q=q),)
    )
    result = steady_solution(problem)
    term = provider.term("coolant")
    out = provider.results(make_state(problem, result.T))
    np.testing.assert_array_equal(out["T_fluid:coolant"], result.T[term.fluid_dofs])
    assert out["mass_flow:coolant"][0] == m
    assert out["h_mean:coolant"][0] == pytest.approx(h)
    assert out["T_in:coolant"][0] == T_IN
    assert out["T_out:coolant"][0] == pytest.approx(T_IN + q * LENGTH / (m * CP_IN), rel=1e-9)
    assert out["heat:coolant"][0] == pytest.approx(q * LENGTH, rel=1e-9)
    assert out["Re:coolant"][0] > 0.0 and out["dp:coolant"][0] > 0.0
    static = provider.static()["coolant"]
    assert static["mode"] == "in_plane"
    np.testing.assert_array_equal(static["s"], term.node_s)
    np.testing.assert_array_equal(static["dofs"], term.fluid_dofs)


def test_initial_fluid_state_satisfies_the_fluid_equations() -> None:
    problem, provider = coupled([stream(mass_flow=0.05, h_override=400.0)])
    problem.settings = SolutionSettings(kind="transient")
    term = provider.term("coolant")
    T, _ = initial_state(problem, 350.0, 0.0)
    fluid = T[term.fluid_dofs]
    assert fluid[0] == T_IN and np.all(np.diff(fluid) > 0.0) and fluid[-1] < 350.0
    s = make_state(problem, T)
    residual = term.matrix(s) @ T
    np.testing.assert_allclose(residual[term.fluid_dofs[1:]], 0.0, atol=1e-9)


# ------------------------------------------------------------------- through the API


def cold_plate(**stream_changes):
    model = api.new_model(name="cold plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(HeatFlux("load", "hot", q=2000.0))
    model.streams.append(stream(walls=["channel"], **stream_changes))
    return model, built, api.mesh(model, built)


def test_fluid_results_in_the_file() -> None:
    model, built, mesh = cold_plate(h_override=800.0, mass_flow=0.05)
    problem = compile_problem(model, built, mesh)
    assert len(problem.providers) == 1 and isinstance(problem.providers[0], FlowProvider)
    results = api.solve(model, mesh, built=built)
    assert results.streams == ["coolant"]
    data = results.stream("coolant")
    term = problem.terms[-1]
    assert data["mode"] == "in_plane"
    np.testing.assert_allclose(data["s"], term.node_s)
    np.testing.assert_array_equal(data["dofs"], term.fluid_dofs)
    for key in ("mass_flow", "h_mean", "Re", "dp", "T_in", "T_out", "heat"):
        assert data[key].shape == (1,) and np.isfinite(data[key][0]), key
    assert data["mass_flow"][0] == 0.05 and data["h_mean"][0] == pytest.approx(800.0)
    fluid = results.fluid_temperature("coolant")
    assert fluid.shape == (term.n_cells + 1,) and fluid[0] == T_IN
    assert fluid[-1] == pytest.approx(data["T_out"][0])
    assert data["heat"][0] == pytest.approx(2000.0 * LENGTH, rel=1e-9)
    assert "T_fluid:coolant" in results.fields
    with h5py.File(results.path, "r") as f:
        assert f["steps/fields/T_fluid:coolant"].attrs["location"] == "extra:coolant"
        assert f["steps/fields/T_fluid:coolant"].attrs["units"] == "K"
        assert f["fluid/0"].attrs["name"] == "coolant"
    with pytest.raises(ModelError, match="no results stored for stream"):
        results.stream("other")


def test_through_plane_stream_in_the_file() -> None:
    model, built, mesh = cold_plate(mode="through_plane", path=None, mass_flow=0.05)
    results = api.solve(model, mesh, built=built)
    data = results.stream("coolant")
    assert data["mode"] == "through_plane" and "s" not in data
    assert data["h_mean"][0] > 0.0 and data["T_out"][0] == T_IN
    with pytest.raises(ModelError, match="through-plane"):
        results.fluid_temperature("coolant")


@pytest.mark.parametrize("theta", [1.0, 0.5])
@pytest.mark.parametrize("given_h", [True, False])
def test_transient_with_a_time_varying_flow_rate_conserves_energy(
    theta: float, given_h: bool
) -> None:
    flow = Expression("0.02 + 0.002*t")
    changes = {"h_override": 800.0} if given_h else {}
    model, built, mesh = cold_plate(mass_flow=flow, **changes)
    model.initial_condition = InitialCondition("uniform", value=Constant(320.0))
    model.solution = SolutionSettings(
        kind="transient", end_time=20.0, initial_dt=1.0, auto_timestep=False, theta=theta
    )
    results = api.solve(model, mesh, built=built)
    assert results.n_steps == 21 and bool(np.all(results.converged))
    data = results.stream("coolant")
    np.testing.assert_allclose(data["mass_flow"], 0.02 + 0.002 * results.times)
    # the initial state is stored with its fluid temperatures
    assert results.fluid_temperature("coolant", 0)[0] == T_IN
    assert np.all(np.isfinite(results.fluid_temperature("coolant", 0)))
    assert np.all(data["T_out"] > T_IN) and np.all(data["T_out"] < results.temperature().max())
    if given_h:  # with a fixed h the outlet cools as the flow rises
        assert data["T_out"][-1] < data["T_out"][1]
    imbalance = results.energy_balance()["relative_imbalance"][1:]
    assert np.abs(imbalance).max() < (1e-8 if given_h else 1e-5)
    # the stream's flow in the balance is its enthalpy term at the last step
    cp = float(library.fluid("Water").props(T_IN).cp)
    last = data["mass_flow"][-1] * cp * (data["T_in"][-1] - data["T_out"][-1])
    if theta == 1.0:
        assert results.heat_flow("coolant")[-1] == pytest.approx(last, rel=1e-9)
