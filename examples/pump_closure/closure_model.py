"""Axisymmetric model of the main closure of a canned-motor pump (demonstration).

Builds the r-z section of sheets 2-4 of ``AP1000_Closure_Thermal_Sketches.pdf`` from the
inputs in ``closure.json``: casing, thermal barrier with its cooling passage, main flange
with the composite stud band G, the area-equivalent stud ring D and nut ring N, and the
stator shell S and liner L below the flange. Two parallel heat paths run from the casing
into the flange: across the seated joint faces (seal land, main seat, barrier foot), and
from the casing lip down the studs to the nuts and back into the flange underside.

Every number comes from ``closure.json``. The only arithmetic here is what the sheets
prescribe: mm to m, degC to K, the ring widths from 2 pi R w = N pi d^2 / 4 (sheet 4),
and the mixing rules of the stud band G (sheet 4).

Use :func:`build_model` to get a model ready to mesh, and :func:`contact_heats` /
:func:`metrics` to post-process its results.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from thermalfea import api
from thermalfea.core.functions import Constant, Table
from thermalfea.core.mesh import Mesh
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.materials import library
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Adiabatic, Contact, Convection
from thermalfea.model.model import InitialCondition, Model
from thermalfea.model.selections import Fingerprint
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.results import Results
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.problem import CompiledProblem
from thermalfea.solver.terms import State

HERE = Path(__file__).resolve().parent
PARAMS = HERE / "closure.json"
MM = 1.0e-3  # m per mm
KELVIN = 273.15  # K at 0 degC
TOL = 1.0e-6  # m; geometric tolerance when selecting entities

#: Solid bodies, in the order they are drawn. Each becomes one region.
BODIES = (
    "casing", "barrier", "stud", "nut", "flange_inner", "flange_band", "flange_outer",
    "shell", "liner",
)  # fmt: skip

#: Contact name -> (body heat leaves, body heat enters) for the sign of the reported heat.
CONTACT_SIDES = {
    "main_seat": ("casing", "flange_inner"),
    "seal_land": ("casing", "flange_inner"),
    "barrier_foot": ("barrier", "flange_inner"),
    "vertical_fit": ("casing", "barrier"),
    "stud_anchor": ("casing", "stud"),
    "nut_bearing": ("nut", "flange_band"),
}

#: Boundary-condition names of the fluid sets of sheet 3.
FILMS = ("H", "M", "Cw", "J", "A")

Point = tuple[float, float]


def load_params(path: str | Path = PARAMS) -> dict[str, Any]:
    """Read the inputs (mm, degC, W/(m^2 K), s)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class Layout:
    """Key dimensions [m] derived from the inputs."""

    stud_w: float  # width of the area-equivalent stud ring
    stud_r0: float
    stud_r1: float
    stud_top: float
    nut_w: float  # width of the combined nut/stud-end ring
    nut_r0: float
    nut_r1: float
    nut_z0: float
    band_fraction: float  # stud area fraction f of the band G


def layout(p: dict[str, Any]) -> Layout:
    """Ring widths from 2 pi R w = N pi d^2 / 4 (sheet 4)."""
    g = p["geometry"]
    studs, nut, flange = g["studs"], g["nut"], g["flange"]
    n, radius = studs["count"], studs["bolt_circle_r"]
    stud_w = n * studs["shank_diameter"] ** 2 / (8.0 * radius)
    nut_w = n * nut["equivalent_od"] ** 2 / (8.0 * radius)
    band = flange["band_r_out"] - flange["band_r_in"]
    bottom = -flange["thickness"]
    return Layout(
        stud_w=stud_w * MM,
        stud_r0=(radius - stud_w / 2) * MM,
        stud_r1=(radius + stud_w / 2) * MM,
        stud_top=studs["grip"] * MM,
        nut_w=nut_w * MM,
        nut_r0=(radius - nut_w / 2) * MM,
        nut_r1=(radius + nut_w / 2) * MM,
        nut_z0=(bottom - nut["height"]) * MM,
        band_fraction=stud_w / band,
    )


# ------------------------------------------------------------------------------ geometry


