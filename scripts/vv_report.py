"""V&V report (task M11.2): run the version-1 verification cases and write ``docs/vv-report.md``.

Usage::

    .venv\\Scripts\\python.exe scripts\\vv_report.py [--out PATH] [--cases V-01,V-10]

Every case is run exactly as its test does (same element types, meshes and arguments) through
the ``run()`` function of its example script (``examples/vNN_*.py``). One small function per
case maps the ``run()`` result to rows of the report. Tolerances come from the constants of
the example modules; where a test keeps a literal, ``LITERALS`` below cites the test file and
``tests/unit/test_vv_report.py`` checks that the number is still in that file.

Exit status is 1 when any row fails.
"""

from __future__ import annotations

import argparse
import datetime
import math
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "verification"
DEFAULT_OUT = ROOT / "docs" / "vv-report.md"

for _path in (str(TESTS), str(ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import cases  # noqa: E402  (tests/verification/cases.py)

TYPES = list(cases.TYPES)

#: Literal tolerances kept in the tests: name -> (test file, text that must occur in it, value).
LITERALS: dict[str, tuple[str, str, float]] = {
    "v03_heat": ("test_v03_generation_slab.py", '["heat_error"] < 1e-10', 1e-10),
    "v09_centre": ("test_v09_rectangle_series.py", "abs=1e-3)", 1e-3),
    "v10_coarse": ("test_v10_nafems_t4.py", '["T_degC"] - example.TARGET_C) < 1.0', 1.0),
    "v14_root": ("test_v14_nafems_t2.py", '["root_error_K"] < 1e-6', 1e-6),
    "v18_far_end": ("test_v18_semi_infinite.py", '["far_end_change"] < 1e-6', 1e-6),
    "stream_balance": ("test_v27_stream_constant_wall.py", '["imbalance"]) < 1e-8', 1e-8),
    "v30_mass": ("test_v30_parallel_ducts.py", '["mass_conservation"] < 1e-10', 1e-10),
    "v31_mass": ("test_v31_unequal_ducts.py", '["mass_conservation"] < 1e-10', 1e-10),
    "v33_interior": ("test_v33_patch.py", "temperature[interior] - exact[interior]) /"
                     " exact[interior]) < 1e-12", 1e-12),
    "v33_flux": ("test_v33_patch.py", "q_nodes - q_exact)) / scale < 1e-10", 1e-10),
    "v33_balance": ("test_v33_patch.py", "balance.relative_imbalance) < 1e-8", 1e-8),
    "v37_interior": ("test_v37_tet_guard.py", "exact[interior]) < 1e-10", 1e-10),
    "v37_flux": ("test_v37_tet_guard.py", "np.broadcast_to(expected, q.shape), rtol=1e-10", 1e-10),
    "v37_face": ("test_v37_tet_guard.py", "pytest.approx(1.0, rel=1e-13)", 1e-13),
    "v37_balance": ("test_v37_tet_guard.py", "balance.relative_imbalance) < 1e-8", 1e-8),
}

#: Version 1 excludes these cases (owner, 2026-11-22, Q29.15).
EXCLUDED: dict[str, str] = {
    "V-22a": "M9 enclosure radiation is on hold",
    "V-22b": "M9 enclosure radiation is on hold",
    "V-22c": "M9 enclosure radiation is on hold",
    "V-22d": "M9 enclosure radiation is on hold",
    "V-23": "M9 enclosure radiation is on hold",
    "V-24": "M9 enclosure radiation is on hold",
    "V-36": "M10.2 phase change is on hold",
}

SCOPE_NOTE = (
    "Version 1 excludes the held features M9 (enclosure radiation) and M10.2 (phase change) "
    "and their cases V-22a-d, V-23, V-24 and V-36 (owner, 2026-11-22, Q29.15)."
)


@dataclass
class Row:
    """One line of the report."""

    case: str
    element: str
    quantity: str
    analytic: object  # a number or a short text
    computed: object  # a number, text or None
    error: float
    kind: str  # "relative", "absolute" or "order"
    tol: float
    op: str = "<"  # the row passes when error < tol (or error >= tol for op ">=")

    @property
    def passed(self) -> bool:
        if not math.isfinite(self.error):
            return False
        return self.error >= self.tol if self.op == ">=" else self.error < self.tol


@dataclass
class Run:
    """One call of an example's ``run``."""

    element: str
    args: tuple = ()
    kwargs: dict | None = None
    label: str = ""  # appended to the element column, e.g. "theta = 0.5"

    @property
    def element_text(self) -> str:
        return f"{self.element}, {self.label}" if self.label else self.element


@dataclass
class Case:
    """One entry of the case table."""

    id: str
    group: str
    module: str | None
    runs: Callable[[ModuleType], list[Run]]
    rows: Callable[[ModuleType, Run, dict], list[Row]]
    linear_steady: bool = True  # V-34 limit for the balance row
    balance: bool = True
    note: str = ""


def literal(name: str) -> float:
    """A tolerance kept as a literal in a test (see ``LITERALS``)."""
    return LITERALS[name][2]


def _rel(case: str, run: Run, quantity: str, analytic: object, error: float, tol: float,
         computed: object = None, kind: str = "relative") -> Row:
    return Row(case, run.element_text, quantity, analytic, computed, float(error), kind, tol)


def _types(_: ModuleType) -> list[Run]:
    return [Run(t) for t in TYPES]


def _call(mod: ModuleType, run: Run) -> dict:
    if run.element == "—":  # a case without element types: ``run()`` takes no arguments
        return mod.run() if mod is not _V37Module else mod.run(run.element)
    return mod.run(run.element, *run.args, **(run.kwargs or {}))


def _balance_row(case: Case, run: Run, res: dict, quantity: str = "relative energy imbalance"
                 ) -> Row:
    limit = cases.BALANCE_LINEAR_STEADY if case.linear_steady else cases.BALANCE
    return Row(case.id, run.element_text, quantity + " (V-34)", "0", None,
               abs(float(res["imbalance"])), "relative", limit)


# --- steady conduction -------------------------------------------------------------------

def rows_v01(m, run, r):
    t = m.TOL
    return [
        _rel("V-01", run, "T, max relative error over the nodes", "linear T(x)", r["error"], t),
        _rel("V-01", run, "flux q = k dT/L, max relative error", "k (T0 - TL)/L",
             r["flux_error"], t),
        _rel("V-01", run, "heat flow 'hot'", "q A", r["heat_error"], t),
    ]


def rows_v02(m, run, r):
    t = m.TOL
    return [
        _rel("V-02", run, "T, max relative error over the nodes", "linear T(x)", r["error"], t),
        _rel("V-02", run, "T(L), relative error", "T_inf + (T0 - T_inf)/(1 + hL/k)",
             r["end_error"], t),
        _rel("V-02", run, "heat flow 'conv'", "k (T0 - T(L))/L", r["heat_error"], t),
    ]


def rows_v03(m, run, r):
    return [
        _rel("V-03", run, "T, max relative error over the nodes", "300 + Q/(2k) x (L - x)",
             r["error"], m.tolerance(run.element)),
        _rel("V-03", run, "heat flow 'gen'", "Q L A", r["heat_error"], literal("v03_heat")),
    ]


def rows_v04(m, run, r):
    return [
        _rel("V-04", run, "T, max relative error over the nodes", "linear T(x)",
             r["error"], m.TOL),
        _rel("V-04", run, "T(0), relative error", "300 + q L/k", r["face_error"], m.TOL),
    ]


def rows_v05(m, run, r):
    t = m.tolerance(run.element)
    return [
        _rel("V-05", run, "T, max relative error over the nodes", "T(r) logarithmic",
             r["error"], t),
        _rel("V-05", run, "heat flow per height 'inner'", "2 pi k (Ti - To)/ln(ro/ri)",
             r["heat_error"], t),
    ]


def rows_v06(m, run, r):
    return [
        _rel("V-06", run, "T, max relative error over the nodes", "T(r) logarithmic",
             r["error"], m.TOL),
        _rel("V-06", run, "heat flow 'inner' (quarter)", "1/4 of 2 pi k (Ti - To)/ln(ro/ri)",
             r["heat_error"], m.TOL),
    ]


def rows_v07(m, run, r):
    return [
        _rel("V-07", run, "T, max relative error over the nodes",
             "T_inf + QR/(2h) + Q (R^2 - r^2)/(4k)", r["error"], m.TOL),
        _rel("V-07", run, "heat flow 'conv'", "generated heat", r["heat_error"], m.TOL),
    ]


def rows_v08(m, run, r):
    return [_rel("V-08", run, "T, max relative error over the nodes",
                 "1D fin with convecting tip", r["error"], m.TOL)]


def rows_v09(m, run, r):
    return [
        _rel("V-09", run, "T, max relative error at (0.5, 0.5), (0.5, 0.75)",
             "Fourier series", r["error"], m.TOL),
        Row("V-09", run.element_text, "theta at (0.5, 0.5)", 0.25, r["centre_theta"],
            abs(r["centre_theta"] - 0.25), "absolute", literal("v09_centre")),
    ]


def runs_v10(m):
    return [Run(t, (s,), label=f"size {s:g}") for t in TYPES for s in m.SIZES]


def rows_v10(m, run, r):
    fine = run.args[0] == m.SIZES[-1]
    tol = m.TOL_C if fine else literal("v10_coarse")
    return [Row("V-10", run.element_text, "T at (0.6, 0.2) [degC]", m.TARGET_C, r["T_degC"],
                r["error_degC"], "absolute", tol)]


def rows_v11(m, run, r):
    t = m.TOL
    return [
        _rel("V-11", run, "T, max relative error over the nodes", "series resistance",
             r["error"], t),
        _rel("V-11", run, "interface T, relative error", "400 - 100 (L1/k1)/(L1/k1 + L2/k2)",
             r["interface_error"], t),
        _rel("V-11", run, "nodal flux, one value per region, relative error", "q",
             r["flux_error"], t),
    ]


def rows_v12(m, run, r):
    return [_rel("V-12", run, "T, max relative error over the nodes",
                 "300 + 50 x^2 + 30 x y + 20 y^2", r["error"], m.TOL)]


# --- nonlinear steady --------------------------------------------------------------------

def rows_v13(m, run, r):
    return [
        _rel("V-13", run, "T, max relative error over the nodes", "Kirchhoff transform",
             r["error"], m.TOL),
        _rel("V-13", run, "heat flow 'hot'", "k0 (U(400) - U(300))/L", r["heat_error"], m.TOL),
    ]


def rows_v14(m, run, r):
    return [
        Row("V-14", run.element_text, "T at the radiating end [K]", m.TARGET, r["T_end"],
            r["error_K"], "absolute", m.TOL_K),
        Row("V-14", run.element_text, "T at the radiating end vs the root of the balance [K]",
            m.root(), r["T_end"], r["root_error_K"], "absolute", literal("v14_root")),
    ]


def rows_v15(m, run, r):
    return [Row("V-15", run.element_text, "T_s at the convecting face [K]", m.root(),
                r["T_surface"], r["error"], "relative", m.TOL)]


# --- transient ---------------------------------------------------------------------------

def runs_v16(m):
    return [Run(t, (th,), label=f"theta = {th:g}") for t in TYPES for th in (1.0, 0.5)]


def rows_v16(m, run, r):
    th = run.args[0]
    return [_rel("V-16", run, "T at t = tau and 3 tau, max relative error",
                 "T_inf + (Ti - T_inf) exp(-hAt/(rho c V))", r["error"], m.TOL[th])]


def rows_v17(m, run, r):
    return [_rel("V-17", run, "T at centre and surface, Fo = 0.2 and 1.0, max relative error",
                 "20-term series", r["error"], m.TOL)]


def rows_v18(m, run, r):
    return [
        _rel("V-18", run, "T at x = 0.01, 0.02 m, t = 30 s, max relative error",
             "400 - 100 erf(x/(2 sqrt(alpha t)))", r["error"], m.TOL),
        Row("V-18", run.element_text, "far-end temperature change [K]", "0", r["far_end_change"],
            r["far_end_change"], "absolute", literal("v18_far_end")),
    ]


def runs_v19(m):
    return [Run(t, (th,), label=f"theta = {th:g}") for t in m.TYPES for th in (0.5, 1.0)]


def rows_v19(m, run, r):
    th = run.args[0]
    return [Row("V-19", run.element_text, "T at (0.08, 32 s) [degC]", m.TARGET_C, r["T_degC"],
                r["error_degC"], "absolute", m.TOL_C[th])]


def rows_v20(m, run, r):
    return [_rel("V-20", run, "T at 0.25 and 1.0 of the end time, max relative error",
                 "solve_ivp, rtol 1e-10", r["error"], m.TOL)]


def runs_v21(m):
    return [Run(t, (th,), label=f"theta = {th:g}") for t in TYPES for th in (1.0, 0.5)]


def rows_v21(m, run, r):
    th = run.args[0]
    return [Row("V-21", run.element_text, "observed time order", m.EXPECTED[th], r["order"],
                r["order_error"], "absolute", m.TOL)]


# --- flow and convection -----------------------------------------------------------------

def _single(_: ModuleType) -> list[Run]:
    return [Run("—")]


V25_NAMES = (
    "plate_forced_avg", "plate_forced_local", "cylinder_crossflow", "vplate_natural",
    "inclined_natural", "hplate_up_natural", "hplate_down_natural", "hcyl_natural",
    "duct_internal", "power_law",
)


def rows_v25(m, run, r):
    return [_rel("V-25", run, f"Nu or h, '{name}', largest relative error",
                 "formula of Theory 8", r[name], m.TOL) for name in r]


def rows_v26(m, run, r):
    return [
        Row("V-26", "—", "Churchill f at Re = 500", 64.0 / m.RE_LAMINAR, r["f_laminar"],
            r["laminar_error"], "relative", m.TOL_LAMINAR),
        Row("V-26", "—", "Churchill f at Re = 1e5 (smooth)", r["f_smooth_reference"],
            r["f_turbulent"], r["turbulent_error"], "relative", m.TOL_TURBULENT),
    ]


def runs_v27(m):
    return [Run(t, (n,), label=f"{n} cell{'s' if n > 1 else ''}") for t in TYPES for n in m.CELLS]


def rows_v27(m, run, r):
    return [
        Row("V-27", run.element_text, "T_out [K]", r["T_exact"], r["T_out"], r["error"],
            "relative", m.TOL),
        _rel("V-27", run, "fluid profile, max relative error", "T_w - (T_w - T_in) exp(-NTU x)",
             r["profile_error"], m.TOL),
    ]


def rows_v28(m, run, r):
    return [
        _rel("V-28", run, "T_out", "T_in + q A/(m cp)", r["error_out"], m.TOL_OUT,
             computed=r["T_out"]),
        _rel("V-28", run, "wall-to-fluid dT, max relative error", "q/h", r["error_dT"], m.TOL_DT),
    ]


def runs_v29(m):
    return [Run(t, (v,), label=v) for t in TYPES for v in m.VARIANTS]


def rows_v29(m, run, r):
    return [_rel("V-29", run, "boundary heat + m cp (T_in - T_out), relative to throughput",
                 "0", r["error"], m.TOL, kind="relative")]


def rows_v30(m, run, r):
    return [
        _rel("V-30", run, "flow split between the two ducts", "equal", r["split_error"], m.TOL),
        _rel("V-30", run, "total flow vs the single duct", "2 x single-duct flow",
             r["total_error"], m.TOL),
        _rel("V-30", run, "dp laminar law", "32 mu L V/D^2", r["laminar_error"], m.TOL),
        Row("V-30", "—", "mass conservation at the junction [kg/s]", "0", None,
            r["mass_conservation"], "absolute", literal("v30_mass")),
    ]


def rows_v31(m, run, r):
    return [
        _rel("V-31", run, "dp of the short duct", "applied dp (Churchill f)",
             r["dp_error_short"], m.TOL),
        _rel("V-31", run, "dp of the long duct", "applied dp (Churchill f)",
             r["dp_error_long"], m.TOL),
        Row("V-31", "—", "mass conservation at the junction [kg/s]", "0", None,
            r["mass_conservation"], "absolute", literal("v31_mass")),
    ]


# --- convergence and robustness ----------------------------------------------------------

def rows_v32(m, run, r):
    return [Row("V-32", run.element_text, "L2 error order (h = 0.1, 0.05, 0.025), smallest",
                f">= {m.required_order(run.element):g}", r["order"], r["order"], "order",
                m.required_order(run.element), op=">=")]


def _v33(run_etype: str) -> dict:
    import numpy as np
    import test_v33_patch as t

    from thermalfea.core.meshgen import distort, rect_mesh
    from thermalfea.post.energy import energy_balance
    from thermalfea.post.recovery import element_flux, nodal_flux
    from thermalfea.solver.steady import steady_solution

    worst = {"interior": 0.0, "flux": 0.0, "balance": 0.0}
    for seed in (1, 2, 3):
        mesh = distort(rect_mesh(*t.BOX, *t.grid(run_etype), run_etype), 0.2, seed)
        exact = t.T_REF + mesh.nodes @ t.GRAD
        fixed = cases.boundary_nodes(mesh)
        interior = np.setdiff1d(np.arange(mesh.n_nodes), fixed)
        problem = cases.conduction_problem(mesh, t.K, fixed, exact[fixed])
        result = steady_solution(problem)
        q_exact = -t.K * t.GRAD
        scale = np.linalg.norm(q_exact)
        (_, q_nodes), = nodal_flux(mesh, problem, result.T).values()
        flux = max(np.max(np.abs(q_nodes - q_exact)),
                   np.max(np.abs(element_flux(mesh, problem, result.T) - q_exact))) / scale
        balance = energy_balance(problem, result.T, system=result.system)
        worst["interior"] = max(worst["interior"], float(
            np.max(np.abs(result.T[interior] - exact[interior]) / exact[interior])))
        worst["flux"] = max(worst["flux"], float(flux))
        worst["balance"] = max(worst["balance"], abs(float(balance.relative_imbalance)))
    return worst


class _V33Module:
    """Stands in for an example module: V-33 has no example script."""

    @staticmethod
    def run(etype: str) -> dict:
        return _v33(etype)


def rows_v33(m, run, r):
    return [
        _rel("V-33", run, "interior T, max relative error, 3 irregular patches", "linear T",
             r["interior"], literal("v33_interior")),
        _rel("V-33", run, "nodal and element flux, max error / |q|", "-k grad T (constant)",
             r["flux"], literal("v33_flux")),
        _rel("V-33", run, "relative energy imbalance (V-34)", "0", r["balance"],
             literal("v33_balance")),
    ]


def rows_v35(m, run, r):
    t = m.TOL
    return [
        _rel("V-35", run, "T, max relative error over the nodes", "series resistance with 1/h_c",
             r["error"], t),
        _rel("V-35", run, "temperature jump at the contact", "q/h_c", r["jump_error"], t),
        _rel("V-35", run, "flux q", "series resistance with 1/h_c", r["flux_error"], t),
    ]


def _v37(_: str) -> dict:
    import numpy as np
    import test_v37_tet_guard as t

    from thermalfea.core import registry
    from thermalfea.physics.kernel import facet_geometry, gfactor
    from thermalfea.post.energy import energy_balance
    from thermalfea.post.recovery import element_flux
    from thermalfea.solver.steady import steady_solution

    et = t.make_tet4()
    registry.register_element(et)
    try:
        mesh = t.cube_mesh(et, t.N_CELLS)
        exact = 300.0 + mesh.nodes @ t.GRAD
        fixed = cases.boundary_nodes(mesh)
        interior = np.setdiff1d(np.arange(mesh.n_nodes), fixed)
        problem = cases.conduction_problem(mesh, t.K, fixed, exact[fixed])
        result = steady_solution(problem)
        expected = np.array([-500.0, -1000.0, -1500.0])
        q = element_flux(mesh, problem, result.T)
        balance = energy_balance(problem, result.T, system=result.system)
        face = 0.0
        for tag in range(1, 7):
            (block,) = mesh.facets_on([tag])
            fg = facet_geometry(block, mesh.nodes)
            g = gfactor(fg.xgp, False, 1.0, mesh.dim)
            face = max(face, abs(float((g * fg.dS).sum()) - 1.0))
        return {
            "interior": float(np.max(np.abs(result.T[interior] - exact[interior])
                                     / exact[interior])),
            "flux": float(np.max(np.abs(q - expected) / np.abs(expected))),
            "face": face,
            "balance": abs(float(balance.relative_imbalance)),
        }
    finally:
        registry._ELEMENTS.pop("Tet4", None)


class _V37Module:
    @staticmethod
    def run(etype: str) -> dict:
        return _v37(etype)


def rows_v37(m, run, r):
    return [
        _rel("V-37", run, "interior T, max relative error (3D patch)", "linear T",
             r["interior"], literal("v37_interior")),
        _rel("V-37", run, "element flux (-500, -1000, -1500), max relative error",
             "-k grad T", r["flux"], literal("v37_flux")),
        Row("V-37", run.element_text, "integral of a unit flux over each cube face", 1.0, None,
            r["face"], "absolute", literal("v37_face")),
        _rel("V-37", run, "relative energy imbalance (V-34)", "0", r["balance"],
             literal("v37_balance")),
    ]


# --- the case table ----------------------------------------------------------------------

STEADY, NONLIN, TRANS, FLOW, ROBUST, GUARD = (
    "Steady conduction", "Nonlinear steady", "Transient", "Flow and convection",
    "Mesh convergence and robustness", "Extensibility guard")


def _c(id_, group, module, rows, runs=_types, **kw) -> Case:
    return Case(id_, group, module, runs, rows, **kw)


CASES: list[Case] = [
    _c("V-01", STEADY, "v01_slab", rows_v01),
    _c("V-02", STEADY, "v02_convection_slab", rows_v02),
    _c("V-03", STEADY, "v03_generation_slab", rows_v03),
    _c("V-04", STEADY, "v04_flux_slab", rows_v04),
    _c("V-05", STEADY, "v05_hollow_cylinder", rows_v05),
    _c("V-06", STEADY, "v06_quarter_annulus", rows_v06),
    _c("V-07", STEADY, "v07_solid_cylinder", rows_v07),
    _c("V-08", STEADY, "v08_fin", rows_v08),
    _c("V-09", STEADY, "v09_rectangle_series", rows_v09),
    _c("V-10", STEADY, "v10_nafems_t4", rows_v10, runs=runs_v10),
    _c("V-11", STEADY, "v11_two_layer_slab", rows_v11),
    _c("V-12", STEADY, "v12_orthotropic", rows_v12,
       runs=lambda m: [Run(t) for t in m.TYPES]),
    _c("V-13", NONLIN, "v13_kirchhoff", rows_v13, linear_steady=False),
    _c("V-14", NONLIN, "v14_nafems_t2", rows_v14, linear_steady=False),
    _c("V-15", NONLIN, "v15_natural_convection", rows_v15, linear_steady=False),
    _c("V-16", TRANS, "v16_lumped_body", rows_v16, runs=runs_v16),
    _c("V-17", TRANS, "v17_slab_convection", rows_v17),
    _c("V-18", TRANS, "v18_semi_infinite", rows_v18),
    _c("V-19", TRANS, "v19_nafems_t3", rows_v19, runs=runs_v19),
    _c("V-20", TRANS, "v20_radiative_cooling", rows_v20, linear_steady=False),
    _c("V-21", TRANS, "v21_time_order", rows_v21, runs=runs_v21),
    _c("V-25", FLOW, "v25_correlations", rows_v25, runs=_single, balance=False),
    _c("V-26", FLOW, "v26_friction", rows_v26, runs=_single, balance=False),
    _c("V-27", FLOW, "v27_stream_constant_wall", rows_v27, runs=runs_v27),
    _c("V-28", FLOW, "v28_stream_constant_flux", rows_v28),
    _c("V-29", FLOW, "v29_stream_energy", rows_v29, runs=runs_v29),
    _c("V-30", FLOW, "v30_parallel_ducts", rows_v30, runs=_single, balance=False),
    _c("V-31", FLOW, "v31_unequal_ducts", rows_v31, runs=_single, balance=False),
    _c("V-32", ROBUST, "v32_convergence", rows_v32),
    _c("V-33", ROBUST, None, rows_v33, balance=False),
    _c("V-35", ROBUST, "v35_thermal_contact", rows_v35),
    _c("V-37", GUARD, None, rows_v37, runs=_single, balance=False),
]

#: Cases whose own rows already carry the V-34 balance (V-33, V-37) or have none (flow cases);
#: V-27-V-29 carry the example's signed ``imbalance`` and are checked at 1e-8 like the tests.
SPECIAL_MODULES = {"V-33": _V33Module, "V-37": _V37Module}

DECISIONS = [
    "V-25: the 10 correlation checks of `examples/v25_correlations.py` (`run()`), one row each; "
    "the pure-function test file repeats the same formulas with more points.",
    "V-26: both Churchill checks (laminar 64/Re, smooth turbulent within 3%).",
    "V-27, V-28, V-29: balance row uses the example's `imbalance` against 1e-8, as the tests do.",
    "V-30, V-31: network cases without a balance row; mass conservation is a row.",
    "V-33: no example script; run here with the test's own mesh helpers (3 irregular patches "
    "per element type, worst case reported).",
    "V-37: no example script; the 3D patch is run with the test's own `Tet4` and cube mesh, "
    "registered only for the run. Interior T, flux, face integral and balance are rows.",
    "V-34: one balance row per case run (limit 1e-8 for linear steady cases, 1e-3 otherwise).",
    "V-10: both mesh sizes; the coarse mesh is checked against the test's literal of 1.0 degC.",
    "Gate, tutorial and pump-closure tests have no analytic target and are not part of the "
    "report.",
]


# --- running -----------------------------------------------------------------------------

def run_case(case: Case) -> list[Row]:
    """Run one case as its test does and return its rows."""
    mod = SPECIAL_MODULES[case.id] if case.id in SPECIAL_MODULES else cases.load(case.module)
    rows: list[Row] = []
    for run in case.runs(mod):
        result = _call(mod, run)
        rows += case.rows(mod, run, result)
        if case.balance and "imbalance" in result:
            rows.append(_balance_row(case, run, result))
    return rows


def run_all(selected: list[str] | None = None, progress: Callable[[str], None] | None = None
            ) -> list[tuple[Case, list[Row]]]:
    out = []
    for case in CASES:
        if selected and case.id not in selected:
            continue
        start = time.perf_counter()
        rows = run_case(case)
        if progress:
            fails = sum(not r.passed for r in rows)
            progress(f"{case.id}: {len(rows)} rows, {fails} failed, "
                     f"{time.perf_counter() - start:.1f} s")
        out.append((case, rows))
    return out


# --- writing -----------------------------------------------------------------------------

def fmt(value: object) -> str:
    """A number as ``:.6g``, text as is, None as an em dash."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        return f"{value:.6g}"
    return str(value)


def esc(text: object) -> str:
    """Markdown table text: pipes escaped, no line breaks."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def tolerance_text(row: Row) -> str:
    return f"{'≥' if row.op == '>=' else '<'} {row.tol:.6g}"


def row_line(row: Row) -> str:
    cells = [
        row.case, row.element, row.quantity, fmt(row.analytic), fmt(row.computed),
        f"{row.error:.6g} ({row.kind})", tolerance_text(row), "Pass" if row.passed else "Fail",
    ]
    return "| " + " | ".join(esc(c) for c in cells) + " |"


HEADER = ("| Case | Element | Quantity | Analytic | Computed | Error | Tolerance | Result |\n"
          "|---|---|---|---|---|---|---|---|")


def git_state() -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()

    try:
        return git("rev-parse", "--short", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.CalledProcessError):
        return "unknown", False


def render(results: list[tuple[Case, list[Row]]], commit: str, dirty: bool,
           date: datetime.date | None = None) -> str:
    date = date or datetime.date.today()
    rows = [r for _, rs in results for r in rs]
    failed = sum(not r.passed for r in rows)
    summary = (f"{len(rows)} rows, all passed." if failed == 0
               else f"{len(rows)} rows, {failed} failed.")
    lines = [
        "# Verification and validation report",
        "",
        f"Date: {date.isoformat()}  ",
        f"Commit: {commit}{' (uncommitted changes)' if dirty else ''}",
        "",
        f"Scope: {SCOPE_NOTE}",
        "",
        f"**Summary: {summary}**",
        "",
        "Generated by `scripts/vv_report.py`; each case is run as its test runs it. "
        "Errors are relative unless marked absolute; a row passes when the error is below the "
        "tolerance (at least the tolerance for convergence orders).",
    ]
    groups: dict[str, list[Row]] = {}
    for case, rs in results:
        groups.setdefault(case.group, []).extend(rs)
    for group, rs in groups.items():
        lines += ["", f"## {group}", "", HEADER, *[row_line(r) for r in rs]]
    lines += ["", "## Decisions", "", *[f"- {d}" for d in DECISIONS]]
    lines += ["", "## Excluded from version 1", "",
              *[f"- {k}: {v}" for k, v in EXCLUDED.items()], ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cases", default="", help="comma-separated case IDs, e.g. V-01,V-10")
    args = parser.parse_args(argv)
    selected = [c.strip() for c in args.cases.split(",") if c.strip()] or None
    known = {c.id for c in CASES}
    if selected and (bad := [c for c in selected if c not in known]):
        sys.stderr.write(f"unknown case(s): {', '.join(bad)}\n")
        return 2
    results = run_all(selected, progress=lambda s: sys.stderr.write(s + "\n"))
    commit, dirty = git_state()
    text = render(results, commit, dirty)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    failed = sum(not r.passed for _, rs in results for r in rs)
    sys.stderr.write(f"wrote {args.out.name}: {failed} failed row(s)\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
