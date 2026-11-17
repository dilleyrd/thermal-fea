"""Tutorial 2 (``guide/tutorials/fin-quench.md``): a hot aluminium fin cooling in still air.

A vertical plate of 6061-T6 aluminium (10 mm thick, 100 mm high, 100 mm deep) starts at
500 K in air at 300 K. Both faces lose heat by natural convection (the vertical-plate
correlation, air properties at the film temperature) and by radiation to the surroundings
(emissivity 0.8); the two ends are insulated. The run is transient with automatic time
steps, first to 3600 s and then continued to 7200 s (restart).

``run()`` returns the numbers the page quotes; ``make_figures`` writes its pictures and
``save_model`` the model of the page. As a script::

    .venv\\Scripts\\python.exe examples\\tutorial_fin_quench.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import common
import numpy as np
import tutorial_common as tc
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.core.constants import STEFAN_BOLTZMANN
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.materials import library
from thermalfea.model.bcs import Adiabatic, CorrelationConvection, RadiationAmbient
from thermalfea.model.model import Model
from thermalfea.post import plots

NAME = "fin-quench"
#: Names of the loads as the GUI gives them (the tree names a new load "<kind> <n>").
CONVECTION, RADIATION = "Correlation Convection 1", "Radiation to Ambient 1"
THICKNESS, HEIGHT, DEPTH = 0.01, 0.10, 0.10  # m: plate thickness (x), height (y), depth
MATERIAL = "Aluminium 6061-T6"
T_INIT, T_AMBIENT, EMISSIVITY = 500.0, 300.0, 0.8  # K, K, -
CORRELATION, FLUID = "vplate_natural", "Air"
MESH_SIZE = 0.005  # m
END_TIME, LATER_END_TIME = 3600.0, 7200.0  # s
INITIAL_DT = 1.0  # s; see the page: the suggested first step triggers a warning on this mesh
PROBE = (THICKNESS / 2.0, HEIGHT / 2.0)  # plate centre [m]


def build() -> tuple[Model, BuiltGeometry]:
    """The model of the page, geometry built, ready to mesh (transient, end time 3600 s)."""
    model = api.new_model("planar", name="Fin quench")
    api.Geometry(model).rectangle(0.0, 0.0, THICKNESS, HEIGHT)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, THICKNESS, HEIGHT)
    api.select_curves(
        model, built, "faces",
        tags=[*model.selections["left"].tags, *model.selections["right"].tags],
    )
    api.select_curves(
        model, built, "ends",
        tags=[*model.selections["top"].tags, *model.selections["bottom"].tags],
    )
    api.assign_region(model, "all", material=MATERIAL, thickness=DEPTH)
    model.bcs += [
        CorrelationConvection(
            CONVECTION, "faces", correlation=CORRELATION, fluid=FLUID,
            T_inf=T_AMBIENT, char_length=HEIGHT,
        ),
        RadiationAmbient(RADIATION, "faces", emissivity=EMISSIVITY, T_inf=T_AMBIENT),
        Adiabatic("Adiabatic 1", "ends"),
    ]
    model.mesh_settings.global_size = MESH_SIZE
    common.transient(model, T_INIT, end_time=END_TIME, initial_dt=INITIAL_DT)
    return model, built


def hand_check() -> dict:
    """The hand calculation of the page: h, Biot number, time constant and initial heat loss.

    Uses the HTC calculator for the convection coefficient at the initial surface
    temperature, the radiation heat flux of Theory §7 divided by the temperature
    difference for the equivalent radiation coefficient, and ``tau = rho c V / (h A)`` of
    V-16 with ``A / V = 2 / thickness`` (two faces, insulated ends).
    """
    result = api.htc(
        CORRELATION, FLUID, T_INIT, T_AMBIENT, length=HEIGHT
    )
    dT = T_INIT - T_AMBIENT
    h_rad = EMISSIVITY * STEFAN_BOLTZMANN * (T_INIT**4 - T_AMBIENT**4) / dT
    h_total = float(result.h) + h_rad
    material = library.solid(MATERIAL)
    k, rho, cp = (float(p.value) for p in (material.k, material.rho, material.cp))
    area = 2.0 * HEIGHT * DEPTH
    volume = THICKNESS * HEIGHT * DEPTH
    return {
        "h_conv": float(result.h),
        "Nu": float(result.Nu),
        "Ra": float(result.Ra),
        "Pr": float(result.Pr),
        "T_film": float(result.T_film),
        "regime": result.regime,
        "warnings": list(result.warnings),
        "h_rad": h_rad,
        "h_total": h_total,
        "k": k,
        "rho": rho,
        "cp": cp,
        "area": area,
        "volume": volume,
        "biot": h_total * (THICKNESS / 2.0) / k,
        "tau": rho * cp * volume / (h_total * area),
        "q_initial": h_total * area * dT,  # heat loss at the start [W]
    }


def _centre_node(mesh) -> int:
    """Index of the mesh node nearest the plate centre."""
    return int(plots.nearest_nodes(mesh, [PROBE])[0])


def _split(results, step: int) -> dict:
    """Heat lost by convection and by radiation at one step [W] and the radiation share."""
    conv = -float(results.heat_flow(CONVECTION)[step])
    rad = -float(results.heat_flow(RADIATION)[step])
    return {"conv": conv, "rad": rad, "rad_share": rad / (conv + rad)}


def _shares(results) -> np.ndarray:
    """Radiation share of the heat lost at every stored step (NaN at the initial state)."""
    conv = -np.asarray(results.heat_flow(CONVECTION), dtype=float)
    rad = -np.asarray(results.heat_flow(RADIATION), dtype=float)
    return rad / (conv + rad)


def run() -> dict:
    """Solve to 3600 s, then continue the same run to 7200 s.

    Returns
    -------
    dict
        ``hand`` (:func:`hand_check`), ``model`` (end time 3600 s), ``mesh``, ``node`` (the
        node nearest the plate centre), ``case`` (the 3600 s run, a :class:`common.Case`) and
        ``results`` (the file, now holding both stages); ``n_steps_3600``, ``n_steps_7200``,
        ``time_end``; ``T_end`` and ``T_later`` [K], the centre node at 3600 s and 7200 s;
        ``split_first``, ``split_end``, ``split_later``: heat lost by convection and by
        radiation [W] and the radiation share, at the first step after the start, at 3600 s
        and at 7200 s; ``t_first`` [s]; ``spread_first``, ``spread_end``: largest minus
        smallest node temperature [K]; ``T_at_tau``: centre temperature at the lumped time
        constant (interpolated between stored steps) and ``T_lumped_at_tau``: the constant-h
        exponential at that time; ``worst_imbalance_3600``, ``worst_imbalance``; the smallest
        radiation share ``share_min`` and its time ``t_share_min``; ``dt_min``, ``dt_max``:
        smallest and largest time step [s].
    """
    model, built = build()
    case = common.solve(model, built)
    first_stage = case.results
    node = _centre_node(case.mesh)
    n_steps_3600 = int(first_stage.n_steps)
    hand = hand_check()
    times = np.asarray(first_stage.times)
    centre = np.array([first_stage.temperature(i)[node] for i in range(len(times))])
    snapshot = {
        "T_end": float(centre[-1]),
        "spread_end": float(np.ptp(first_stage.temperature())),
        "split_end": _split(first_stage, -1),
    }
    t_first = float(times[1])
    t_at_tau = float(np.interp(hand["tau"], times, centre))
    lumped_at_tau = T_AMBIENT + (T_INIT - T_AMBIENT) * float(np.exp(-1.0))
    spread_first = float(np.ptp(first_stage.temperature(1)))
    split_first = _split(first_stage, 1)
    worst_3600 = case.worst_imbalance

    later = copy.deepcopy(model)
    later.solution.end_time = LATER_END_TIME
    results = api.solve(later, case.mesh, built=built, path=first_stage.path, restart=True)
    shares = _shares(results)
    balance = results.energy_balance()["relative_imbalance"]
    balance = balance[np.isfinite(balance)]
    steps = np.diff(np.asarray(results.times))
    return {
        "hand": hand,
        "model": model,
        "mesh": case.mesh,
        "node": node,
        "case": case,
        "results": results,
        "n_steps_3600": n_steps_3600,
        "n_steps_7200": int(results.n_steps),
        "t_first": t_first,
        "T_end": snapshot["T_end"],
        "spread_end": snapshot["spread_end"],
        "spread_first": spread_first,
        "split_first": split_first,
        "split_end": snapshot["split_end"],
        "T_later": float(results.temperature(-1)[node]),
        "split_later": _split(results, -1),
        "T_at_tau": t_at_tau,
        "T_lumped_at_tau": lumped_at_tau,
        "worst_imbalance_3600": worst_3600,
        "worst_imbalance": float(np.abs(balance).max()),
        "share_min": float(shares[1:].min()),
        "t_share_min": float(np.asarray(results.times)[1:][np.argmin(shares[1:])]),
        "dt_min": float(steps.min()),
        "dt_max": float(steps.max()),
        "time_end": float(results.times[-1]),
    }


def share_figure(results) -> Figure:
    """Share of the heat lost by radiation (the rest is convection) against time."""
    fig = Figure(figsize=(7.5, 4.5), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(np.asarray(results.times)[1:], 100.0 * _shares(results)[1:])
    ax.axhline(50.0, color="0.6", linestyle="--")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Share of the heat lost by radiation [%]")
    ax.set_title("Radiation and convection: who carries the heat")
    ax.grid(True)
    return fig


def make_figures(folder: Path | None = None, result: dict | None = None) -> list[Path]:
    """Write the pictures of the page into ``folder`` (default ``guide/tutorials/img``)."""
    folder = folder if folder is not None else tc.IMAGES
    result = result if result is not None else run()
    results = result["results"]
    figures = {
        "fin-history.png": plots.history(results, points=[PROBE]),
        "fin-heat-flows.png": plots.heat_flow_history(results),
        "fin-share.png": share_figure(results),
    }
    return [tc.save_figure(fig, folder / name) for name, fig in figures.items()]


def save_model(result: dict | None = None, folder: Path | None = None) -> Path:
    """Save the model of the page (end time 3600 s) as ``fin-quench.tfea``."""
    model = result["model"] if result is not None else build()[0]
    return tc.save_model(model, NAME, folder)


if __name__ == "__main__":
    out = sys.stdout.write
    answer = run()
    hand = answer["hand"]
    out(f"h_conv = {hand['h_conv']:.3f}, h_rad = {hand['h_rad']:.3f}, tau = {hand['tau']:.1f} s\n")
    out(f"T(3600 s) = {answer['T_end']:.3f} K, T(7200 s) = {answer['T_later']:.3f} K\n")
    for path in [*make_figures(result=answer), save_model(answer)]:
        out(f"wrote {path}\n")
