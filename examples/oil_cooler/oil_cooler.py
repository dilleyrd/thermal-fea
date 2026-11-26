"""Counterflow double-pipe oil cooler: an axisymmetric copper tube between two streams.

Hot engine oil flows up the bore of a copper tube (z = 0 to L); cooling water flows down the
annulus between the tube and an adiabatic shell (z = L to 0). Only the copper wall is meshed;
the two liquids are in-plane streams (Theory §9.1) on the bore and on the outside of the tube.
The model's axisymmetric coordinates are x = r (radius) and y = z (axial).

Three runs, each with its own check (``examples/oil_cooler/README.md``):

* ``reference``   -- constant film coefficients (``h_override``) on both streams. The two
  outlets and the duty are compared with the counterflow effectiveness-NTU method, and the
  comparison is repeated with finer axial meshes (stream cells follow the wall edges).
* ``correlation`` -- the duct correlations of Theory §8.1: the circular laminar Nusselt
  number for the oil and the heated inner surface of the annulus (``annulus_inner``) for the
  water. Reports Re, mean h and the regime of each stream.
* ``startup``     -- from the converged correlation run, the oil inlet temperature rises by
  20 K over 1 s; the water inlet and both flows are held. The heat released by the oil minus
  the heat gained by the water is compared with the change of the copper's internal energy,
  and the end state with a separate steady run at the new oil inlet temperature.

Run from the project folder::

    .venv\\Scripts\\python.exe examples\\oil_cooler\\oil_cooler.py

It prints the checks, writes the figures to ``examples/oil_cooler/img`` and the models to
``examples/oil_cooler/models``. Every input that is a choice, not a library property, is
marked "assumption" below (owner-approved values of 2026-11-26).
"""

from __future__ import annotations

import math
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from thermalfea import api
from thermalfea.core.functions import Table
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.materials import library
from thermalfea.model.bcs import Stream
from thermalfea.model.model import InitialCondition, Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.post import flow
from thermalfea.post.results import Results

HERE = Path(__file__).resolve().parent
IMAGES = HERE / "img"
MODELS = HERE / "models"

# ----------------------------------------------------------------------------- inputs
#: Tube: ASTM B88 Type K copper tube, 3/8 in nominal: OD 0.500 in, wall 0.049 in.
D_O = 0.500 * 0.0254  # m, tube outside diameter (12.70 mm)
WALL = 0.049 * 0.0254  # m, wall thickness (1.245 mm)
D_I = D_O - 2.0 * WALL  # m, tube bore (10.21 mm)
D_S = 0.020  # m, shell bore (assumption)
LENGTH = 2.0  # m, straight copper span (assumption)

COPPER = "Copper (pure)"  # Incropera Table A.1, 300 K
OIL = "Engine Oil (Unused)"  # Incropera Table A.5 ("unused engine oil"), 273-430 K
WATER = "Water"  # library liquid water, 0.1 MPa, 280-370 K

M_OIL = 0.002  # kg/s (assumption)
M_WATER = 0.003  # kg/s (assumption)
T_WATER_IN = 290.0  # K (assumption)
T_OIL_IN = 350.0  # K before the step (assumption)
T_OIL_STEP = 370.0  # K after the step (assumption)
RAMP = 1.0  # s, the oil inlet rises linearly over this time
END_TIME = 120.0  # s of the start-up run
DT_MAX = 0.25  # s, largest time step of the start-up (fine run: a quarter of it)

#: Axial elements (= stream cells) of the main mesh, and the radial elements of the wall.
N_AXIAL, N_RADIAL = 200, 4
REFINEMENTS = (50, 100, 200, 400)

#: Laminar Nusselt numbers of Theory §8.1 (constant wall temperature): circular duct, and
#: the heated inner surface of a concentric annulus against D_i/D_o (linear interpolation).
NU_CIRCULAR = 3.66
NU_ANNULUS_INNER = ((0.05, 17.46), (0.10, 11.56), (0.25, 7.37), (0.50, 5.74), (1.00, 4.86))

