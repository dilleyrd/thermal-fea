"""Tutorial 1 (``guide/tutorials/t4-plate.md``): the NAFEMS T4 plate on four mesh sizes.

The model is the one of V-10 (``examples/v10_nafems_t4.py``); this script adds what the
page quotes: the answer at four mesh sizes with linear triangles (the default mesh of the
program), the answer with quadratic triangles, the heat flow through the plate, and the
pictures. Run it as a script to write the pictures into ``guide/tutorials/img`` and the
model into ``guide/tutorials/models``::

    .venv\\Scripts\\python.exe examples\\tutorial_t4_plate.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import tutorial_common as tc
import v10_nafems_t4 as v10
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from thermalfea.model.model import Model
from thermalfea.post import plots

#: Element sizes of the convergence table [m]; the third is the one of the walkthrough.
SIZES = (0.1, 0.05, 0.025, 0.0125)
#: The size the page builds in the GUI, and the one drawn and saved.
GUI_SIZE = 0.025
ZERO_C = v10.ZERO_C
NAME = "t4-plate"


def run(sizes: tuple[float, ...] = SIZES) -> dict:
    """Solve the plate on each size with linear triangles, and once with quadratic ones.

    Parameters
    ----------
    sizes : tuple of float
        Global element sizes [m].

    Returns
    -------
    dict
        ``table``: one dict per size (``size``, ``nodes``, ``elements``, ``T_K``, ``T_degC``,
        ``error_degC``, ``heat_base`` [W], ``imbalance``); ``table6``: the same with quadratic
        triangles (``size``, ``nodes``, ``T_degC``, ``imbalance``), ``T6_degC`` and ``T6_nodes``
        at :data:`GUI_SIZE`; ``case`` and ``T_degC``, ``T_K``,
        ``error_degC``, ``heat_base``, ``heat_cooling``, ``imbalance`` of the case at
        :data:`GUI_SIZE`; ``target_degC`` and ``tol_degC`` of the benchmark.
    """
    table = []
    for size in sizes:
        result = v10.run("T3", size)
        case = result["case"]
        table.append(
            {
                "size": size,
                "nodes": int(case.mesh.n_nodes),
                "elements": int(sum(len(b.conn) for b in case.mesh.blocks)),
                "T_K": result["T_degC"] + ZERO_C,
                "T_degC": result["T_degC"],
                "error_degC": result["error_degC"],
                "heat_base": case.heat("base"),
                "imbalance": result["imbalance"],
                "case": case,
            }
        )
    main = next(row for row in table if row["size"] == GUI_SIZE)
    table6 = []
    for size in sizes:
        quadratic = v10.run("T6", size)
        table6.append(
            {
                "size": size,
                "nodes": int(quadratic["case"].mesh.n_nodes),
                "T_degC": quadratic["T_degC"],
                "imbalance": quadratic["imbalance"],
            }
        )
    at_gui_size = next(row for row in table6 if row["size"] == GUI_SIZE)
    return {
        "table": table,
        "table6": table6,
        "T6_degC": at_gui_size["T_degC"],
        "T6_nodes": at_gui_size["nodes"],
        "T_degC": main["T_degC"],
        "T_K": main["T_K"],
        "error_degC": main["error_degC"],
        "heat_base": main["heat_base"],
        "heat_cooling": main["case"].heat("cooling"),
        "imbalance": main["imbalance"],
        "target_degC": v10.TARGET_C,
        "tol_degC": v10.TOL_C,
        "case": main["case"],
    }


def convergence_figure(result: dict) -> Figure:
    """Temperature at the benchmark point against element size, with the target band."""
    fig = Figure(figsize=(7.5, 4.5), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)
    sizes = [row["size"] for row in result["table"]]
    ax.axhspan(
        result["target_degC"] - result["tol_degC"], result["target_degC"] + result["tol_degC"],
        color="0.88", label=f"benchmark {result['target_degC']} +/- {result['tol_degC']}",
    )
    ax.plot(sizes, [row["T_degC"] for row in result["table"]], "o-", label="linear triangles")
    ax.plot(
        sizes, [row["T_degC"] for row in result["table6"]], "s--", label="quadratic triangles"
    )
    ax.set_xscale("log")
    ax.invert_xaxis()
    ax.set_xticks(sizes, [f"{size:g}" for size in sizes])
    ax.minorticks_off()
    ax.set_xlabel("Global element size [m]")
    ax.set_ylabel("Temperature at (0.6, 0.2) [degC]")
    ax.set_title("NAFEMS T4: convergence with mesh size")
    ax.grid(True)
    ax.legend(loc="lower right")
    return fig


def make_figures(folder: Path | None = None) -> list[Path]:
    """Write the pictures of the page into ``folder`` (default ``guide/tutorials/img``)."""
    folder = folder if folder is not None else tc.IMAGES
    result = run()
    case = result["case"]
    coarse = next(row for row in result["table"] if row["size"] == 0.1)["case"]
    edge = [(v10.W, 0.0), (v10.W, v10.HGT)]
    figures = {
        "t4-contour.png": plots.contour(case.results, smooth=True, levels=14),
        "t4-mesh.png": plots.contour(coarse.results, show_mesh=True),
        "t4-right-edge.png": plots.path(case.results, edge, field="T"),
        "t4-convergence.png": convergence_figure(result),
    }
    return [tc.save_figure(fig, folder / name) for name, fig in figures.items()]


def gui_named_model() -> Model:
    """The model of the page (mesh size 0.025) with the load names the GUI gives."""
    model = copy.deepcopy(v10.run("T3", GUI_SIZE)["case"].model)
    names = {"base": "Fixed Temperature 1", "cooling": "Convection 1", "insulated": "Adiabatic 1"}
    for bc in model.bcs:
        bc.name = names[bc.name]
    return model


def save_model(folder: Path | None = None) -> Path:
    """Save the model of the page as ``t4-plate.tfea``."""
    return tc.save_model(gui_named_model(), NAME, folder)


if __name__ == "__main__":
    out = sys.stdout.write
    answer = run()
    for row in answer["table"]:
        out(
            f"size {row['size']:<7} nodes {row['nodes']:>5} elements {row['elements']:>5} "
            f"T = {row['T_degC']:.4f} degC  heat in at the base = {row['heat_base']:.2f} W\n"
        )
    out(f"quadratic triangles at {GUI_SIZE}: T = {answer['T6_degC']:.4f} degC\n")
    for path in [*make_figures(), save_model()]:
        out(f"wrote {path}\n")
