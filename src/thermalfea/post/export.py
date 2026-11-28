"""Export of results to files (M5.5): CSV tables, VTU series for ParaView, and animations.

Every temperature and flux written to a file is in SI units (K, W/m^2), whatever the model's
display units are. ``steps`` arguments take stored step indices (negative counts from the
end); ``None`` means every stored step.
"""

from __future__ import annotations

import csv
import logging
import math
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import matplotlib
import meshio
import numpy as np
from matplotlib.animation import FFMpegWriter
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from numpy import ndarray
from PIL import Image

from ..core.errors import ModelError
from ..core.registry import element
from . import plots
from .results import Results

log = logging.getLogger(__name__)

#: gmsh element-type code -> meshio cell-type name (part of meshio, not the gmsh package).
_GMSH_TO_MESHIO = meshio.gmsh.gmsh_to_meshio_type

_CSV_FORMATS = ["%d", "%.17g", "%d", "%.17g", "%.17g", "%.17g", "%.17g", "%.17g"]
_NODAL_HEADER = "step,time,node,x,y,T,qx,qy"


def _resolve_steps(results: Results, steps: Sequence[int] | None) -> list[int]:
    """Non-negative stored indices of the steps asked for; ``None`` means all of them."""
    n = results.n_steps
    if n == 0:
        raise ModelError("the results file has no steps")
    if steps is None:
        return list(range(n))
    picked = [int(s) for s in steps]
    if not picked:
        raise ModelError("no steps to export")
    for step in picked:
        if not -n <= step < n:
            raise ModelError(f"step {step} is out of range; the file has {n} step(s)")
    return [step % n for step in picked]


def _with_zero_z(vectors: ndarray) -> ndarray:
    """Append a zero z-component to an ``(n, 2)`` array, giving ``(n, 3)``."""
    return np.column_stack([vectors[:, :2], np.zeros(vectors.shape[0])])