OIL_STREAM, WATER_STREAM = "Oil", "Water"
OIL_WALL, WATER_WALL, ENDS = "oil wall", "water wall", "tube ends"


# ------------------------------------------------------------------------- geometry
def oil_area() -> float:
    """Oil flow area: the tube bore [m^2]."""
    return math.pi * D_I**2 / 4.0


def oil_perimeter() -> float:
    """Oil wetted perimeter [m]."""
    return math.pi * D_I


def water_area() -> float:
    """Water flow area: the annulus between tube and shell [m^2]."""
    return math.pi * (D_S**2 - D_O**2) / 4.0


def water_perimeter() -> float:
    """Water wetted perimeter: both walls of the annulus, D_h = D_s - D_o [m]."""
    return math.pi * (D_S + D_O)


def diameter_ratio() -> float:
    """D_i/D_o of the annulus: tube outside diameter over shell bore."""
    return D_O / D_S


def _on_radius(value: float):
    return lambda c: abs(c.bbox[0] - value) < 1e-6 and abs(c.bbox[3] - value) < 1e-6


def _on_height(value: float):
    return lambda c: abs(c.bbox[1] - value) < 1e-6 and abs(c.bbox[4] - value) < 1e-6


def build(
    variant: str = "correlation", n_axial: int = N_AXIAL, oil_inlet=T_OIL_IN,
    h_override: tuple[float, float] | None = None,
) -> tuple[Model, BuiltGeometry]:  # fmt: skip
    """The cooler model, geometry built and selections made, ready to mesh.

    Parameters
    ----------
    variant : str
        Model name suffix ("reference", "correlation", "startup", ...).
    n_axial : int
        Elements along the tube (and so stream cells: one per wall edge).
    oil_inlet : float or Function
        Oil inlet temperature [K] (a ``Table`` against time for the start-up).
    h_override : (h_oil, h_water), optional
        Constant film coefficients [W/(m^2 K)] replacing the duct correlations.
    """
    model = api.new_model("axisymmetric", name=f"Oil cooler ({variant})")
    api.Geometry(model).rectangle(D_I / 2.0, 0.0, WALL, LENGTH)
    built = api.build(model)
    api.select_curves(model, built, OIL_WALL, where=_on_radius(D_I / 2.0))
    api.select_curves(model, built, WATER_WALL, where=_on_radius(D_O / 2.0))
    bottom = api.select_curves(model, built, "bottom end", where=_on_height(0.0))
    top = api.select_curves(model, built, "top end", where=_on_height(LENGTH))
    api.select_curves(model, built, ENDS, tags=[*bottom.tags, *top.tags])
    del model.selections["bottom end"], model.selections["top end"]
    api.assign_region(model, "all", material=COPPER)
    oil_h, water_h = h_override if h_override is not None else (None, None)
    model.streams += [
        Stream(
            name=OIL_STREAM, fluid=OIL, mode="in_plane", walls=[OIL_WALL],
            flow_area=oil_area(), wetted_perimeter=oil_perimeter(),
            cross_section="circular", T_inlet=oil_inlet, mass_flow=M_OIL,
            path=[(D_I / 2.0, 0.0), (D_I / 2.0, LENGTH)], h_override=oil_h,
        ),
        Stream(
            name=WATER_STREAM, fluid=WATER, mode="in_plane", walls=[WATER_WALL],
            flow_area=water_area(), wetted_perimeter=water_perimeter(),
            cross_section="annulus_inner", diameter_ratio=diameter_ratio(),
            T_inlet=T_WATER_IN, mass_flow=M_WATER,
            path=[(D_O / 2.0, LENGTH), (D_O / 2.0, 0.0)], h_override=water_h,
        ),
    ]  # fmt: skip
    settings = model.mesh_settings
    settings.global_size = LENGTH / n_axial
    settings.element_shape = "quad"
    settings.curve_divisions = {OIL_WALL: n_axial, WATER_WALL: n_axial, ENDS: N_RADIAL}
    settings.structured_surfaces = ["all"]
    return model, built


