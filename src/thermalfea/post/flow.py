"""Post-processing of fluid streams (M7.5).

:func:`wall_temperature` and :func:`plot_stream` show the fluid and the mean wall temperature
of an in-plane stream against its path coordinate ``s``. :func:`stream_summary` gathers the
stored numbers of every stream at one step, and :func:`format_stream_summary` lays them out
as a text table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from matplotlib.figure import Figure
from numpy import ndarray

from ..convection.correlations import RE_LAMINAR, RE_TURBULENT
from ..core.errors import ModelError
from ..flow.stream import path_coordinate
from ..model.bcs import Stream
from .plots import _figure
from .results import Results

_NO_STREAMS = "no streams"
_EMPTY = "-"


def _stream_definition(results: Results, stream: str) -> Stream:
    """The model's definition of an in-plane stream; ModelError otherwise."""
    model = results.model
    if model is None:
        raise ModelError("the results have no embedded model; wall temperatures are unavailable")
    definition = next((st for st in model.streams if st.name == stream), None)
    if definition is None:
        names = ", ".join(st.name for st in model.streams) or "none"
        raise ModelError(f"unknown stream {stream!r} (streams in the model: {names})")
    if definition.mode != "in_plane":
        raise ModelError(f"stream {stream!r} is through-plane and has no fluid path")
    return definition


def wall_temperature(results: Results, stream: str, step: int = -1) -> tuple[ndarray, ndarray]:
    """Mean wall temperature of an in-plane stream against its path coordinate.

    Parameters
    ----------
    results : Results
    stream : str
        Name of an in-plane stream in the results.
    step : int
        Stored step; negative counts from the end.

    Returns
    -------
    s : ndarray, shape (n,)
        Path coordinate of the wall nodes [m], ascending.
    T_wall : ndarray, shape (n,)
        Temperature [K] of the wall nodes; nodes that share one ``s`` (two walls of a
        channel) are averaged.

    Raises
    ------
    ModelError
        If the results have no embedded model, the stream is unknown or through-plane.
    """
    definition = _stream_definition(results, stream)
    model, mesh = results.model, results.mesh
    tags: set[int] = set()
    for wall in definition.walls:
        if wall not in model.selections:
            raise ModelError(f"stream {stream!r}: unknown wall selection {wall!r}")
        tags.update(model.selections[wall].tags)
    node_sets = [fb.conn[np.isin(fb.entity, list(tags))] for fb in mesh.facets]
    nodes = np.unique(np.concatenate([c.ravel() for c in node_sets]))
    if nodes.size == 0:
        raise ModelError(f"stream {stream!r}: its walls contain no mesh facets")

    polyline = np.asarray(definition.path, dtype=float)
    length = float(np.linalg.norm(np.diff(polyline, axis=0), axis=1).sum())
    s = path_coordinate(mesh.nodes[nodes], polyline)
    temperature = np.asarray(results.temperature(step))[nodes]

    order = np.argsort(s, kind="stable")
    s, temperature = s[order], temperature[order]
    # nodes whose path coordinates agree to a tiny fraction of the path length share one s
    groups = np.split(np.arange(s.size), np.flatnonzero(np.diff(s) > 1e-9 * length) + 1)
    s_out = np.array([s[g].mean() for g in groups])
    t_out = np.array([temperature[g].mean() for g in groups])
    return s_out, t_out


def plot_stream(results: Results, stream: str, step: int = -1) -> Figure:
    """Fluid and mean wall temperature of an in-plane stream against ``s``.

    Parameters
    ----------
    results : Results
    stream : str
        Name of an in-plane stream.
    step : int
        Stored step; negative counts from the end.

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        See :func:`wall_temperature`; also for a through-plane stream.
    """
    s_wall, t_wall = wall_temperature(results, stream, step)
    s_fluid = np.asarray(results.stream(stream)["s"], dtype=float)
    t_fluid = results.fluid_temperature(stream, step)
    index = results._step(step)
    fig, ax = _figure(None)
    ax.plot(s_fluid, t_fluid, label="fluid")
    ax.plot(s_wall, t_wall, label="mean wall")
    ax.set_xlabel("s [m]")
    ax.set_ylabel("T [K]")
    ax.set_title(f"Stream {stream}, t = {float(results.times[index]):.6g} s")
    ax.grid(True)
    ax.legend()
    return fig


def flow_regime(Re: float) -> str:
    """Flow regime of internal duct flow from the Reynolds number.

    Uses the limits of :mod:`thermalfea.convection.correlations` (Theory §8.1) as the
    calculator does: laminar for ``Re <= RE_LAMINAR``, turbulent for ``Re >= RE_TURBULENT``
    and transitional in between.

    Parameters
    ----------
    Re : float
        Reynolds number [-].

    Returns
    -------
    str
        ``"laminar"``, ``"transitional"`` or ``"turbulent"``; ``""`` for NaN.
    """
    if math.isnan(Re):
        return ""
    if Re <= RE_LAMINAR:
        return "laminar"
    if Re < RE_TURBULENT:
        return "transitional"
    return "turbulent"


@dataclass
class StreamSummary:
    """The stored numbers of one stream at one step (SI units; NaN where not applicable).

    Attributes
    ----------
    name : str
        Stream name.
    mode : str
        ``"in_plane"`` or ``"through_plane"``.
    mass_flow : float
        Mass flow rate [kg/s].
    Re : float
        Reynolds number [-].
    regime : str
        Flow regime (see :func:`flow_regime`).
    h_mean : float
        Mean heat-transfer coefficient [W/(m^2 K)].
    dp : float
        Pressure drop [Pa].
    T_in, T_out : float
        Inlet and outlet fluid temperature [K].
    heat : float
        Heat picked up from the walls [W].
    """

    name: str
    mode: str
    mass_flow: float
    Re: float
    regime: str
    h_mean: float
    dp: float
    T_in: float
    T_out: float
    heat: float


def stream_summary(results: Results, step: int = -1) -> list[StreamSummary]:
    """One :class:`StreamSummary` per stream in the results, at one step.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.

    Returns
    -------
    list of StreamSummary
        Empty when the results contain no streams.
    """
    index = results._step(step)
    rows = []
    for name in results.streams:
        data = results.stream(name)
        values = {
            key: float(data[key][index])
            for key in ("mass_flow", "Re", "h_mean", "dp", "T_in", "T_out", "heat")
        }
        rows.append(
            StreamSummary(
                name=name,
                mode=str(data["mode"]),
                regime=flow_regime(values["Re"]),
                **values,
            )
        )
    return rows


def format_stream_summary(rows: list[StreamSummary]) -> str:
    """Lay out stream summaries as a plain-text table.

    Parameters
    ----------
    rows : list of StreamSummary

    Returns
    -------
    str
        A header line with units and one line per stream, without a trailing newline; NaN
        values and an empty regime are shown as ``-``. For an empty list the single line
        ``"no streams"`` is returned.
    """
    if not rows:
        return _NO_STREAMS
    header = [
        "stream", "m_dot [kg/s]", "Re", "regime", "h [W/(m^2 K)]",
        "dp [Pa]", "T_in [K]", "T_out [K]", "heat [W]",
    ]
    table = [header]
    for r in rows:
        numbers = [r.mass_flow, r.Re, r.h_mean, r.dp, r.T_in, r.T_out, r.heat]
        cells = [f"{v:.6g}" if not math.isnan(v) else _EMPTY for v in numbers]
        table.append([r.name, cells[0], cells[1], r.regime or _EMPTY, *cells[2:]])
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
             for row in table]
    return "\n".join(lines)
