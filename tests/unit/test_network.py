"""Flow-network hydraulics (Theory §9.2)."""

from __future__ import annotations

import math

import pytest

from thermalfea.convection.correlations import friction_churchill, pressure_drop
from thermalfea.convection.fluid_props import fluid_props
from thermalfea.core.errors import ConvergenceError, ModelError, SolverError
from thermalfea.flow import network as netmod
from thermalfea.flow.network import solve_network, solve_network_full
from thermalfea.materials import library
from thermalfea.model.bcs import FlowNetwork, NetBranch, NetNode, Stream

D = 0.01
AREA = math.pi * D**2 / 4.0
T = 300.0


def stream(name: str = "s", roughness: float = 0.0, fluid: str = "Water", d: float = D) -> Stream:
    return Stream(
        name=name, fluid=fluid, mode="through_plane", walls=[], flow_area=math.pi * d**2 / 4,
        wetted_perimeter=math.pi * d, cross_section="circular", T_inlet=T, roughness=roughness,
    )


def props(fluid: str = "Water", temp: float = T) -> tuple[float, float]:
    p = fluid_props(library.fluid(fluid), temp)
    return float(p.rho), float(p.mu)


def single(dp: float, length: float = 1.0, k: float = 0.0, kind: str = "duct") -> FlowNetwork:
    return FlowNetwork(
        [NetNode("a", pressure=dp), NetNode("b", pressure=0.0)],
        [NetBranch("x", "a", "b", kind=kind, length=length, K_minor=k, stream="s")],  # type: ignore[arg-type]
    )


def drop_of(m: float, length: float, k: float, rough: float) -> float:
    rho, mu = props()
    V = m / (rho * AREA)
    Re = rho * V * D / mu
    f = friction_churchill(Re, rough / D)
    return float(pressure_drop(f, length, D, k, rho, V))


def test_single_duct_laminar() -> None:
    dp = 20.0
    m, _ = solve_network(single(dp), {"s": stream()}, T)
    rho, mu = props()
    assert m["x"] * D / (AREA * mu) < 1000.0
    assert drop_of(m["x"], 1.0, 0.0, 0.0) == pytest.approx(dp, rel=1e-5)


def test_single_duct_turbulent_rough_with_minor_loss() -> None:
    dp = 3.0e4
    m, _ = solve_network(single(dp, length=3.0, k=2.5), {"s": stream(roughness=1e-4)}, T)
    rho, mu = props()
    assert m["x"] * D / (AREA * mu) > 4000.0
    assert drop_of(m["x"], 3.0, 2.5, 1e-4) == pytest.approx(dp, rel=1e-5)


def test_prescribed_inflow() -> None:
    mdot = 0.05
    net = FlowNetwork(
        [NetNode("a", inflow=mdot), NetNode("b", pressure=0.0)],
        [NetBranch("x", "a", "b", length=2.0, K_minor=1.0, stream="s")],
    )
    m, p = solve_network(net, {"s": stream(roughness=2e-5)}, T)
    assert m["x"] == pytest.approx(mdot, abs=1e-10)
    assert p["a"] == pytest.approx(drop_of(mdot, 2.0, 1.0, 2e-5), rel=1e-5)
    assert p["b"] == 0.0


def junction_network() -> FlowNetwork:
    nodes = [
        NetNode("in", pressure=5.0e4),
        NetNode("j1"),
        NetNode("j2", inflow=0.01),
        NetNode("out", pressure=0.0),
    ]
    br = [NetBranch("feed", "in", "j1", length=1.0, stream="s")]
    for i, length in enumerate((1.0, 2.0, 3.5)):
        br.append(NetBranch(f"p{i}", "j1", "j2", length=length, stream="s"))
    br.append(NetBranch("exit", "j2", "out", length=1.5, K_minor=1.0, stream="s"))
    return FlowNetwork(nodes, br)


