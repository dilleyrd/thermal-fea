"""Milestone M5 gate: every plot type for V-10 (steady) and V-17 (transient).

Writes PNG images, a GIF animation, CSV files and VTU files into a folder for a person to
look at::

    .venv\\Scripts\\python.exe examples\\m5_gallery.py [output-folder]

The default folder is ``examples/output/m5_gallery``. Nothing is shown on screen.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import common
import v10_nafems_t4 as v10
import v17_slab_convection as v17

from thermalfea import api
from thermalfea.core.units import UnitSettings
from thermalfea.model.bcs import Convection
from thermalfea.post import export, plots

log = logging.getLogger("thermalfea.examples.m5_gallery")
ETYPE = "Q8"


def v10_case() -> common.Case:
    """NAFEMS T4, shown in degrees Celsius."""
    case = v10.run(ETYPE, 0.025)["case"]
    case.results.model.display_units = UnitSettings(temperature="degC")
    return case


def v17_case() -> common.Case:
    """The convectively cooled slab of V-17 with every time step stored."""
    model, built = common.rectangle(
        "V-17 slab convection", ETYPE, 0.0, 0.0, v17.L, v17.L / 10, v17.N, 1
    )
    model.bcs.append(Convection("conv", "right", h=v17.H, T_inf=v17.T_INF))
    common.transient(model, v17.T_INIT, end_time=v17.L**2 / v17.ALPHA, output="all")
    return common.solve(model, built)


def steady_plots(case: common.Case, folder: Path) -> list[Path]:
    r = case.results
    edge = [(v10.W, 0.0), (v10.W, v10.HGT)]  # up the convecting right edge
    diagonal = [(0.0, 0.0), (v10.W, v10.HGT)]
    made = [
        ("v10_contour_T_banded.png", lambda p: plots.contour(r, field="T", path=p)),
        ("v10_contour_T_smooth_mesh.png",
         lambda p: plots.contour(r, field="T", smooth=True, show_mesh=True, path=p)),
        ("v10_contour_qmag.png", lambda p: plots.contour(r, field="qmag", levels=16, path=p)),
        ("v10_contour_qy.png", lambda p: plots.contour(r, field="qy", path=p)),
        ("v10_contour_gradmag.png", lambda p: plots.contour(r, field="gradmag", path=p)),
        ("v10_vectors.png", lambda p: plots.vectors(r, density=25, path=p)),
        ("v10_path_T_right_edge.png", lambda p: plots.path(r, edge, field="T", path=p)),
        ("v10_path_qmag_diagonal.png", lambda p: plots.path(r, diagonal, field="qmag", path=p)),
    ]
    return [_make(folder / name, draw) for name, draw in made]


def transient_plots(case: common.Case, folder: Path) -> list[Path]:
    r = case.results
    mid = v17.L / 20  # mid-height of the strip
    through = [(0.0, mid), (v17.L, mid)]
    half_way = r.n_steps // 4
    made = [
        ("v17_contour_T_early.png", lambda p: plots.contour(r, step=half_way, path=p)),
        ("v17_contour_T_end.png", lambda p: plots.contour(r, step=-1, show_mesh=True, path=p)),
        ("v17_contour_qx_end.png", lambda p: plots.contour(r, step=-1, field="qx", path=p)),
        ("v17_vectors_end.png", lambda p: plots.vectors(r, step=-1, density=20, path=p)),
        ("v17_history_centre_surface.png",
         lambda p: plots.history(r, points=[(0.0, mid), (v17.L / 2, mid), (v17.L, mid)], path=p)),
        ("v17_history_stat_surface_mean.png",
         lambda p: plots.history_stat(r, "right", stat="mean", path=p)),
        ("v17_history_stat_all_min.png",
         lambda p: plots.history_stat(r, "all", stat="min", path=p)),
        ("v17_heat_flow_history.png", lambda p: plots.heat_flow_history(r, path=p)),
        ("v17_path_T_through_thickness_early.png",
         lambda p: plots.path(r, through, step=half_way, field="T", path=p)),
        ("v17_path_T_through_thickness_end.png",
         lambda p: plots.path(r, through, step=-1, field="T", path=p)),
        ("v17_path_qx_through_thickness_end.png",
         lambda p: plots.path(r, through, step=-1, field="qx", path=p)),
    ]
    files = [_make(folder / name, draw) for name, draw in made]
    frames = list(range(0, r.n_steps, max(1, r.n_steps // 12)))
    files.append(export.animation(r, folder / "v17_animation_T.gif", steps=frames, fps=4, dpi=80))
    files.append(export.nodal_csv(r, folder / "v17_nodal.csv", steps=[0, -1]))
    probes = [(0.0, mid), (v17.L, mid)]
    files.append(export.history_csv(r, folder / "v17_history.csv", points=probes))
    files.append(export.vtu(r, folder / "v17_vtu", steps=[0, -1]))
    return files


def _make(path: Path, draw) -> Path:
    draw(path)
    return path


def main(folder: Path | None = None) -> list[Path]:
    """Produce the gallery and return the files written."""
    folder = Path(folder) if folder else Path(__file__).resolve().parent / "output" / "m5_gallery"
    folder.mkdir(parents=True, exist_ok=True)
    steady, moving = v10_case(), v17_case()
    files = steady_plots(steady, folder) + transient_plots(moving, folder)
    for name, case in (("v10_summary.txt", steady), ("v17_summary.txt", moving)):
        target = folder / name
        target.write_text(api.summary(case.results) + "\n", encoding="utf-8")
        files.append(target)
    for file in files:
        log.info("wrote %s", file)
    return files


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("thermalfea").setLevel(logging.WARNING)
    log.setLevel(logging.INFO)
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