def _draw(model: Model, p: dict[str, Any], lay: Layout) -> dict[str, tuple[float, ...]]:
    """Append the geometry operations; return the bounding box [m] of every body."""
    g = p["geometry"]
    geo = api.Geometry(model)
    boxes: dict[str, tuple[float, ...]] = {}

    def rect(name: str, r0: float, z0: float, r1: float, z1: float) -> None:
        geo.rectangle(r0, z0, r1 - r0, z1 - z0, id=name)
        boxes[name] = (r0, z0, r1, z1)

    # casing: the seat face (685,0)->(550,0) gets a vertex at the seal-land edge, so the
    # seal land and the main seat are separate curves
    casing = [(r * MM, z * MM) for r, z in g["casing_vertices"]]
    casing.append((g["seal_land_r_out"] * MM, 0.0))
    geo.polygon(casing, id="casing")
    rs, zs = [v[0] for v in casing], [v[1] for v in casing]
    boxes["casing"] = (min(rs), min(zs), max(rs), max(zs))

    b = g["barrier"]
    top, under = b["top_z"] * MM, (b["top_z"] - b["web_thickness"]) * MM
    bore, s_in, s_out = b["bore_r"] * MM, b["skirt_r_in"] * MM, b["skirt_r_out"] * MM
    geo.polygon(
        [(bore, under), (bore, top), (s_out, top), (s_out, 0.0), (s_in, 0.0), (s_in, under)],
        id="barrier_solid",
    )
    c = g["passage"]
    geo.circle(c["r"] * MM, c["z"] * MM, c["diameter"] / 2 * MM, id="passage")
    geo.cut(["barrier_solid"], ["passage"], id="barrier")
    boxes["barrier"] = (bore, 0.0, s_out, top)

    f = g["flange"]
    bottom = -f["thickness"] * MM
    rect("flange_inner", f["r_in"] * MM, bottom, f["band_r_in"] * MM, 0.0)
    rect("flange_band", f["band_r_in"] * MM, bottom, f["band_r_out"] * MM, 0.0)
    rect("flange_outer", f["band_r_out"] * MM, bottom, f["r_out"] * MM, 0.0)

    low = bottom - g["extension_below_flange"] * MM
    rect("liner", g["liner"]["r_in"] * MM, low, g["liner"]["r_out"] * MM, bottom)
    rect("shell", g["shell"]["r_in"] * MM, low, g["shell"]["r_out"] * MM, bottom)
    rect("stud", lay.stud_r0, 0.0, lay.stud_r1, lay.stud_top)
    rect("nut", lay.nut_r0, lay.nut_z0, lay.nut_r1, bottom)
    return boxes


def _box_is(fp: Fingerprint, box: Sequence[float]) -> bool:
    xmin, ymin, _, xmax, ymax, _ = fp.bbox
    return all(abs(a - b) < TOL for a, b in zip((xmin, ymin, xmax, ymax), box, strict=True))


