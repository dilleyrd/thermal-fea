"""Text summary of one stored step of a results file (M5.6).

:func:`summarize` gathers the numbers of a step into a :class:`Summary`;
:func:`format_summary` lays them out as text for the command line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .flow import format_stream_summary, stream_summary
from .plots import _display_temperature
from .results import Results

log = logging.getLogger(__name__)

#: Relative energy imbalance (of the throughput) above which a warning is given.
IMBALANCE_LIMIT = 1e-3

#: Energy-balance columns in the order they are printed: (column, label).
_ENERGY_LINES = (
    ("heat_in", "heat in"),
    ("heat_out", "heat out"),
    ("net", "net"),
    ("stored_rate", "stored rate"),
    ("imbalance", "imbalance"),
)


@dataclass
class Summary:
    """The numbers printed by the text summary of one stored step.

    Attributes
    ----------
    analysis : str
        Analysis label, e.g. ``"planar, transient"``.
    n_nodes, n_elements : int
        Size of the mesh.
    n_steps : int
        Number of stored steps.
    time : float
        Time of the summarised step [s].
    end_time : float
        Time of the last stored step [s].
    t_min, t_max : float
        Smallest and largest nodal temperature of the step, in the display unit (NaN when
        no temperature is finite).
    t_min_at, t_max_at : tuple of float
        Coordinates (x, y) [m] of the nodes holding ``t_min`` and ``t_max``.
    t_min_node, t_max_node : int
        Indices of those nodes.
    unit : str
        Temperature unit label: ``"K"``, ``"°C"`` or ``"°F"``.
    heat_flows : dict of str to float
        Boundary condition or load name -> heat entering the body at the step [W]; names
        with no stored value at the step are left out.
    energy : dict of str to float
        The energy-balance columns at the step [W] (relative imbalance is dimensionless).
    total_iterations : int
        Sum of the iterations of all stored steps.
    max_iterations : int
        Largest number of iterations of any stored step.
    unconverged_steps : int
        Number of stored steps flagged as not converged.
    warnings : list of str
        Plain sentences describing problems found.
    """

    analysis: str
    n_nodes: int
    n_elements: int
    n_steps: int
    time: float
    end_time: float
    t_min: float
    t_min_at: tuple[float, float]
    t_min_node: int
    t_max: float
    t_max_at: tuple[float, float]
    t_max_node: int
    unit: str
    heat_flows: dict[str, float]
    energy: dict[str, float]
    total_iterations: int
    max_iterations: int
    unconverged_steps: int
    warnings: list[str]


def summarize(results: Results, step: int = -1) -> Summary:
    """Gather the summary of one stored step.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end (default the last).

    Returns
    -------
    Summary

    Raises
    ------
    ModelError
        If the step is out of range.
    """
    kelvin = np.asarray(results.temperature(step), dtype=float)
    time = float(results.times[step])
    temperature, unit = _display_temperature(results, kelvin)
    finite = np.isfinite(temperature)
    if finite.any():
        i_min = int(np.argmin(np.where(finite, temperature, np.inf)))
        i_max = int(np.argmax(np.where(finite, temperature, -np.inf)))
        kelvin_min = float(np.min(np.where(finite, kelvin, np.inf)))
    else:
        i_min = i_max = 0
        kelvin_min = float("nan")
    mesh = results.mesh
    xy_min = mesh.nodes[i_min, :2]
    xy_max = mesh.nodes[i_max, :2]

    heat_flows: dict[str, float] = {}
    for name in results.heat_flow_names:
        value = float(results.heat_flow(name)[step])
        if not np.isnan(value):
            heat_flows[name] = value

    energy = {key: float(column[step]) for key, column in results.energy_balance().items()}
    iterations = np.asarray(results.iterations)
    unconverged = int(np.count_nonzero(~np.asarray(results.converged, dtype=bool)))

    warnings: list[str] = []
    if unconverged:
        warnings.append(f"{unconverged} step(s) did not converge")
    imbalance = energy["relative_imbalance"]
    if np.isfinite(imbalance) and abs(imbalance) > IMBALANCE_LIMIT:
        limit = f"{IMBALANCE_LIMIT:.0e}".replace("-0", "-")
        warnings.append(
            f"energy imbalance is {imbalance:.1e} of the throughput (limit {limit})"
        )
    if not finite.all():
        warnings.append("the solution contains non-finite temperatures")
    if finite.any() and kelvin_min <= 0.0:
        warnings.append("temperatures at or below 0 K: check that temperatures are absolute")

    return Summary(
        analysis=str(results.meta["analysis"]),
        n_nodes=int(mesh.n_nodes),
        n_elements=int(mesh.n_elements),
        n_steps=results.n_steps,
        time=time,
        end_time=float(results.times[-1]),
        t_min=float(temperature[i_min]) if finite.any() else float("nan"),
        t_min_at=(float(xy_min[0]), float(xy_min[1])),
        t_min_node=i_min,
        t_max=float(temperature[i_max]) if finite.any() else float("nan"),
        t_max_at=(float(xy_max[0]), float(xy_max[1])),
        t_max_node=i_max,
        unit=unit,
        heat_flows=heat_flows,
        energy=energy,
        total_iterations=int(np.sum(iterations)),
        max_iterations=int(np.max(iterations)) if iterations.size else 0,
        unconverged_steps=unconverged,
        warnings=warnings,
    )


def format_summary(summary: Summary) -> str:
    """Lay out a :class:`Summary` as text.

    Parameters
    ----------
    summary : Summary

    Returns
    -------
    str
        Several lines, without a trailing newline.
    """
    s = summary
    lines = [
        f"Analysis:      {s.analysis}",
        f"Mesh:          {s.n_nodes} nodes, {s.n_elements} elements",
        f"Steps stored:  {s.n_steps} (end at t = {s.end_time:.6g} s); "
        f"summary at t = {s.time:.6g} s",
        f"Temperature:   min {s.t_min:.6g} {s.unit} at node {s.t_min_node} "
        f"({s.t_min_at[0]:.6g}, {s.t_min_at[1]:.6g})",
        f"               max {s.t_max:.6g} {s.unit} at node {s.t_max_node} "
        f"({s.t_max_at[0]:.6g}, {s.t_max_at[1]:.6g})",
        f"Iterations:    {s.total_iterations} in total, at most {s.max_iterations} per step",
        "Heat entering the body [W]:",
    ]
    if s.heat_flows:
        width = max(len(name) for name in s.heat_flows)
        lines += [f"  {name:<{width}}  {value:.6g}" for name, value in s.heat_flows.items()]
    else:
        lines.append("  (none stored for this step)")

    lines.append("Energy balance [W]:")
    if all(np.isnan(value) for value in s.energy.values()):
        lines.append("  (none stored for this step)")
    else:
        for key, label in _ENERGY_LINES:
            value = s.energy[key]
            row = f"  {label:<12}{value:.6g}"
            if key == "imbalance":
                row += f"  ({s.energy['relative_imbalance']:.2g} of the throughput)"
            lines.append(row)

    if s.warnings:
        lines.append("Warnings:")
        lines += [f"  - {message}" for message in s.warnings]
    return "\n".join(lines)


def text_summary(results: Results, step: int = -1) -> str:
    """The text summary of one stored step.

    This is ``format_summary(summarize(results, step))``, followed, when the results contain
    streams, by the stream table of :func:`~thermalfea.post.flow.format_stream_summary`.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end (default the last).

    Raises
    ------
    ModelError
        If the step is out of range.
    """
    text = format_summary(summarize(results, step))
    if results.streams:
        table = format_stream_summary(stream_summary(results, step), results.display_units)
        text += "\nStreams:\n" + table
    return text
