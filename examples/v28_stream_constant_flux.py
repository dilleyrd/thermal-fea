"""V-28 — stream along a wall with a constant heat flux.

Thin wall strip with flux q on the outside and the stream inside. T_out = T_in + q A /
(m_dot c_p) (tolerance 1e-6); far from the inlet the wall runs q / h above the local fluid
temperature (tolerance 1e-2). ``c_p`` is taken at the inlet temperature, as in the stream
equations; the wall area is the wall length times the thickness (1 m).
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.materials import library
from thermalfea.model.bcs import HeatFlux, Stream

TOL_OUT = 1e-6
TOL_DT = 1e-2
LENGTH = 1.0  # m
HEIGHT = 0.002  # m
T_IN = 300.0  # K
Q = 5000.0  # W/m^2 on the outside
H = 500.0  # W/(m^2 K), constant override
RISE = 20.0  # K, temperature rise of the stream


def run(etype: str) -> dict:
    """Solve the heated strip with the stream along its bottom edge."""
    model, built = common.rectangle(
        "V-28 stream constant flux", etype, 0.0, 0.0, LENGTH, HEIGHT, 40, 1
    )
    model.bcs.append(HeatFlux("heating", "top", q=Q))
    cp = float(library.fluid("Water").props(T_IN).cp)
    mass_flow = Q * LENGTH / (RISE * cp)
    model.streams.append(
        Stream(
            name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
            wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN,
            mass_flow=mass_flow, path=[(0.0, 0.0), (LENGTH, 0.0)], h_override=H,
        )
    )
    case = common.solve(model, built)
    results = case.results

    fluid = np.asarray(results.fluid_temperature("coolant"), dtype=float)
    s = np.asarray(results.stream("coolant")["s"], dtype=float)
    exact_out = T_IN + Q * LENGTH / (mass_flow * cp)
    t_out = float(fluid[-1])

    nodes = case.nodes
    wall = np.flatnonzero((np.abs(nodes[:, 1]) < 1e-9) & (nodes[:, 0] > 0.6) & (nodes[:, 0] < 0.9))
    local_fluid = np.interp(nodes[wall, 0], s, fluid)
    dT = (case.T[wall] - local_fluid) - Q / H
    return {
        "error_out": abs(t_out - exact_out) / exact_out,
        "error_dT": float(np.max(np.abs(dT) / (Q / H))),
        "T_out": t_out,
        "imbalance": case.imbalance,
        "iterations": case.iterations,
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
