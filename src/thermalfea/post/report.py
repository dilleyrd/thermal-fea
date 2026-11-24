"""Self-contained HTML report of one results file (M10.5).

:func:`write_report` writes one HTML file: inline CSS, the plots embedded as base64 PNG
images, and no external links or scripts. The numbers come from
:func:`~thermalfea.post.summary.summarize`, the :class:`Results` handle (its embedded model,
its region data and its solver settings) and the mesh quality report.
"""

from __future__ import annotations

import base64
import dataclasses
import html
import io
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.figure import Figure

from ..core.errors import ModelError
from ..core.functions import Constant, Expression, Table
from ..core.units import si_label
from ..meshing import quality
from .plots import FIELDS, contour, contour_fields, draw_history, heat_flow_history_data
from .results import Results
from .summary import Summary, summarize

log = logging.getLogger(__name__)

#: Resolution of the embedded plot images [dpi].
IMAGE_DPI = 110

_CSS = """
body { font-family: system-ui, sans-serif; margin: 0 auto; max-width: 980px; padding: 16px;
  color: #1d1d1f; line-height: 1.45; }
h1 { font-size: 1.6em; margin-bottom: 0.2em; }
h2 { border-bottom: 1px solid #c8c8cc; padding-bottom: 4px; margin-top: 1.8em; font-size: 1.25em; }
h3 { font-size: 1.05em; margin-bottom: 0.2em; }
table { border-collapse: collapse; margin: 0.6em 0; width: 100%; font-size: 0.92em; }
th, td { border: 1px solid #c8c8cc; padding: 4px 8px; text-align: left; vertical-align: top;
  overflow-wrap: anywhere; }
th { background: #f0f0f3; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em 0; }
.muted { color: #6e6e73; }
.warnings { color: #8a4b00; }
"""

#: Labels of the energy-balance columns (the relative imbalance is dimensionless).
_ENERGY_LABELS = {
    "heat_in": "Heat in [W]",
    "heat_out": "Heat out [W]",
    "net": "Net [W]",
    "stored_rate": "Stored rate [W]",
    "imbalance": "Imbalance [W]",
    "relative_imbalance": "Relative imbalance (of the throughput)",
}

#: Mesh-quality rows: (key of ``QualityReport.summary()``, label).
_QUALITY_ROWS = (
    ("min_angle_min", "Smallest interior angle, worst element [deg]"),
    ("min_angle_mean", "Smallest interior angle, mean [deg]"),
    ("aspect_ratio_max", "Aspect ratio, worst element [-]"),
    ("aspect_ratio_mean", "Aspect ratio, mean [-]"),
    ("jacobian_ratio_min", "Jacobian ratio, worst element [-]"),
    ("jacobian_ratio_mean", "Jacobian ratio, mean [-]"),
)

_FUNCTIONS = (Constant, Expression, Table)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _number(value: float, unit: str = "") -> str:
    text = f"{value:.6g}"
    return f"{text} {unit}" if unit else text


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _pairs(rows: Sequence[tuple[str, object]]) -> str:
    return _table(("Item", "Value"), rows)


def _function_text(f: Constant | Expression | Table) -> str:
    """The text of a function: its value, its formula, or a note on its table."""
    if isinstance(f, Constant):
        return f"{f.value:.6g}"
    if isinstance(f, Expression):
        return f.text
    return f"table in {f.variable}, {len(f.xs)} points"


