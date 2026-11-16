"""V-27 — stream along a wall at constant temperature.

Wall fixed at 350 K, length 1 m, water, T_in = 300 K, NTU = h A / (m_dot c_p) = 1 with a
constant h override. The exact outlet temperature is T_out = T_w - (T_w - T_in) exp(-NTU);
the tolerance is 1e-6 (the scheme is exact here), for 1 cell and for 20 cells. ``c_p`` is
taken at the inlet temperature, as in the stream equations.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.materials import library
from thermalfea.model.bcs import FixedTemperature, Stream

TOL = 1e-6
LENGTH = 1.0  # m; the wall area is LENGTH x thickness (thickness 1 m)
T_WALL = 350.0  # K
T_IN = 300.0  # K
H = 1000.0  # W/(m^2 K), constant override
CELLS = (1, 20)


def run(etype: str, n_cells: int = 20) -> dict:
    """Solve the stream along a fixed-temperature wall with ``n_cells`` stream cells."""
    model, built = common.rectangle(
        "V-27 stream constant wall", etype, 0.0, 0.0, LENGTH, 0.1, 20, 2
    )
    model.bcs.append(FixedTemperature("wall", "bottom", T=T_WALL))
    cp = float(library.fluid("Water").props(T_IN).cp)
    model.streams.append(
        Stream(
            name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
            wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN,
            mass_flow=H * LENGTH / cp, path=[(0.0, 0.0), (LENGTH, 0.0)], h_override=H,
            n_cells=n_cells,
        )
    )
    case = common.solve(model, built)
    results = case.results

    stream = results.stream("coolant")
    fluid = np.asarray(results.fluid_temperature("coolant"), dtype=float)
    s = np.asarray(stream["s"], dtype=float)
    exact_out = T_WALL - (T_WALL - T_IN) * np.exp(-1.0)
    t_out = float(fluid[-1])
    exact_profile = T_WALL - (T_WALL - T_IN) * np.exp(-s / LENGTH)
    return {
        "error": abs(t_out - exact_out) / exact_out,
        "T_out": t_out,
        "T_exact": float(exact_out),
        "profile_error": float(np.max(np.abs(fluid - exact_profile) / exact_profile)),
        "imbalance": case.imbalance,
        "iterations": case.iterations,
        "case": case,
    }


if __name__ == "__main__":
    for n in CELLS:
        common.main(lambda etype, n=n: run(etype, n), f"{__doc__.splitlines()[0]} [{n} cell(s)]")