def _write_table(path: Path, header: Sequence[str], data: ndarray, fmt: str | list[str]) -> None:
    """Write a header line and then the rows of ``data``, one ``savetxt`` call.

    The header fields are quoted by the :mod:`csv` module when they hold commas or quotes.
    """
    with path.open("w", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerow(header)
        np.savetxt(fh, data, fmt=fmt, delimiter=",")


# ------------------------------------------------------------------------------ nodal table


def nodal_csv(results: Results, path: str | Path, steps: Sequence[int] | None = None) -> Path:
    """Write the nodal temperature and heat flux of every node at every step to a CSV file.

    Parameters
    ----------
    results : Results
    path : str or Path
        File to write. Columns: ``step,time,node,x,y,T,qx,qy``; one row per node per step.
        Positions in m, time in s, temperature in K, flux in W/m^2 (the flux is merged over
        regions, averaged at interface nodes).
    steps : sequence of int, optional
        Stored steps to write; default all.

    Returns
    -------
    Path
        The file written.

    Raises
    ------
    ModelError
        If a step is out of range or no steps are given.
    """
    path = Path(path)
    indices = _resolve_steps(results, steps)
    times = np.asarray(results.times, dtype=float)
    mesh = results.mesh
    n = mesh.n_nodes
    node = np.arange(n, dtype=float)
    xy = mesh.nodes[:, :2]
    with path.open("w", encoding="utf-8") as fh:
        fh.write(_NODAL_HEADER + "\n")
        for step in indices:
            T = results.temperature(step)
            q = Results.node_values(results.flux(step), n)
            block = np.column_stack(
                [np.full(n, float(step)), np.full(n, times[step]), node, xy, T, q]
            )
            np.savetxt(fh, block, fmt=_CSV_FORMATS, delimiter=",")
    log.info("wrote nodal table of %d step(s) to %s", len(indices), path)
    return path


# ---------------------------------------------------------------------------- history table


def history_csv(
    results: Results,
    path: str | Path,
    nodes: Sequence[int] | None = None,
    points: Sequence[tuple[float, float]] | None = None,
    bc_names: Sequence[str] | None = None,
) -> Path:
    """Write the time histories of some nodes and of the boundary-condition heat flows.

    Parameters
    ----------
    results : Results
    path : str or Path
        File to write. The first column is ``time`` [s]; then one column ``T:node <index>``
        per requested node [K], then one column ``heat:<name>`` per boundary condition [W].
    nodes : sequence of int, optional
        Node indices.
    points : sequence of (x, y), optional
        Positions [m], each replaced by its nearest mesh node. Give at most one of
        ``nodes`` and ``points``; with neither, no temperature columns are written.
    bc_names : sequence of str, optional
        Boundary conditions whose heat flow is written; default all of
        ``results.heat_flow_names``. An empty sequence writes none.

    Returns
    -------
    Path
        The file written. NaN values (e.g. the heat flow of the initial state) are written
        as ``nan``.

    Raises
    ------
    ModelError
        If both ``nodes`` and ``points`` are given, a node or name is unknown, or a
        selection is empty.
    """
    path = Path(path)
    if results.n_steps == 0:
        raise ModelError("the results file has no steps")
    if nodes is not None and points is not None:
        raise ModelError("history_csv: give at most one of points= and nodes=")
    if points is not None:
        index = plots.nearest_nodes(results.mesh, points)
    elif nodes is not None:
        raw = np.asarray(nodes)
        if raw.size == 0 or not np.issubdtype(raw.dtype, np.integer):
            raise ModelError("nodes must be a non-empty sequence of node indices")
        index = raw.reshape(-1).astype(int)
    else:
        index = np.zeros(0, dtype=int)

    columns: list[ndarray] = [np.asarray(results.times, dtype=float)]
    header = ["time"]
    for node in index:
        columns.append(np.asarray(results.nodal_history(int(node)), dtype=float))
        header.append(f"T:node {int(node)}")
    names = results.heat_flow_names if bc_names is None else list(bc_names)
    for name in names:
        columns.append(np.asarray(results.heat_flow(name), dtype=float))
        header.append(f"heat:{name}")
    _write_table(path, header, np.column_stack(columns), "%.17g")
    log.info("wrote history table with %d column(s) to %s", len(columns), path)
    return path


# ---------------------------------------------------------------------------- series table


def series_csv(
    path: str | Path,
    x_name: str,
    x: ndarray,
    series: dict[str, ndarray],
) -> Path:
    """Write one abscissa column and named series columns, as plotted, to a CSV file.

    This writes numbers that were already gathered (for example by
    :func:`thermalfea.post.plots.history_data` or :func:`thermalfea.post.plots.path_data`)
    without converting them, so a chart's CSV holds exactly what the chart shows.

    Parameters
    ----------
    path : str or Path
        File to write; the first line is the header.
    x_name : str
        Header of the first column, e.g. ``"time [s]"``.
    x : ndarray, shape (n,)
        Abscissa values.
    series : dict of str to ndarray
        Header -> values, each of shape ``(n,)``. Commas in headers are replaced by
        semicolons. NaN is written as ``nan``.

    Returns
    -------
    Path
        The file written.

    Raises
    ------
    ModelError
        If a series does not have as many values as ``x``.
    """
    path = Path(path)
    abscissa = np.asarray(x, dtype=float).reshape(-1)
    columns = [abscissa]
    for label, values in series.items():
        column = np.asarray(values, dtype=float).reshape(-1)
        if column.size != abscissa.size:
            raise ModelError(f"series {label!r} has {column.size} values, expected {abscissa.size}")
        columns.append(column)
    header = [h.replace(",", ";") for h in [x_name, *series]]
    _write_table(path, header, np.column_stack(columns), "%.17g")
    log.info("wrote series table with %d column(s) to %s", len(columns), path)
    return path


# ------------------------------------------------------------------------------------- VTU


def _meshio_type(etype: str) -> str:
    """The meshio cell-type name of a registered element type."""
    return _GMSH_TO_MESHIO[element(etype).gmsh_type]


def vtu(
    results: Results,
    folder: str | Path,
    name: str = "results",
    steps: Sequence[int] | None = None,
) -> Path:
    """Write one VTU file per step and a ``.pvd`` index for ParaView.

    Parameters
    ----------
    results : Results
    folder : str or Path
        Created if missing. Files are ``<name>_<index:04d>.vtu`` (the stored step index).
    name : str
        Base name of the files and of the ``.pvd`` index.
    steps : sequence of int, optional
        Stored steps to write; default all.

    Returns
    -------
    Path
        The ``.pvd`` file. Point data: ``T`` [K] and ``q`` [W/m^2, z component zero] (the
        nodal flux merged over regions). Cell data: ``region`` and ``q_element`` [W/m^2].

    Raises
    ------
    ModelError
        If a step is out of range or no steps are given.
    """
    folder = Path(folder)
    indices = _resolve_steps(results, steps)
    times = np.asarray(results.times, dtype=float)
    folder.mkdir(parents=True, exist_ok=True)
    mesh = results.mesh
    n = mesh.n_nodes
    points = _with_zero_z(mesh.nodes)
    cells = [(_meshio_type(block.etype), np.asarray(block.conn)) for block in mesh.blocks]
    regions = [np.asarray(block.region, dtype=int) for block in mesh.blocks]

    entries: list[tuple[float, str]] = []
    for step in indices:
        q = _with_zero_z(Results.node_values(results.flux(step), n))
        element_flux = results.element_flux(step)
        cell_q = [_with_zero_z(element_flux[block.elem_ids]) for block in mesh.blocks]
        out = folder / f"{name}_{step:04d}.vtu"
        meshio.Mesh(
            points,
            cells,
            point_data={"T": np.asarray(results.temperature(step), dtype=float), "q": q},
            cell_data={"region": regions, "q_element": cell_q},
        ).write(out)
        entries.append((float(times[step]), out.name))

    pvd = folder / f"{name}.pvd"
    lines = ['<?xml version="1.0"?>', '<VTKFile type="Collection" version="0.1">', "  <Collection>"]
    for time, filename in entries:
        lines.append(f'    <DataSet timestep="{time!r}" part="0" file={quoteattr(filename)}/>')
    lines += ["  </Collection>", "</VTKFile>"]
    pvd.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %d VTU file(s) and %s", len(entries), pvd)
    return pvd


# ------------------------------------------------------------------------------- animation


def animation(
    results: Results,
    path: str | Path,
    field: str = "T",
    steps: Sequence[int] | None = None,
    fps: float = 5,
    dpi: float = 100,
    **contour_options: Any,
) -> Path:
    """Animate a contour plot over the stored steps, as a GIF or an MP4.

    The color range is fixed over all frames (the extrema of the chosen steps), unless
    ``vmin`` / ``vmax`` are given.

    Parameters
    ----------
    results : Results
    path : str or Path
        ``.gif`` (Pillow) or ``.mp4`` (needs ffmpeg on the PATH).
    field : str
        Contour field, see :func:`thermalfea.post.plots.contour`.
    steps : sequence of int, optional
        Stored steps; default all.
    fps : float
        Frames per second; must be positive.
    dpi : float
        Resolution of the frames.
    **contour_options
        Passed to :func:`thermalfea.post.plots.contour` (``levels``, ``vmin``, ``vmax``,
        ``smooth``, ``show_mesh``). ``ax`` and ``path`` are not accepted.

    Returns
    -------
    Path
        The file written.

    Raises
    ------
    ModelError
        For an unknown file type, a non-positive ``fps``, no steps, an unknown field or
        step, ``ax`` among the options, or an MP4 request without ffmpeg.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".gif", ".mp4"):
        raise ModelError(f"unsupported animation file {path.name!r}; use a .gif or .mp4 name")
    if not (math.isfinite(fps) and fps > 0):
        raise ModelError(f"fps must be a positive finite number, not {fps}")
    if "ax" in contour_options:
        raise ModelError("animation draws its own figures; do not pass ax=")
    indices = _resolve_steps(results, steps)
    ffmpeg = shutil.which("ffmpeg") if suffix == ".mp4" else None
    if suffix == ".mp4" and ffmpeg is None:
        raise ModelError("ffmpeg was not found on this machine; write a .gif instead")

    options = dict(contour_options)
    if options.get("vmin") is None or options.get("vmax") is None:
        ranges = [plots.contour_data(results, step, field) for step in indices]
        if options.get("vmin") is None:
            options["vmin"] = min(r.vmin for r in ranges)
        if options.get("vmax") is None:
            options["vmax"] = max(r.vmax for r in ranges)

    if suffix == ".gif":
        frames = []
        for step in indices:
            fig = plots.contour(results, step, field, **options)
            fig.set_dpi(dpi)
            fig.canvas.draw()
            frames.append(Image.fromarray(np.array(fig.canvas.buffer_rgba())))
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=int(1000 / fps),
            loop=0,
        )
    else:
        fig = Figure(figsize=(7.5, 5.5), layout="constrained")
        FigureCanvasAgg(fig)
        fig.set_dpi(dpi)
        # the full path found above: started by its bare name, ffmpeg is looked up again by
        # the operating system, which can fail where the lookup above succeeded
        with matplotlib.rc_context({"animation.ffmpeg_path": ffmpeg}):
            writer = FFMpegWriter(fps=fps)
            writer.setup(fig, str(path), dpi)
            try:
                for step in indices:
                    fig.clear()
                    ax = fig.add_subplot(1, 1, 1)
                    plots.contour(results, step, field, ax=ax, **options)
                    writer.grab_frame()
            finally:
                writer.finish()
    log.info("wrote animation of %d frame(s) to %s", len(indices), path)
    return path
