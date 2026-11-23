"""Tutorial 3 (``guide/tutorials/cold-plate.md``): an aluminium cold plate cooled by water.

A strip of 2024-T6 aluminum, 200 mm long and 10 mm thick, 50 mm deep, carries a uniform
heat flux of 20 kW/m^2 on its top edge (components mounted on it: 200 W in all). Water at
300 K flows along the bottom edge in a flat channel 50 mm wide and 2 mm high, at 0.02 kg/s;
the stream model supplies the heat-transfer coefficient (internal duct correlation) and the
water temperature along the wall. The other two edges are insulated. Steady.

``run()`` returns the numbers the page quotes, including the what-if with other mass flows;
``make_figures`` writes the pictures and ``save_model`` the model of the page::

    .venv\\Scripts\\python.exe examples\\tutorial_cold_plate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import common
import numpy as np
import tutorial_common as tc

from thermalfea import api
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.materials import library
from thermalfea.model.bcs import Adiabatic, HeatFlux, Stream
from thermalfea.model.model import Model
from thermalfea.post import flow, plots

NAME = "cold-plate"
LENGTH, THICKNESS, DEPTH = 0.20, 0.01, 0.05  # m: plate length (x), thickness (y), depth
MATERIAL = "Aluminum, Alloy 2024-T6"
FLUX = 20000.0  # W/m^2 on the top edge
GAP = 0.002  # m, channel height; the channel is as wide as the plate is deep
FLUID, CROSS_SECTION = "Water", "parallel_plates_one_side"
T_INLET = 300.0  # K
MASS_FLOW = 0.02  # kg/s (about 1.2 l/min)
WHAT_IF = (0.005, 0.1)  # kg/s
MESH_SIZE = 0.005  # m
STREAM = "Stream 1"
#: Laminar Nusselt number of Theory §8.1, parallel plates with one side insulated, constant wall T.
NU_LAMINAR = 4.86


def flow_area() -> float:
    """Flow cross-section of the channel [m^2]."""
    return DEPTH * GAP


def wetted_perimeter() -> float:
    """Wetted perimeter of the channel [m]."""
    return 2.0 * (DEPTH + GAP)


def build(mass_flow: float = MASS_FLOW) -> tuple[Model, BuiltGeometry]:
    """The model of the page, geometry built, ready to mesh."""
    model = api.new_model("planar", name="Cold plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, THICKNESS)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, LENGTH, THICKNESS)
    api.select_curves(
        model, built, "ends",
        tags=[*model.selections["left"].tags, *model.selections["right"].tags],
    )
    api.assign_region(model, "all", material=MATERIAL, thickness=DEPTH)
    model.bcs += [
        HeatFlux("Heat Flux 1", "top", q=FLUX),
        Adiabatic("Adiabatic 1", "ends"),
    ]
    model.streams.append(
        Stream(
            name=STREAM, fluid=FLUID, mode="in_plane", walls=["bottom"],
            flow_area=flow_area(), wetted_perimeter=wetted_perimeter(),
            cross_section=CROSS_SECTION, T_inlet=T_INLET, mass_flow=mass_flow,
            path=[(0.0, 0.0), (LENGTH, 0.0)],
        )
    )
    model.mesh_settings.global_size = MESH_SIZE
    return model, built


def hand_check() -> dict:
    """The hand calculation of the page, with water properties at the inlet temperature.

    ``D_h = 4 A / P_wet``, ``Re = m D_h / (A mu)``, ``h = Nu k / D_h`` with the laminar
    ``Nu`` of the duct table, the heat load as flux times area, and the outlet temperature
    from ``Q = m c_p (T_out - T_in)`` with ``c_p`` at the inlet temperature, and the wall
    temperature above the water as heat flux over ``h`` (the bottom edge carries the same
    flux density as the top edge).
    """
    props = library.fluid(FLUID).props(T_INLET)
    area, perimeter = flow_area(), wetted_perimeter()
    d_h = 4.0 * area / perimeter
    heat = FLUX * LENGTH * DEPTH
    cp = float(props.cp)
    reynolds = MASS_FLOW * d_h / (area * float(props.mu))
    velocity = MASS_FLOW / (float(props.rho) * area)
    return {
        "D_h": d_h,
        "Re": reynolds,
        "h": NU_LAMINAR * float(props.k) / d_h,
        "heat": heat,
        "cp": cp,
        "T_out": T_INLET + heat / (MASS_FLOW * cp),
        "superheat": FLUX / (NU_LAMINAR * float(props.k) / d_h),
        "velocity": velocity,
        "dp": (64.0 / reynolds) * (LENGTH / d_h) * float(props.rho) * velocity**2 / 2.0,
        "k": float(props.k),
        "mu": float(props.mu),
        "rho": float(props.rho),
    }


def solve_case(mass_flow: float) -> dict:
    """Solve the model for one mass flow and return the stream and plate numbers."""
    model, built = build(mass_flow)
    case = common.solve(model, built)
    (summary,) = flow.stream_summary(case.results)
    s_wall, T_wall = flow.wall_temperature(case.results, STREAM)
    s_fluid = case.results.stream(STREAM)["s"]
    T_fluid = case.results.fluid_temperature(STREAM)
    middle = 0.5 * LENGTH
    superheat = float(np.interp(middle, s_wall, T_wall) - np.interp(middle, s_fluid, T_fluid))
    return {
        "mass_flow": summary.mass_flow,
        "Re": summary.Re,
        "regime": summary.regime,
        "h_mean": summary.h_mean,
        "dp": summary.dp,
        "T_in": summary.T_in,
        "T_out": summary.T_out,
        "heat": summary.heat,
        "superheat_mid": superheat,
        "T_max": float(case.T.max()),
        "T_min": float(case.T.min()),
        "heat_in": case.heat("Heat Flux 1"),
        "heat_stream": case.heat(STREAM),
        "imbalance": abs(case.imbalance),
        "iterations": case.iterations,
        "n_cells": len(case.results.fluid_temperature(STREAM)) - 1,
        "model": model,
        "case": case,
    }


def run() -> dict:
    """Solve the page's model (0.02 kg/s) and the what-if cases.

    Returns
    -------
    dict
        The entries of :func:`solve_case` for the main case, plus ``hand``
        (:func:`hand_check`), ``dT_hand`` (outlet minus inlet temperature from the heat
        balance by hand [K]), ``dT`` (the program's) and ``what_if``: one :func:`solve_case`
        dict per mass flow of :data:`WHAT_IF`.
    """
    main = solve_case(MASS_FLOW)
    hand = hand_check()
    main["hand"] = hand
    main["dT_hand"] = hand["T_out"] - T_INLET
    main["dT"] = main["T_out"] - main["T_in"]
    main["what_if"] = [solve_case(m) for m in WHAT_IF]
    return main


def make_figures(folder: Path | None = None, result: dict | None = None) -> list[Path]:
    """Write the pictures of the page into ``folder`` (default ``guide/tutorials/img``)."""
    folder = folder if folder is not None else tc.IMAGES
    result = result if result is not None else run()
    results = result["case"].results
    figures = {
        "cold-plate-contour.png": plots.contour(results, show_mesh=False, levels=14),
        "cold-plate-stream.png": flow.plot_stream(results, STREAM),
    }
    return [tc.save_figure(fig, folder / name) for name, fig in figures.items()]


def save_model(result: dict | None = None, folder: Path | None = None) -> Path:
    """Save the model of the page as ``cold-plate.tfea``."""
    model = result["model"] if result is not None else build()[0]
    return tc.save_model(model, NAME, folder)


if __name__ == "__main__":
    out = sys.stdout.write
    answer = run()
    for row in (answer, *answer["what_if"]):
        out(
            f"m = {row['mass_flow']:<6} Re = {row['Re']:.0f} ({row['regime']}), "
            f"h = {row['h_mean']:.1f}, dp = {row['dp']:.1f} Pa, T_out = {row['T_out']:.3f} K, "
            f"T_max = {row['T_max']:.2f} K\n"
        )
    for path in [*make_figures(result=answer), save_model(answer)]:
        out(f"wrote {path}\n")
