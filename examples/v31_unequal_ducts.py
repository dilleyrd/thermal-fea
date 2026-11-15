"""V-31 — two parallel ducts, one twice as long, turbulent.

Flows satisfy equal dp using the Churchill f; dp is evaluated for each branch from its
computed flow. Tolerance 1e-5.

This is a pure-function case: there is no model and no mesh.
"""

from __future__ import annotations

import math
import sys

from thermalfea.convection.correlations import friction_churchill, pressure_drop
from thermalfea.convection.fluid_props import fluid_props
from thermalfea.flow.network import solve_network
from thermalfea.materials import library
from thermalfea.model.bcs import FlowNetwork, NetBranch, NetNode, Stream

TOL = 1e-5
T_FLUID = 300.0  # K
DIAMETER, ROUGHNESS = 10e-3, 5e-5  # m
L_SHORT, L_LONG = 2.0, 4.0  # m
DP = 2.0e4  # Pa
P_OUT = 0.0


def run() -> dict[str, float]:
    """Branch pressure-drop errors, Reynolds numbers, flow ratio, mass conservation."""
    area = math.pi * DIAMETER**2 / 4.0
    stream = Stream(
        name="duct", fluid="Water", mode="through_plane", walls=[], flow_area=area,
        wetted_perimeter=math.pi * DIAMETER, cross_section="circular", T_inlet=T_FLUID,
        roughness=ROUGHNESS,
    )
    branches = [
        NetBranch("short", "in", "out", length=L_SHORT, stream="duct"),
        NetBranch("long", "in", "out", length=L_LONG, stream="duct"),
    ]
    props = fluid_props(library.fluid("Water"), T_FLUID)
    rho, mu = float(props.rho), float(props.mu)
    m, _ = solve_network(
        FlowNetwork([NetNode("in", pressure=P_OUT + DP), NetNode("out", pressure=P_OUT)],
                    branches),
        [stream], T_FLUID,
    )
    out: dict[str, float] = {}
    for key, br in (("short", branches[0]), ("long", branches[1])):
        V = m[br.id] / (rho * area)
        Re = rho * V * DIAMETER / mu
        f = friction_churchill(Re, ROUGHNESS / DIAMETER)
        dp = pressure_drop(f, br.length, DIAMETER, 0.0, rho, V)
        out[f"dp_error_{key}"] = abs(dp - DP) / DP
        out[f"Re_{key}"] = Re
    out["flow_ratio"] = m["short"] / m["long"]
    # the same pair driven by the total flow: the inlet junction must balance
    total = m["short"] + m["long"]
    md, _ = solve_network(
        FlowNetwork([NetNode("in", inflow=total), NetNode("out", pressure=P_OUT)], branches),
        [stream], T_FLUID,
    )
    out["mass_conservation"] = abs(md["short"] + md["long"] - total)
    return out


if __name__ == "__main__":
    sys.stdout.write(f"{__doc__.splitlines()[0]}\n")
    for key, value in run().items():
        sys.stdout.write(f"  {key:20s} = {value:.6g}\n")
