"""V-29 — energy conservation with a stream.

Any model: sum of the boundary heat flows + m c_p (T_in - T_out) = 0, to 1e-8 relative.

A plate 0.4 m by 0.02 m with heat generation, a fixed temperature on the left and
convection on the right is cooled by water streams along its long sides. Two variants:

* ``given``: one stream along the bottom with a prescribed mass flow and the duct
  correlation for h (a nonlinear problem);
* ``network``: streams along the bottom and the top in parallel between two pressure
  nodes; the network distributes the flow (the top branch has an extra loss).

The nonlinear tolerance is tightened so that the convergence error of the iteration lies
below the tolerance of the case. ``c_p`` is taken at the inlet temperature, as in the
stream equations.
"""

from __future__ import annotations

import common

from thermalfea.materials import library
from thermalfea.model.bcs import (
    Convection,
    FixedTemperature,
    FlowNetwork,
    HeatGeneration,
    NetBranch,
    NetNode,
    Stream,
)

TOL = 1e-8
LENGTH, HEIGHT = 0.4, 0.02  # m
T_IN = 290.0  # K
VARIANTS = ("given", "network")


def _stream(name: str, wall: str, y: float, mass_flow: float | None) -> Stream:
    return Stream(
        name=name, fluid="Water", mode="in_plane", walls=[wall], flow_area=5e-5,
        wetted_perimeter=0.03, cross_section="circular", T_inlet=T_IN, mass_flow=mass_flow,
        path=[(0.0, y), (LENGTH, y)],
    )


def run(etype: str, variant: str = "given") -> dict:
    model, built = common.rectangle(
        f"V-29 stream energy ({variant})", etype, 0.0, 0.0, LENGTH, HEIGHT, 40, 4
    )
    model.bcs.append(HeatGeneration("heating", "all", Q=4.0e5))
    model.bcs.append(FixedTemperature("hot end", "left", T=340.0))
    model.bcs.append(Convection("air", "right", h=50.0, T_inf=300.0))
    if variant == "given":
        model.streams.append(_stream("lower", "bottom", 0.0, 0.02))
    else:
        model.streams.append(_stream("lower", "bottom", 0.0, None))
        model.streams.append(_stream("upper", "top", HEIGHT, None))
        model.network = FlowNetwork(
            nodes=[NetNode("in", pressure=400.0), NetNode("out", pressure=0.0)],
            branches=[
                NetBranch("lower duct", "in", "out", length=LENGTH, stream="lower"),
                NetBranch("upper duct", "in", "out", length=LENGTH, K_minor=4.0,
                          stream="upper"),
            ],
        )
    model.solution.rtol = 1e-10
    model.solution.ttol = 1e-8
    model.solution.max_iterations = 60
    case = common.solve(model, built)
    results = case.results

    cp = float(library.fluid("Water").props(T_IN).cp)
    streams = {name: results.stream(name) for name in results.streams}
    enthalpy = {
        name: float(d["mass_flow"][-1] * cp * (d["T_in"][-1] - d["T_out"][-1]))
        for name, d in streams.items()
    }
    boundary = {
        name: case.heat(name) for name in results.heat_flow_names if name not in streams
    }
    total = sum(boundary.values()) + sum(enthalpy.values())
    scale = max(abs(v) for v in (*boundary.values(), *enthalpy.values()))
    return {
        "error": abs(total) / scale,
        "boundary_heat": sum(boundary.values()),
        "stream_enthalpy": sum(enthalpy.values()),
        "mass_flow": sum(float(d["mass_flow"][-1]) for d in streams.values()),
        "T_out": max(float(d["T_out"][-1]) for d in streams.values()),
        "imbalance": case.imbalance,
        "iterations": case.iterations,
        "streams": streams,
        "case": case,
    }


if __name__ == "__main__":
    for name in VARIANTS:
        common.main(lambda etype, v=name: run(etype, v), f"{__doc__.splitlines()[0]} [{name}]")