def test_mass_conservation_at_every_node() -> None:
    net = junction_network()
    sol = solve_network_full(net, {"s": stream(roughness=1e-5)}, T)
    for n in net.nodes:
        net_out = 0.0
        for b in net.branches:
            if b.node_from == n.id:
                net_out += sol.mass_flow[b.id]
            if b.node_to == n.id:
                net_out -= sol.mass_flow[b.id]
        if n.inflow is not None or n.pressure is None:
            assert net_out == pytest.approx(n.inflow or 0.0, abs=1e-10)
    # the pressure nodes balance the whole network
    assert sol.mass_flow["feed"] - sol.mass_flow["exit"] == pytest.approx(-0.01, abs=1e-10)
    assert sol.mass_flow["p0"] > sol.mass_flow["p1"] > sol.mass_flow["p2"] > 0.0


def test_reverse_flow_changes_sign() -> None:
    fwd = FlowNetwork(
        [NetNode("a", pressure=2e4), NetNode("b", pressure=0.0)],
        [NetBranch("x", "a", "b", length=2.0, stream="s"),
         NetBranch("y", "a", "b", length=1.0, K_minor=3.0, stream="s")],
    )
    rev = FlowNetwork(
        [NetNode("a", pressure=0.0), NetNode("b", pressure=2e4)], fwd.branches
    )
    m1, _ = solve_network(fwd, {"s": stream(roughness=3e-5)}, T)
    m2, _ = solve_network(rev, {"s": stream(roughness=3e-5)}, T)
    for k in m1:
        assert m1[k] > 0.0
        assert m2[k] == pytest.approx(-m1[k], rel=1e-5)


def test_loss_branch() -> None:
    k, dp = 4.0, 5.0e3
    m, _ = solve_network(single(dp, k=k, kind="loss"), {"s": stream()}, T)
    rho, _ = props()
    assert m["x"] == pytest.approx(AREA * math.sqrt(2 * rho * dp / k), rel=1e-5)


def test_temperature_per_branch_and_input_forms() -> None:
    net = FlowNetwork(
        [NetNode("a", pressure=3.0), NetNode("b", pressure=0.0)],  # laminar at both temperatures
        [NetBranch("x", "a", "b", length=1.0, stream="s"),
         NetBranch("y", "a", "b", length=1.0, stream="s")],
    )
    s = stream()
    same, _ = solve_network(net, {"s": s}, 300.0)
    assert same["x"] == pytest.approx(same["y"], rel=1e-12)
    as_dict, _ = solve_network(net, {"s": s}, {"x": 300.0, "y": 300.0})
    as_list, _ = solve_network(net, [s], 300.0)
    assert as_dict == same
    assert as_list == same
    hot, _ = solve_network(net, {"s": s}, {"x": 300.0, "y": 360.0})
    assert hot["y"] > hot["x"]  # warmer water is less viscous
    (rho_x, mu_x), (rho_y, mu_y) = props(temp=300.0), props(temp=360.0)
    assert hot["y"] / hot["x"] == pytest.approx((rho_y / mu_y) / (rho_x / mu_x), rel=1e-3)


def test_return_types_and_iterations() -> None:
    net = junction_network()
    m, p = solve_network(net, {"s": stream()}, T)
    assert set(m) == {b.id for b in net.branches}
    assert set(p) == {n.id for n in net.nodes}
    sol = solve_network_full(net, {"s": stream()}, T)
    assert sol.converged
    assert 1 <= sol.iterations <= 200
    assert sol.mass_flow == m
    assert set(sol.friction) == set(sol.reynolds) == set(sol.pressure_drop) == set(m)
    assert sol.pressure_drop["feed"] == pytest.approx(p["in"] - p["j1"])