# ------------------------------------------------------------------ hand calculation
@dataclass
class Ntu:
    """Counterflow effectiveness-NTU prediction (Incropera Table 11.3)."""

    h_oil: float
    h_water: float
    UA: float
    C_oil: float
    C_water: float
    Cr: float
    NTU: float
    effectiveness: float
    Q: float
    T_oil_out: float
    T_water_out: float


def nusselt_annulus_inner(ratio: float) -> float:
    """Laminar Nu of the heated inner surface of an annulus, interpolated in D_i/D_o."""
    xs, ys = zip(*NU_ANNULUS_INNER, strict=True)
    return float(np.interp(ratio, xs, ys))


def correlation_h(oil_inlet: float = T_OIL_IN) -> tuple[float, float]:
    """Laminar fully developed film coefficients with properties at the inlet temperatures."""
    oil = library.fluid(OIL).props(oil_inlet)
    water = library.fluid(WATER).props(T_WATER_IN)
    h_oil = NU_CIRCULAR * float(oil.k) / D_I
    h_water = nusselt_annulus_inner(diameter_ratio()) * float(water.k) / (D_S - D_O)
    return h_oil, h_water


def ntu_prediction(h_oil: float, h_water: float, oil_inlet: float = T_OIL_IN) -> Ntu:
    """Both outlets and the duty from the counterflow effectiveness-NTU relation.

    ``1/UA = 1/(h_o pi D_i L) + ln(D_o/D_i)/(2 pi k L) + 1/(h_w pi D_o L)``; heat-capacity
    rates with c_p at each stream's inlet temperature (as the solver takes them);
    ``eps = (1 - E)/(1 - Cr E)``, ``E = exp(-NTU (1 - Cr))`` (``eps = NTU/(1 + NTU)`` at Cr = 1).
    """
    k = float(library.solid(COPPER).k.value)
    resistance = (
        1.0 / (h_oil * math.pi * D_I * LENGTH)
        + math.log(D_O / D_I) / (2.0 * math.pi * k * LENGTH)
        + 1.0 / (h_water * math.pi * D_O * LENGTH)
    )
    UA = 1.0 / resistance
    C_oil = M_OIL * float(library.fluid(OIL).props(oil_inlet).cp)
    C_water = M_WATER * float(library.fluid(WATER).props(T_WATER_IN).cp)
    c_min, c_max = min(C_oil, C_water), max(C_oil, C_water)
    Cr, NTU = c_min / c_max, UA / c_min
    if abs(1.0 - Cr) < 1e-9:
        eps = NTU / (1.0 + NTU)
    else:
        E = math.exp(-NTU * (1.0 - Cr))
        eps = (1.0 - E) / (1.0 - Cr * E)
    Q = eps * c_min * (oil_inlet - T_WATER_IN)
    return Ntu(h_oil, h_water, UA, C_oil, C_water, Cr, NTU, eps, Q,
               oil_inlet - Q / C_oil, T_WATER_IN + Q / C_water)  # fmt: skip


# ------------------------------------------------------------------------- solving
def solve(model: Model, built: BuiltGeometry, path: Path | None = None) -> Results:
    """Mesh and solve; the results file goes to ``path`` (default a temporary file)."""
    mesh = api.mesh(model, built)
    if path is None:
        path = Path(tempfile.mkdtemp(prefix="oil-cooler-")) / "run.tfea.h5"
    return api.solve(model, mesh, built=built, path=path)


def streams(results: Results, step: int = -1) -> dict[str, flow.StreamSummary]:
    """The stream summaries of one step, by name."""
    return {s.name: s for s in flow.stream_summary(results, step)}


def compare(results: Results, prediction: Ntu) -> dict:
    """Outlets and duties of the solver against the effectiveness-NTU prediction."""
    rows = streams(results)
    oil, water = rows[OIL_STREAM], rows[WATER_STREAM]
    q_oil, q_water = -oil.heat, water.heat  # oil release and water gain, both positive
    return {
        "T_oil_out": oil.T_out, "T_water_out": water.T_out,
        "dT_oil_out": oil.T_out - prediction.T_oil_out,
        "dT_water_out": water.T_out - prediction.T_water_out,
        "Q_oil": q_oil, "Q_water": q_water,
        "dQ_oil": q_oil - prediction.Q, "dQ_water": q_water - prediction.Q,
        "dQ_oil_pct": 100.0 * (q_oil - prediction.Q) / prediction.Q,
        "dQ_water_pct": 100.0 * (q_water - prediction.Q) / prediction.Q,
    }  # fmt: skip


