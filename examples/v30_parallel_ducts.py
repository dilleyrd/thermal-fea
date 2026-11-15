"""V-30 — two identical parallel ducts.

Equal split; total flow matches the single-duct law. Laminar single duct:
dp = 32 mu L V / D^2. Tolerance 1e-5.

This is a pure-function case: there is no model and no mesh.
"""

from __future__ import annotations

import sys

from thermalfea.convection.fluid_props import fluid_props
from thermalfea.flow.network import solve_network
from thermalfea.materials import library
from thermalfea.model.bcs import FlowNetwork, NetBranch, NetNode, Stream

TOL = 1e-5
T_FLUID = 300.0  # K
DIAMETER, LENGTH = 5e-3, 1.0  # m
DP = 30.0  # Pa; keeps the Reynolds number laminar (about 160)
P_OUT = 0.0


def _stream() -> Stream:
    area = 3.141592653589793 * DIAMETER**2 / 4.0
    return Stream(
        name="duct", fluid="Water", mode="through_plane", walls=[], flow_area=area,
        wetted_perimeter=3.141592653589793 * DIAMETER, cross_section="circular",
        T_inlet=T_FLUID, roughness=0.0,
    )


def run() -> dict[str, float]:
    """Errors of the split, the total flow and the laminar law; Re; mass conservation."""
    stream = _stream()
    nodes = [NetNode("in", pressure=P_OUT + DP), NetNode("out", pressure=P_OUT)]
    two = FlowNetwork(
        nodes=nodes,
        branches=[
            NetBranch("a", "in", "out", length=LENGTH, stream="duct"),
            NetBranch("b", "in", "out", length=LENGTH, stream="duct"),
        ],
    )
    one = FlowNetwork(nodes=nodes, branches=[NetBranch("a", "in", "out", length=LENGTH,
                                                       stream="duct")])
    m2, _ = solve_network(two, [stream], T_FLUID)
    m1, _ = solve_network(one, [stream], T_FLUID)
    props = fluid_props(library.fluid("Water"), T_FLUID)
    rho, mu = float(props.rho), float(props.mu)
    V = m1["a"] / (rho * stream.flow_area)
    dp_law = 32.0 * mu * LENGTH * V / DIAMETER**2
    # the same pair driven by the total flow instead: the junction must balance
    total = m2["a"] + m2["b"]
    driven = FlowNetwork(nodes=[NetNode("in", inflow=total), NetNode("out", pressure=P_OUT)],
                         branches=two.branches)
    md, _ = solve_network(driven, [stream], T_FLUID)
    return {
        "split_error": abs(m2["a"] - m2["b"]) / abs(m2["a"]),
        "total_error": abs(m2["a"] + m2["b"] - 2.0 * m1["a"]) / (2.0 * m1["a"]),
        "laminar_error": abs(DP - dp_law) / DP,
        "Re": rho * V * DIAMETER / mu,
        "mass_conservation": abs(md["a"] + md["b"] - total),
    }


if __name__ == "__main__":
    sys.stdout.write(f"{__doc__.splitlines()[0]}\n")
    for key, value in run().items():
        sys.stdout.write(f"  {key:20s} = {value:.6g}\n")