def _value_text(value: Any) -> str:
    """Plain text of any model value: numbers with :.6g, functions as their text."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, _FUNCTIONS):
        return _function_text(value)
    if isinstance(value, (float, np.floating)):
        return f"{value:.6g}"
    if isinstance(value, (int, np.integer)):
        return str(value)
    if isinstance(value, str):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return "; ".join(
            f"{f.name}: {_value_text(getattr(value, f.name))}"
            for f in dataclasses.fields(value)
        )
    if isinstance(value, (list, tuple)):
        return "; ".join(_value_text(v) for v in value) or "—"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_value_text(v)}" for k, v in value.items()) or "—"
    return str(value)


def _figure_uri(fig: Figure) -> str:
    """Render a figure to PNG bytes in memory and return it as a data URI; closes it."""
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=IMAGE_DPI)
    finally:
        fig.clear()
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _section(section_id: str, title: str, body: str) -> str:
    return f'<section>\n<h2 id="{section_id}">{_esc(title)}</h2>\n{body}\n</section>'


def _model_section(results: Results, summary: Summary) -> str:
    model = results.model
    rows: list[tuple[str, object]] = [
        ("Model name", model.name if model is not None else "(not stored in the results file)"),
        ("Analysis", results.meta["analysis"]),
        ("Created", results.meta["created"]),
        ("Results file", results.path.name),
        ("Nodes", summary.n_nodes),
        ("Elements", summary.n_elements),
        ("Stored steps", summary.n_steps),
        ("Reported step: time [s]", _number(summary.time)),
        ("End time [s]", _number(summary.end_time)),
        (
            "Minimum temperature",
            f"{_number(summary.t_min, summary.unit)} at node {summary.t_min_node} "
            f"({summary.t_min_at[0]:.6g}, {summary.t_min_at[1]:.6g}) m",
        ),
        (
            "Maximum temperature",
            f"{_number(summary.t_max, summary.unit)} at node {summary.t_max_node} "
            f"({summary.t_max_at[0]:.6g}, {summary.t_max_at[1]:.6g}) m",
        ),
    ]
    body = _pairs(rows)
    if summary.warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in summary.warnings)
        body += f'\n<h3>Warnings</h3>\n<ul class="warnings">{items}</ul>'
    return _section("summary", "Model", body)


def _materials_section(results: Results) -> str:
    regions = results.problem.regions
    rows = []
    for region_id in sorted(regions):
        region = regions[region_id]
        m = region.material
        rows.append(
            (
                region.name,
                m.name,
                _value_text(m.k),
                _value_text(m.rho),
                _value_text(m.cp),
                _number(region.thickness),
            )
        )
    header = (
        "Region",
        "Material",
        f"k [{si_label('conductivity')}]",
        f"rho [{si_label('density')}]",
        f"c_p [{si_label('specific_heat')}]",
        f"thickness [{si_label('length')}]",
    )
    body = _table(header, rows) if rows else "<p class=\"muted\">No regions.</p>"
    return _section("materials", "Materials", body)


def _mesh_section(results: Results) -> str:
    q = quality.report(results.mesh)
    counts = _table(("Element type", "Count"), list(q.counts.items()))
    stats = q.summary()
    rows = [("Nodes", q.n_nodes), ("Elements", q.n_elements)]
    rows += [(label, _number(stats[key])) for key, label in _QUALITY_ROWS if key in stats]
    body = f"<h3>Counts</h3>\n{counts}\n<h3>Quality</h3>\n{_pairs(rows)}"
    return _section("mesh", "Mesh", body)


def _loads_section(model: Any) -> str:
    if model is None:
        return _section(
            "loads", "Loads",
            '<p class="muted">The results file holds no model, so no loads are listed.</p>',
        )
    by_kind: dict[str, list[Any]] = {}
    for item in [*model.bcs, *model.contacts, *model.streams]:
        by_kind.setdefault(type(item).__name__, []).append(item)
    parts: list[str] = []
    for kind, members in by_kind.items():
        fields = [f.name for f in dataclasses.fields(members[0]) if f.name != "name"]
        rows = [
            [item.name, *(_value_text(getattr(item, f)) for f in fields)] for item in members
        ]
        parts.append(f"<h3>{_esc(kind)}</h3>\n{_table(['Name', *fields], rows)}")
    body = "\n".join(parts) if parts else '<p class="muted">No loads are defined.</p>'
    return _section("loads", "Loads", body)


def _solver_section(results: Results, summary: Summary) -> str:
    settings = results.meta["settings"]
    rows: list[tuple[str, object]] = [(key, _value_text(v)) for key, v in settings.items()]
    rows += [
        ("Stored steps", results.n_steps),
        ("Total iterations", summary.total_iterations),
        ("Most iterations in one step", summary.max_iterations),
        ("Unconverged steps", summary.unconverged_steps),
    ]
    if settings.get("kind") == "transient":
        dt = np.asarray(results.dt, dtype=float)
        dt = dt[np.isfinite(dt) & (dt > 0.0)]
        rows += [
            ("Smallest time step [s]", _number(dt.min()) if dt.size else "—"),
            ("Largest time step [s]", _number(dt.max()) if dt.size else "—"),
        ]
    return _section("solver", "Solver", _pairs(rows))


def _energy_section(results: Results, summary: Summary) -> str:
    flows = [(name, _number(value, "W")) for name, value in summary.heat_flows.items()]
    flow_table = (
        _table(("Boundary condition or load", "Heat entering the body"), flows)
        if flows else '<p class="muted">No heat flow is stored for this step.</p>'
    )
    columns = [
        (_ENERGY_LABELS.get(key, key), _number(value)) for key, value in summary.energy.items()
    ]
    rel = np.asarray(results.energy_balance().get("relative_imbalance", []), dtype=float)
    finite = np.abs(rel[np.isfinite(rel)])
    largest = _number(float(finite.max())) if finite.size else "—"
    body = (
        f"<h3>Heat flow at the reported step</h3>\n{flow_table}\n"
        f"<h3>Energy balance at the reported step</h3>\n{_pairs(columns)}\n"
        f"<p>Largest |relative imbalance| over all {results.n_steps} stored steps: "
        f"{largest}</p>"
    )
    return _section("energy", "Energy balance", body)


def _plots_section(results: Results, step: int, fields: Sequence[str]) -> str:
    images: list[str] = []
    for name in fields:
        title = FIELDS[name][3]
        uri = _figure_uri(contour(results, step, field=name))
        images.append(f'<h3>{_esc(title)}</h3>\n<img alt="{_esc(title)}" src="{uri}">')
    if results.meta["settings"].get("kind") == "transient" and results.heat_flow_names:
        data = heat_flow_history_data(results)
        uri = _figure_uri(draw_history(data))
        images.append(f'<h3>{_esc(data.title)}</h3>\n<img alt="{_esc(data.title)}" src="{uri}">')
    body = "\n".join(images) if images else '<p class="muted">No plots were requested.</p>'
    return _section("plots", "Plots", body)


def write_report(
    results: Results,
    path: str | Path,
    step: int = -1,
    plots: Sequence[str] = ("T",),
) -> Path:
    """Write the HTML report of one results file.

    Parameters
    ----------
    results : Results
    path : str or Path
        HTML file to write (replaced if it exists).
    step : int
        Stored step that the summary, the energy balance and the contour plots refer to;
        negative counts from the end.
    plots : sequence of str
        Contour fields to embed (keys of :data:`~thermalfea.post.plots.FIELDS`); a transient
        with heat flows also gets the heat-flow history chart.

    Returns
    -------
    Path
        The file written.

    Raises
    ------
    ModelError
        For an unknown plot field or a step out of range.
    """
    allowed = contour_fields(results)
    for name in plots:
        if name not in allowed:
            raise ModelError(
                f"unknown contour field {name!r}; choose from {', '.join(allowed)}"
            )
    summary = summarize(results, step)
    model = results.model
    model_name = model.name if model is not None else results.path.name
    sections = [
        _model_section(results, summary),
        _materials_section(results),
        _mesh_section(results),
        _loads_section(model),
        _solver_section(results, summary),
        _energy_section(results, summary),
        _plots_section(results, step, tuple(plots)),
    ]
    title = f"ThermalFEA report – {model_name}"
    document = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"<h1>{_esc(title)}</h1>\n" + "\n".join(sections) + "\n</body>\n</html>\n"
    )
    target = Path(path)
    target.write_text(document, encoding="utf-8")
    log.info("report written to %s", target)
    return target