def reference_study() -> dict:
    """Constant film coefficients: the solver against effectiveness-NTU, on four meshes."""
    h = correlation_h()
    prediction = ntu_prediction(*h)
    rows = []
    for n in REFINEMENTS:
        model, built = build("reference", n_axial=n, h_override=h)
        result = compare(solve(model, built), prediction)
        result["n_axial"] = n
        rows.append(result)
    return {"prediction": prediction, "rows": rows}


def axial_profiles(results: Results, step: int = -1) -> dict:
    """Bulk and wall temperatures of both streams against the axial coordinate z."""
    s_oil = results.stream(OIL_STREAM)["s"]
    s_water = results.stream(WATER_STREAM)["s"]
    zo_wall, To_wall = flow.wall_temperature(results, OIL_STREAM, step)
    zw_wall, Tw_wall = flow.wall_temperature(results, WATER_STREAM, step)
    return {
        "z_oil": np.asarray(s_oil), "T_oil": results.fluid_temperature(OIL_STREAM, step),
        "z_water": LENGTH - np.asarray(s_water),
        "T_water": results.fluid_temperature(WATER_STREAM, step),
        "z_oil_wall": np.asarray(zo_wall), "T_oil_wall": np.asarray(To_wall),
        "z_water_wall": LENGTH - np.asarray(zw_wall), "T_water_wall": np.asarray(Tw_wall),
    }  # fmt: skip


def copper_energy(results: Results, step: int) -> float:
    """Internal energy of the copper relative to 0 K, rho c_p integral of T dV [J].

    Bilinear quads: each element's volume is 2 pi r_c times its area (r at its centroid),
    times the mean temperature of its corner nodes; second order in the element size, which
    is ample for the 0.1 % check of the start-up.
    """
    cu = library.solid(COPPER)
    rho_cp = float(cu.rho.value) * float(cu.cp.value)
    T = results.temperature(step)
    nodes = results.mesh.nodes
    total = 0.0
    for block in results.mesh.blocks:
        corners = block.conn[:, :4]
        xy = nodes[corners]
        x, y = xy[..., 0], xy[..., 1]
        area = 0.5 * np.abs(
            (x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0]) + (x[:, 1] * y[:, 2] - x[:, 2] * y[:, 1])
            + (x[:, 2] * y[:, 3] - x[:, 3] * y[:, 2]) + (x[:, 3] * y[:, 0] - x[:, 0] * y[:, 3])
        )  # fmt: skip
        volume = 2.0 * math.pi * x.mean(axis=1) * area
        total += float(np.sum(volume * T[corners].mean(axis=1)))
    return rho_cp * total


def startup_model(steady_path: Path) -> tuple[Model, BuiltGeometry]:
    """The start-up run: oil inlet 350 -> 370 K over 1 s, from the steady results file."""
    ramp = Table([0.0, RAMP], [T_OIL_IN, T_OIL_STEP], "t")
    model, built = build("startup", oil_inlet=ramp)
    model.initial_condition = InitialCondition("from_results", results_path=str(steady_path))
    model.solution = SolutionSettings(
        kind="transient", end_time=END_TIME, initial_dt=0.02, dt_max=DT_MAX, auto_timestep=True,
        output="every_n", output_every=1,
    )  # fmt: skip
    return model, built