def bad(**kw: object) -> FlowNetwork:
    nodes = kw.pop("nodes", [NetNode("a", pressure=1.0), NetNode("b", pressure=0.0)])
    branches = kw.pop("branches", [NetBranch("x", "a", "b", length=1.0, stream="s")])
    return FlowNetwork(nodes, branches)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "net",
    [
        bad(branches=[NetBranch("x", "a", "b", length=1.0)]),
        bad(branches=[NetBranch("x", "a", "b", length=1.0, stream="nope")]),
        bad(branches=[NetBranch("x", "a", "zz", length=1.0, stream="s")]),
        bad(nodes=[NetNode("a", pressure=1.0, inflow=1.0), NetNode("b", pressure=0.0)]),
        bad(nodes=[NetNode("a", inflow=1.0), NetNode("b")]),
        bad(nodes=[NetNode("a", pressure=1.0), NetNode("a", pressure=0.0)]),
        bad(branches=[NetBranch("x", "a", "b", length=1.0, stream="s"),
                      NetBranch("x", "a", "b", length=1.0, stream="s")]),
        bad(branches=[NetBranch("x", "a", "b", length=0.0, stream="s")]),
        bad(branches=[NetBranch("x", "a", "b", kind="loss", K_minor=0.0, stream="s")]),
        FlowNetwork([], []),
    ],
)
def test_model_errors(net: FlowNetwork) -> None:
    with pytest.raises(ModelError):
        solve_network(net, {"s": stream()}, T)


def test_disconnected_node() -> None:
    net = bad(nodes=[NetNode("a", pressure=1.0), NetNode("b", pressure=0.0), NetNode("c")])
    with pytest.raises((SolverError, ModelError)):
        solve_network(net, {"s": stream()}, T)


def test_iteration_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netmod, "MAX_ITERATIONS", 1)
    with pytest.raises(ConvergenceError, match="relative change"):
        solve_network(single(3.0e4, length=3.0), {"s": stream(roughness=1e-4)}, T)


# ------------------------------------------------------------------- guards (M11.23)


def test_self_loop_is_refused() -> None:
    net = bad(branches=[NetBranch("x", "a", "a", length=1.0, stream="s")])
    with pytest.raises(ModelError, match="to itself"):
        solve_network(net, {"s": stream()}, T)


def test_duct_with_negative_minor_loss_is_refused() -> None:
    net = bad(branches=[NetBranch("x", "a", "b", length=1.0, K_minor=-0.5, stream="s")])
    with pytest.raises(ModelError, match="K_minor must not be negative"):
        solve_network(net, {"s": stream()}, T)


def test_negative_roughness_is_refused() -> None:
    with pytest.raises(ModelError, match="roughness"):
        solve_network(single(1.0e3), {"s": stream(roughness=-1e-5)}, T)


def test_network_problems_lists_every_problem_with_its_id() -> None:
    net = bad(
        nodes=[NetNode("a", pressure=1.0, inflow=2.0), NetNode("b"), NetNode("b")],
        branches=[
            NetBranch("x", "a", "a", length=1.0, stream="s"),
            NetBranch("y", "a", "zz", length=0.0, stream="nope"),
            NetBranch("z", "a", "b", kind="loss", K_minor=0.0),
        ],
    )
    found: dict[str, str] = {}
    for ident, message in netmod.network_problems(net.nodes, net.branches, [stream()]):
        found[ident] = found.get(ident, "") + message + "; "
    assert set(found) == {"a", "b", "x", "y", "z"}
    assert "both a pressure and an inflow" in found["a"]
    assert "duplicate node ids" in found["b"]
    assert "to itself" in found["x"]
    assert "unknown node" in found["y"] and "unknown stream" in found["y"]
    assert "no stream" in found["z"] and "positive K_minor" in found["z"]
    assert netmod.network_problems(single(1.0).nodes, single(1.0).branches, [stream()]) == []
    assert netmod.network_problems([], [], []) != []
    no_pressure = bad(nodes=[NetNode("a", inflow=1.0), NetNode("b")])
    assert any("prescribed pressure" in m for _, m in netmod.network_problems(
        no_pressure.nodes, no_pressure.branches, [stream()]))