def _on_segment(fp: Fingerprint, a: Point, b: Point) -> bool:
    """True when a straight curve lies on the segment a-b."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    cx, cy = fp.center[0], fp.center[1]
    if abs((cx - ax) * dy - (cy - ay) * dx) / length > TOL:
        return False
    xmin, ymin, _, xmax, ymax, _ = fp.bbox
    inside = (
        xmin >= min(ax, bx) - TOL and xmax <= max(ax, bx) + TOL
        and ymin >= min(ay, by) - TOL and ymax <= max(ay, by) + TOL
    )  # fmt: skip
    straight = abs(fp.measure - math.hypot(xmax - xmin, ymax - ymin)) < 1e3 * TOL
    return inside and straight


def _select_segments(
    model: Model, built: BuiltGeometry, name: str, segments: Sequence[tuple[Point, Point]]
) -> None:
    """Select the curves covering a list of segments [m]; check that they cover them."""
    sel = api.select_curves(
        model, built, name, where=lambda fp: any(_on_segment(fp, a, b) for a, b in segments)
    )
    want = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segments)
    got = sum(fp.measure for fp in sel.fingerprints)
    if abs(got - want) > 1e3 * TOL:
        raise RuntimeError(f"selection {name!r} covers {got:.6f} m of {want:.6f} m")


def _select(model: Model, built: BuiltGeometry, p: dict[str, Any], lay: Layout,
            boxes: dict[str, tuple[float, ...]]) -> None:  # fmt: skip
    """Name the bodies, the fluid-wetted sets of sheet 3 and the contacts of sheet 4."""
    for name in BODIES:
        api.select_surfaces(model, built, name, where=lambda fp, n=name: _box_is(fp, boxes[n]))

    g = p["geometry"]

    def m(r: float, z: float) -> Point:
        return (r * MM, z * MM)

    b, f = g["barrier"], g["flange"]
    under = b["top_z"] - b["web_thickness"]
    cas = g["casing_vertices"]
    bot = -f["thickness"]
    low = bot - g["extension_below_flange"]
    seal = g["seal_land_r_out"]
    lip = g["studs"]["grip"]
    s0, s1 = lay.stud_r0 / MM, lay.stud_r1 / MM
    n0, n1, nz = lay.nut_r0 / MM, lay.nut_r1 / MM, lay.nut_z0 / MM

    sets: dict[str, list[tuple[Point, Point]]] = {
        # H: barrier top and inner edge, then the sloping casing wall
        "H": [(m(b["bore_r"], under), m(b["bore_r"], b["top_z"])),
              (m(b["bore_r"], b["top_z"]), m(b["skirt_r_out"], b["top_z"])),
              (m(*cas[1]), m(*cas[2])), (m(*cas[2]), m(*cas[3]))],
        # M: barrier underside and skirt ID, flange ledge and bore, liner ledge and bore
        "M": [(m(b["bore_r"], under), m(b["skirt_r_in"], under)),
              (m(b["skirt_r_in"], under), m(b["skirt_r_in"], 0)),
              (m(f["r_in"], 0), m(b["skirt_r_in"], 0)),
              (m(f["r_in"], bot), m(f["r_in"], 0)),
              (m(g["liner"]["r_in"], bot), m(f["r_in"], bot)),
              (m(g["liner"]["r_in"], low), m(g["liner"]["r_in"], bot))],
        # J: shell OD
        "J": [(m(g["shell"]["r_out"], low), m(g["shell"]["r_out"], bot))],
        # A: casing OD, lip underside, casing face in the stud cavity, flange top, OD and
        # underside (the stud foot and the nut bearing face are not exposed)
        "A": [(m(*cas[4]), m(*cas[5])), (m(*cas[5]), m(*cas[6])), (m(*cas[6]), m(*cas[7])),
              (m(*cas[8]), m(s0, lip)), (m(s1, lip), m(*cas[7])),
              (m(*cas[9]), m(*cas[8])),
              (m(cas[9][0], 0), m(s0, 0)), (m(s1, 0), m(f["r_out"], 0)),
              (m(f["r_out"], bot), m(f["r_out"], 0)),
              (m(g["shell"]["r_out"], bot), m(n0, bot)), (m(n1, bot), m(f["r_out"], bot))],
        # X: truncation planes (zero axial flux)
        "X": [(m(*cas[3]), m(*cas[4])), (m(g["liner"]["r_in"], low), m(g["shell"]["r_out"], low))],
        # insulated for this run: stud shank sides, nut sides and base
        "insulated": [(m(s0, 0), m(s0, lip)), (m(s1, 0), m(s1, lip)),
                      (m(n0, nz), m(n0, bot)), (m(n1, nz), m(n1, bot)), (m(n0, nz), m(n1, nz))],
        # contacts (sheet 4)
        "main_seat": [(m(seal, 0), m(*cas[9]))],
        "seal_land": [(m(*cas[0]), m(seal, 0))],
        "barrier_foot": [(m(b["skirt_r_in"], 0), m(b["skirt_r_out"], 0))],
        "vertical_fit": [(m(*cas[0]), m(*cas[1]))],
        "stud_anchor": [(m(s0, lip), m(s1, lip))],
        "nut_bearing": [(m(n0, bot), m(n1, bot))],
    }  # fmt: skip
    for name, segments in sets.items():
        _select_segments(model, built, name, segments)

    c = g["passage"]
    centre, radius = m(c["r"], c["z"]), c["diameter"] / 2 * MM
    api.select_curves(
        model, built, "Cw",
        where=lambda fp: math.dist(fp.center[:2], centre) < TOL
        and abs(fp.measure - 2 * math.pi * radius) < 1e3 * TOL,
    )  # fmt: skip
    # curves that get the fine element size: stud, nut, seal land, passage
    fine = [model.selections[n].tags for n in ("insulated", "stud_anchor", "nut_bearing",
                                               "seal_land", "Cw")]  # fmt: skip
    api.select_curves(model, built, "fine", tags=sorted({t for tags in fine for t in tags}))


# ----------------------------------------------------------------------------- materials


def _value(material: Material, prop: str) -> float:
    fn = getattr(material, prop)
    if not isinstance(fn, Constant):
        raise RuntimeError(f"{material.name}: {prop} is not a constant; the band mix needs one")
    return float(fn.value)


def band_material(flange: Material, stud: Material, f: float) -> Material:
    """Composite band G (sheet 4): filled-bore mix of flange and stud metal.

    k_axial = (1 - f) k_flange + f k_stud and k_radial = (1 - f) k_flange; density and
    volumetric heat capacity are mixed separately, then divided to get the specific heat.
    The material axis is x (= r), so ``k`` is radial and ``k2`` axial.
    """
    k_f, k_s = _value(flange, "k"), _value(stud, "k")
    rho_f, rho_s = _value(flange, "rho"), _value(stud, "rho")
    rc = (1 - f) * rho_f * _value(flange, "cp") + f * rho_s * _value(stud, "cp")
    rho = (1 - f) * rho_f + f * rho_s
    return Material(
        "Flange band G", k=(1 - f) * k_f, rho=rho, cp=rc / rho, k2=(1 - f) * k_f + f * k_s
    )


# ---------------------------------------------------------------------------------- model


def build_model(
    p: dict[str, Any] | None = None,
    kind: str = "transient",
    seat_factor: float = 1.0,
    mesh_factor: float = 1.0,
) -> tuple[Model, BuiltGeometry]:
    """Build the closure model.

    Parameters
    ----------
    p : dict, optional
        Inputs (default: ``closure.json``).
    kind : {"transient", "steady"}
        Transient heat-up (H ramps from T_start to T_end) or steady hot case (H at T_end).
    seat_factor : float
        Factor on the main-seat contact conductance (study of sheet 5).
    mesh_factor : float
        Factor on both element sizes (0.5 halves them).
    """
    p = load_params() if p is None else p
    lay = layout(p)
    label = f"pump closure, {kind}" + (f", seat x{seat_factor:g}" if seat_factor != 1 else "")
    model = api.new_model("axisymmetric", name=label)
    boxes = _draw(model, p, lay)
    built = api.build(model)
    _select(model, built, p, lay, boxes)

    mats = p["materials"]
    body_steel = library.solid(mats["bodies"])
    stud_steel = library.solid(mats["studs_and_nuts"])
    liner_steel = library.solid(mats["liner"])
    band = band_material(body_steel, stud_steel, lay.band_fraction)
    for m in (body_steel, stud_steel, liner_steel, band):
        model.materials[m.name] = m
    for name in BODIES:
        material = {"stud": stud_steel, "nut": stud_steel, "flange_band": band,
                    "liner": liner_steel}.get(name, body_steel)  # fmt: skip
        api.assign_region(model, name, material=material.name)

    fl = p["fluids"]
    hot = fl["H"]
    if kind == "transient":
        T_hot = Table([0.0, float(hot["ramp_time"])],
                      [hot["T_start"] + KELVIN, hot["T_end"] + KELVIN], "t")  # fmt: skip
    else:
        T_hot = Constant(hot["T_end"] + KELVIN)
    model.bcs.append(Convection("H", "H", h=hot["h"], T_inf=T_hot))
    for name in ("M", "Cw", "J", "A"):
        model.bcs.append(Convection(name, name, h=fl[name]["h"], T_inf=fl[name]["T"] + KELVIN))
    model.bcs.append(Adiabatic("truncation planes", "X"))
    model.bcs.append(Adiabatic("stud and nut sides", "insulated"))

    for name, h in p["contacts"].items():
        scale = seat_factor if name == "main_seat" else 1.0
        model.contacts.append(Contact(name, name, conductance=h * scale))

    ms = p["mesh"]
    settings = model.mesh_settings
    settings.global_size = ms["global_size"] * MM * mesh_factor
    settings.order = ms["order"]
    settings.curve_sizes = {"fine": ms["fine_size"] * MM * mesh_factor}

    model.initial_condition = InitialCondition("uniform", value=Constant(p["initial_T"] + KELVIN))
    if kind == "transient":
        run = p["run"]
        end, step = float(run["end_time"]), float(run["output_interval"])
        model.solution = SolutionSettings(
            kind="transient", end_time=end, initial_dt=float(run["initial_dt"]),
            output="times", output_times=list(np.arange(step, end + step / 2, step)),
        )  # fmt: skip
    else:
        model.solution = SolutionSettings(kind="steady")
    return model, built


# ------------------------------------------------------------------------ post-processing


class ContactHeats:
    """Heat crossing each contact [W], signed by :data:`CONTACT_SIDES`.

    The results do not store the heat across a contact, so it is evaluated here from the
    stored temperatures with the solver's own contact terms.
    """

    def __init__(self, model: Model, built: BuiltGeometry, mesh: Mesh) -> None:
        from thermalfea.physics.contact import ContactTerm

        self.problem: CompiledProblem = compile_problem(model, built, mesh)
        self.terms = {t.name: t for t in self.problem.terms if isinstance(t, ContactTerm)}
        opened = self.problem.mesh
        node_region = np.full(opened.n_nodes, -1)
        for block in opened.blocks:
            node_region[block.conn] = block.region[:, None]
        body_of = {tag: name for name in BODIES for tag in model.selections[name].tags}
        self.sign: dict[str, float] = {}
        for name, term in self.terms.items():
            batch, _ = term._sides[0]
            side_a = body_of[int(np.bincount(node_region[batch.conn.ravel()]).argmax())]
            source, sink = CONTACT_SIDES[name]
            if side_a not in (source, sink):
                raise RuntimeError(f"contact {name!r}: side A is {side_a!r}")
            self.sign[name] = 1.0 if side_a == source else -1.0

    def __call__(self, T: np.ndarray, t: float) -> dict[str, float]:
        """Heat [W] from the first to the second body of each contact at one state."""
        if T.size != self.problem.dofs.n_dofs:
            raise RuntimeError("results and compiled problem have different DOF counts")
        s = State(u=T, u_prev=T, t=t, dt=None, dofs=self.problem.dofs)
        return {n: self.sign[n] * term.heat_across(s) for n, term in self.terms.items()}


def _mean_on(nodes: np.ndarray, T: np.ndarray, r: float | None = None,
             z: tuple[float, float] | None = None,
             rr: tuple[float, float] | None = None) -> float:  # fmt: skip
    x, y = nodes[:, 0], nodes[:, 1]
    mask = np.ones(len(nodes), dtype=bool)
    if r is not None:
        mask &= np.abs(x - r) < TOL
    if rr is not None:
        mask &= (x > rr[0] - TOL) & (x < rr[1] + TOL)
    if z is not None:
        mask &= (y > z[0] - TOL) & (y < z[1] + TOL)
    if not mask.any():
        raise RuntimeError("no nodes in the requested range")
    return float(T[mask].mean())


def metrics(p: dict[str, Any], results: Results, step: int,
            heats: ContactHeats) -> dict[str, float]:  # fmt: skip
    """Comparison quantities of sheet 5 at one stored step.

    Temperatures in degC (means of the nodal values along an edge or over a body), heat
    in W (whole ring, 2 pi r included).
    """
    lay = layout(p)
    f = p["geometry"]["flange"]
    nodes = results.mesh.nodes
    T = results.temperature(step)
    t = float(results.times[step])
    bot = -f["thickness"] * MM
    bore = _mean_on(nodes, T, r=f["r_in"] * MM, z=(bot, 0.0))
    rim = _mean_on(nodes, T, r=f["r_out"] * MM, z=(bot, 0.0))
    stud = _mean_on(nodes, T, rr=(lay.stud_r0, lay.stud_r1), z=(0.0, lay.stud_top))
    out = {
        "time_s": t,
        "flange_bore_C": bore - KELVIN,
        "flange_rim_C": rim - KELVIN,
        "bore_to_rim_dT_K": bore - rim,
        "stud_mean_C": stud - KELVIN,
    }
    for name, q in heats(T, t).items():
        out[f"Q_{name}_W"] = q
    for name in FILMS:
        out[f"Q_film_{name}_W"] = float(results.heat_flow(name)[step])
    out["relative_imbalance"] = float(results.energy_balance()["relative_imbalance"][step])
    return out