def startup_study(steady_path: Path, dt_scale: float = 1.0) -> dict:
    """Solve the start-up and check the copper energy storage against the two duties."""
    model, built = startup_model(steady_path)
    model.solution.initial_dt *= dt_scale
    if model.solution.dt_max is not None:
        model.solution.dt_max *= dt_scale
    model.solution.time_tol *= dt_scale
    results = solve(model, built)
    times = np.asarray(results.times)
    q_oil = np.array([-streams(results, i)[OIL_STREAM].heat for i in range(len(times))])
    q_water = np.array([streams(results, i)[WATER_STREAM].heat for i in range(len(times))])
    T_oil_in = np.array([streams(results, i)[OIL_STREAM].T_in for i in range(len(times))])
    T_oil_out = np.array([streams(results, i)[OIL_STREAM].T_out for i in range(len(times))])
    T_water_out = np.array([streams(results, i)[WATER_STREAM].T_out for i in range(len(times))])
    # trapezoidal integral of the net heat into the copper; the fluid holds no energy
    net = q_oil - q_water
    stored = float(np.sum(0.5 * (net[1:] + net[:-1]) * np.diff(times)))
    delta_u = copper_energy(results, -1) - copper_energy(results, 0)
    mid = _mid_wall_node(results)
    T_mid = np.array([results.temperature(i)[mid] for i in range(len(times))])
    return {
        "results": results, "times": times, "q_oil": q_oil, "q_water": q_water,
        "T_oil_in": T_oil_in, "T_oil_out": T_oil_out, "T_water_out": T_water_out,
        "T_mid": T_mid, "stored": stored, "delta_u": delta_u, "n_steps": len(times),
    }  # fmt: skip


def _mid_wall_node(results: Results) -> int:
    """The node at mid-length, mid-wall of the copper."""
    nodes = results.mesh.nodes
    target = np.array([D_I / 2.0 + WALL / 2.0, LENGTH / 2.0])
    return int(np.argmin(np.linalg.norm(nodes[:, :2] - target, axis=1)))


# ------------------------------------------------------------------------------ run
def run() -> dict:
    """Every run and check of the page."""
    MODELS.mkdir(exist_ok=True)
    out: dict = {"reference": reference_study()}

    model, built = build("correlation")
    steady_path = Path(tempfile.mkdtemp(prefix="oil-cooler-")) / "oil-cooler.tfea.h5"
    steady = solve(model, built, steady_path)
    rows = streams(steady)
    out["correlation"] = {
        "results": steady, "model": model, "rows": rows, "profiles": axial_profiles(steady),
        "ntu": ntu_prediction(*correlation_h()), "path": steady_path,
    }  # fmt: skip
    api.save(model, MODELS / "oil-cooler.tfea")

    model_after, built_after = build("after step", oil_inlet=T_OIL_STEP)
    after = solve(model_after, built_after)
    out["after"] = {
        "rows": streams(after),
        "ntu": ntu_prediction(*correlation_h(T_OIL_STEP), oil_inlet=T_OIL_STEP),
    }
    out["startup"] = startup_study(steady_path)
    out["startup_fine"] = startup_study(steady_path, dt_scale=0.25)
    start_model, _ = startup_model(Path("oil-cooler.tfea.h5"))
    api.save(start_model, MODELS / "oil-cooler-startup.tfea")
    return out


def report(out: dict) -> str:
    """The numbers the page quotes, as text."""
    lines = []
    ref = out["reference"]
    p = ref["prediction"]
    lines += [
        "== Geometry",
        f"D_i {D_I * 1e3:.2f} mm, D_o {D_O * 1e3:.2f} mm, wall {WALL * 1e3:.3f} mm, "
        f"D_s {D_S * 1e3:.1f} mm, L {LENGTH} m, D_o/D_s {diameter_ratio():.4f}",
        f"oil A {oil_area():.4e} m2, P {oil_perimeter():.4e} m; water A {water_area():.4e} m2,"
        f" P {water_perimeter():.4e} m, D_h {4 * water_area() / water_perimeter() * 1e3:.3f} mm",
        "== Reference (constant h): effectiveness-NTU",
        f"h_oil {p.h_oil:.3f}, h_water {p.h_water:.3f} W/(m2 K); UA {p.UA:.4f} W/K; "
        f"C_oil {p.C_oil:.4f}, C_water {p.C_water:.4f} W/K; Cr {p.Cr:.4f}; NTU {p.NTU:.4f}; "
        f"eps {p.effectiveness:.4f}; Q {p.Q:.3f} W; T_oil,out {p.T_oil_out:.3f} K; "
        f"T_water,out {p.T_water_out:.3f} K",
    ]
    for r in ref["rows"]:
        lines.append(
            f"  n {r['n_axial']:4d}: T_oil,out {r['T_oil_out']:.3f} ({r['dT_oil_out']:+.4f} K)"
            f"  T_water,out {r['T_water_out']:.3f} ({r['dT_water_out']:+.4f} K)"
            f"  Q_oil {r['Q_oil']:.3f} ({r['dQ_oil_pct']:+.3f} %)"
            f"  Q_water {r['Q_water']:.3f} ({r['dQ_water_pct']:+.3f} %)"
        )
    c = out["correlation"]
    lines.append("== Correlation run")
    for name, row in c["rows"].items():
        lines.append(
            f"  {name}: Re {row.Re:.2f} ({row.regime}), h_mean {row.h_mean:.2f} W/(m2 K), "
            f"T_in {row.T_in:.3f}, T_out {row.T_out:.3f} K, heat {row.heat:.3f} W, "
            f"dp {row.dp:.2f} Pa"
        )
    n = c["ntu"]
    lines.append(
        f"  e-NTU with the inlet-temperature h: Q {n.Q:.3f} W, T_oil,out {n.T_oil_out:.3f}, "
        f"T_water,out {n.T_water_out:.3f} K"
    )
    imbalance = float(c["results"].energy_balance()["relative_imbalance"][-1])
    lines.append(f"  imbalance (relative) {imbalance:.2e}")
    oil, water = c["rows"][OIL_STREAM], c["rows"][WATER_STREAM]
    d1, d2 = oil.T_in - water.T_out, oil.T_out - water.T_in
    lmtd = (d1 - d2) / math.log(d1 / d2)
    k_cu = float(library.solid(COPPER).k.value)
    ua_mean = 1.0 / (
        1.0 / (oil.h_mean * math.pi * D_I * LENGTH)
        + math.log(D_O / D_I) / (2.0 * math.pi * k_cu * LENGTH)
        + 1.0 / (water.h_mean * math.pi * D_O * LENGTH)
    )
    lines.append(
        f"  LMTD {lmtd:.3f} K; Q/LMTD {water.heat / lmtd:.4f} W/K; UA from the mean h "
        f"{ua_mean:.4f} W/K"
    )
    for name, fluid, area, flow_rate, T_in in ((OIL_STREAM, OIL, oil_area(), M_OIL, T_OIL_IN),
                                               (WATER_STREAM, WATER, water_area(), M_WATER,
                                                T_WATER_IN)):  # fmt: skip
        rho = float(library.fluid(fluid).props(T_in).rho)
        velocity = flow_rate / (rho * area)
        lines.append(f"  {name}: mean velocity {velocity * 1e3:.1f} mm/s, transit time "
                     f"L/V {LENGTH / velocity:.0f} s (not modelled: the streams are "
                     "quasi-steady)")  # fmt: skip
    a = out["after"]
    lines.append("== Steady at the stepped oil inlet")
    for name, row in a["rows"].items():
        lines.append(f"  {name}: T_out {row.T_out:.3f} K, heat {row.heat:.3f} W")
    for key in ("startup", "startup_fine"):
        s = out[key]
        rel = (s["stored"] - s["delta_u"]) / s["delta_u"]
        lines.append(
            f"== {key}: {s['n_steps']} stored steps; final T_oil,out {s['T_oil_out'][-1]:.3f}, "
            f"T_water,out {s['T_water_out'][-1]:.3f} K; integral(Q_oil - Q_water) dt "
            f"{s['stored']:.2f} J vs copper Delta U {s['delta_u']:.2f} J ({100 * rel:+.3f} %)"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    result = run()
    text = report(result)
    print(text)
    (HERE / "results.txt").write_text(text + "\n", encoding="utf-8")
    from figures import make_figures  # noqa: E402

    for path in make_figures(result):
        print("wrote", path)
