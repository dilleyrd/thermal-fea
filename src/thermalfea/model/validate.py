"""Validation of a model before solving (Data §8).

``validate(model, built, mesh)`` returns a list of :class:`Issue` records. Errors block
the solve; warnings do not. Each issue names the object it concerns so the GUI can select
it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from ..core.errors import ModelError
from ..core.forms import form_for
from ..core.functions import Constant, Function, Table
from ..core.mesh import Mesh
from ..materials import library
from ..materials.material import Material
from .bcs import (
    Convection,
    CorrelationConvection,
    FixedTemperature,
    HeatFlow,
    HeatPower,
    RadiationAmbient,
    Stream,
    diameter_ratio_problem,
    inclination_problem,
    power_law_problem,
)
from .model import Model
from .selections import StaleSelectionError, resolve
from .vocabulary import entity_word

if TYPE_CHECKING:  # the builder imports gmsh; this module must not (Plan §3)
    from ..geometry.builder import BuiltGeometry

log = logging.getLogger(__name__)

#: The user power law h = C |dT|^n needs no fluid properties.
NO_FLUID = "power_law"
INCLINED = "inclined_natural"
AXIS_TOL = 1e-9  # axisymmetric: nodes may lie this fraction of L left of the axis
SURFACE_DIM, CURVE_DIM, POINT_DIM = 2, 1, 0
_INTERFACE_SIDES = 2


@dataclass(frozen=True)
class Issue:
    """One finding of the validation.

    Attributes
    ----------
    severity : {"error", "warning"}
        Errors block the solve.
    code : str
        Stable identifier of the check, e.g. ``"stale-selection"``.
    message : str
        Explanation for the user.
    kind : str
        Kind of the object concerned: ``"model"``, ``"selection"``, ``"region"``,
        ``"material"``, ``"bc"``, ``"stream"``, ``"contact"``, ``"mesh"``, ``"solution"``.
    name : str
        Name of that object (empty for the model as a whole).
    """

    severity: Literal["error", "warning"]
    code: str
    message: str
    kind: str = "model"
    name: str = ""


def errors(issues: Iterable[Issue]) -> list[Issue]:
    """Return the issues that block the solve."""
    return [i for i in issues if i.severity == "error"]


def raise_if_errors(issues: Iterable[Issue]) -> None:
    """Raise :class:`ModelError` listing every error, if there is any."""
    found = errors(issues)
    if found:
        text = "\n".join(f"- {i.message}" for i in found)
        raise ModelError(f"the model has {len(found)} error(s):\n{text}")


# ---------------------------------------------------------------------------- helpers


#: Where a located value is evaluated: points [m] as an (n, 2) array, ``None`` if unknown.
Locator = Callable[["Iterable[str] | None"], "np.ndarray | None"]


def _sample_times(model: Model, fn: Function, over_run: bool) -> list[float]:
    """Times at which a function is evaluated (Q28.5, Q29).

    A function without time dependence is sampled at t = 0. A steady model uses the steady
    time. A transient model uses the function's breakpoints inside [0, end_time] plus the
    start and the end; an expression of t exposes no breakpoints, so it is sampled at t = 0
    and at end_time only.
    """
    from ..solver.steady import STEADY_TIME  # lazy: keep the model layer light

    if not fn.depends_on_time or not over_run:
        return [0.0]
    if model.solution.kind != "transient":
        return [STEADY_TIME]
    end = float(model.solution.end_time)
    if not end > 0.0:
        return [0.0]
    inside = [float(b) for b in fn.breakpoints() if 0.0 <= b <= end]
    return sorted({0.0, end, *inside})


def _sample(
    fn: Function | None,
    points: np.ndarray | None = None,
    times: Iterable[float] = (0.0,),
) -> list[float] | None:
    """Smallest and largest value of a function over the sample points and times.

    Returns ``None`` (unknown) if the function depends on temperature, or if it depends on
    position and no points are available. Otherwise one value if the extremes coincide,
    else ``[min, max]``.
    """
    if fn is None or fn.depends_on_T:
        return None
    x: np.ndarray | float = 0.0
    y: np.ndarray | float = 0.0
    if fn.depends_on_position:
        if points is None or len(points) == 0:
            return None
        x, y = points[:, 0], points[:, 1]
    values = np.concatenate([np.asarray(fn(t=t, x=x, y=y), dtype=float).ravel() for t in times])
    lo, hi = float(np.min(values)), float(np.max(values))
    return [lo] if lo == hi else [lo, hi]


def _values(fn: Function, lo: float, hi: float) -> list[float]:
    """Values of a property sampled over the temperature range [lo, hi]."""
    if isinstance(fn, Table) and fn.variable == "T":
        inside = [y for x, y in zip(fn.xs, fn.ys, strict=True) if lo <= x <= hi]
        return [*inside, float(fn(T=lo)), float(fn(T=hi))]
    return [float(v) for v in np.asarray(fn(T=np.linspace(lo, hi, 11))).ravel()]


def _extremes(fn: Function, lo: float, hi: float) -> tuple[float, float]:
    """Smallest and largest value of a property over the temperature range [lo, hi].

    ``(nan, nan)`` when some sampled value is not finite (``min`` alone would ignore a NaN
    depending on its position).
    """
    values = _values(fn, lo, hi)
    if not all(np.isfinite(values)):
        return float("nan"), float("nan")
    return min(values), max(values)


def _fluid_known(name: object) -> bool:
    """True when the library knows the fluid, whatever the case of its name."""
    try:
        library.fluid(name)  # type: ignore[arg-type]
    except (ModelError, AttributeError):
        return False
    return True


def _selection_dims(bc: object) -> tuple[int, ...]:
    """Geometry dimensions the selection of a load may have, from its registered form."""
    try:
        spec = form_for(type(bc))
    except ModelError:
        return (POINT_DIM, CURVE_DIM, SURFACE_DIM)
    for field in spec.fields:
        if field.name == "selection" and field.selection_dims:
            return tuple(field.selection_dims)
    return (POINT_DIM, CURVE_DIM, SURFACE_DIM)


def _known_temperatures(
    model: Model, locate: Locator | None = None
) -> list[tuple[float, str, str]]:
    """Temperatures the model states explicitly: (value [K], kind, name).

    ``locate(selection names)`` gives the points a load applies to (``None`` names: the
    whole domain). A varying value contributes its smallest and its largest value.
    """
    where: Locator = locate or (lambda _names: None)
    found: list[tuple[float, str, str]] = []

    def add(fn: Function | None, names: Iterable[str] | None, kind: str, name: str,
            over_run: bool = True) -> None:
        if fn is None or fn.depends_on_T:
            return
        values = _sample(fn, where(names), _sample_times(model, fn, over_run))
        found.extend((v, kind, name) for v in values or [])

    for bc in model.bcs:
        if not bc.active:
            continue
        for attr in ("T", "T_inf"):
            if hasattr(bc, attr):
                add(getattr(bc, attr), [bc.selection], "bc", bc.name)
    for stream in model.streams:
        add(stream.T_inlet, list(stream.walls), "stream", stream.name)
    for enclosure in model.enclosures:
        add(enclosure.T_ambient, [s.selection for s in enclosure.surfaces], "enclosure",
            enclosure.name)
    ic = model.initial_condition
    if model.solution.kind == "transient":
        if ic.kind in ("uniform", "expression"):
            add(ic.value, None, "model", "initial condition", over_run=False)
        for region, value in (ic.per_region or {}).items():
            found.append((float(value), "model", f"initial condition of {region}"))
    return found


class _Checker:
    def __init__(self, model: Model, built: BuiltGeometry | None, mesh: Mesh | None) -> None:
        self.model, self.built, self.mesh = model, built, mesh
        self.issues: list[Issue] = []
        self.tags: dict[str, list[int]] = {}

    def error(self, code: str, message: str, kind: str = "model", name: str = "") -> None:
        self.issues.append(Issue("error", code, message, kind, name))

    def warning(self, code: str, message: str, kind: str = "model", name: str = "") -> None:
        self.issues.append(Issue("warning", code, message, kind, name))

    # --------------------------------------------------------------------- selections

    def selections(self) -> None:
        """No stale selection; remember the current tags of the good ones."""
        if self.built is None:
            return
        for name, selection in self.model.selections.items():
            try:
                self.tags[name] = resolve(selection, self.built)
            except StaleSelectionError as exc:
                self.error("stale-selection", str(exc), "selection", name)

    def _use(self, name: str, dims: tuple[int, ...], kind: str, owner: str) -> list[int] | None:
        """Tags of a selection used by ``owner``, reporting unknown or wrong ones."""
        selection = self.model.selections.get(name)
        if selection is None:
            self.error("unknown-selection", f"{kind} {owner!r} refers to unknown selection "
                       f"{name!r}", kind, owner)
            return None
        if selection.dim not in dims:
            geometry = {0: "", 1: " (curves)", 2: " (surfaces)"}
            wanted = " or ".join(
                entity_word(d, self.model, plural=True) + geometry[d] for d in dims
            )
            self.error("wrong-selection", f"{kind} {owner!r} needs a selection of {wanted}, "
                       f"but {name!r} is not", kind, owner)
            return None
        tags = self.tags.get(name)  # None when stale (already reported) or not built
        if tags is not None and not tags:
            self.error("empty-selection", f"{kind} {owner!r} uses selection {name!r}, which "
                       "contains no geometry", kind, owner)
        return tags

    # ------------------------------------------------------------------------ regions

    def regions(self) -> None:
        """Every surface has exactly one region assignment; materials and fluids exist."""
        model = self.model
        owners: dict[int, list[str]] = (
            {tag: [] for tag in self.built.surfaces} if self.built is not None else {}
        )
        for region in model.regions:
            tags = self._use(region.selection, (SURFACE_DIM,), "region", region.selection)
            for tag in tags or []:
                owners.setdefault(tag, []).append(region.selection)
            if region.material not in model.materials:
                self.error("missing-material", f"region {region.selection!r} uses material "
                           f"{region.material!r}, which is not in the model",
                           "region", region.selection)
            if model.analysis == "planar" and not region.thickness > 0.0:
                self.error("bad-thickness", f"region {region.selection!r} has a non-positive "
                           "thickness", "region", region.selection)
        for tag, names in owners.items():
            assert self.built is not None
            centre = self.built.surfaces[tag].center
            where = f"surface {tag} (centre {centre[0]:.4g}, {centre[1]:.4g})"
            if not names:
                self.error("no-region", f"{where} has no region assignment (no material)",
                           "region", "")
            elif len(names) > 1:
                self.error("multiple-regions", f"{where} is assigned by more than one region: "
                           f"{', '.join(map(repr, names))}", "region", names[-1])

        for bc in model.bcs:
            needs_fluid = isinstance(bc, CorrelationConvection) and bc.correlation != NO_FLUID
            # an empty fluid is reported as "empty-fluid" (bc_values), not as unknown here
            if needs_fluid and bc.active and bc.fluid and not _fluid_known(bc.fluid):
                self.error("missing-fluid", f"boundary condition {bc.name!r} uses unknown "
                           f"fluid {bc.fluid!r}", "bc", bc.name)
        for stream in model.streams:
            if not _fluid_known(stream.fluid):
                self.error("missing-fluid", f"stream {stream.name!r} uses unknown fluid "
                           f"{stream.fluid!r}", "stream", stream.name)
            message = diameter_ratio_problem(stream)
            if message:
                self.error("stream-diameter-ratio", f"stream {stream.name!r}: {message}",
                           "stream", stream.name)

    # ------------------------------------------------------------ boundary conditions

    def boundary_conditions(self) -> None:
        """Selections of the BCs; no curve carries two fixed temperatures; unique names."""
        fixed_on: dict[int, list[str]] = {}
        names = [bc.name for bc in self.model.bcs]
        for name in sorted({n for n in names if names.count(n) > 1}):
            self.error("duplicate-name", f"more than one boundary condition is called "
                       f"{name!r}", "bc", name)
        for bc in self.model.bcs:
            if not bc.active:
                continue
            is_fixed = isinstance(bc, FixedTemperature)
            tags = self._use(bc.selection, _selection_dims(bc), "boundary condition", bc.name)
            selection = self.model.selections.get(bc.selection)
            if is_fixed and tags and selection is not None and selection.dim == CURVE_DIM:
                for tag in tags:
                    fixed_on.setdefault(tag, []).append(bc.name)
        for tag, names in fixed_on.items():
            if len(names) > 1:
                self.error("double-fixed-temperature", f"curve {tag} carries more than one "
                           f"fixed temperature: {', '.join(map(repr, names))}", "bc", names[-1])

    def bc_values(self) -> None:
        """Values of the loads: total loads, correlation inputs, velocity."""
        model = self.model
        for bc in model.bcs:
            if not bc.active:
                continue
            if isinstance(bc, (HeatPower, HeatFlow)) and bc.P.depends_on_position:
                what, instead = (
                    ("power", "Heat Generation") if isinstance(bc, HeatPower)
                    else ("heat flow", "Heat Flux")
                )
                self.error("position-dependent-total", f"boundary condition {bc.name!r}: a "
                           f"total {what} is spread uniformly, so it may depend on time only; "
                           f"use {instead} for a value that varies with position", "bc", bc.name)
            if isinstance(bc, (CorrelationConvection, RadiationAmbient)):
                self._unset_values(bc)
            if not isinstance(bc, CorrelationConvection):
                continue
            if bc.correlation == INCLINED and "theta_deg" in bc.params:
                message = inclination_problem(bc.params["theta_deg"])
                if message:
                    self.error("bad-inclination", f"boundary condition {bc.name!r}: {message}",
                               "bc", bc.name)
            if bc.correlation == NO_FLUID and "C" in bc.params and "n" in bc.params:
                message = power_law_problem(bc.params["C"], bc.params["n"])
                if message:
                    self.error("bad-power-law", f"boundary condition {bc.name!r}: {message}",
                               "bc", bc.name)
            if bc.velocity is not None:
                values = _sample(bc.velocity, self.points_of([bc.selection]),
                                 _sample_times(model, bc.velocity, True))
                if values is not None and not values[0] >= 0.0:
                    self.error("negative-velocity", f"boundary condition {bc.name!r}: the "
                               f"velocity must not be negative; got {values[0]:g} m/s",
                               "bc", bc.name)

    def _unset_values(self, bc: CorrelationConvection | RadiationAmbient) -> None:
        """Blank or zero inputs a new load can be left with (Q26.4(d), Q27.2).

        Errors for an empty correlation or fluid (the fluid is not needed by the user power
        law); warnings for an ambient temperature or an emissivity that is the constant 0.
        """
        who = f"boundary condition {bc.name!r}"
        if isinstance(bc, CorrelationConvection):
            if not bc.correlation:
                self.error("empty-correlation", f"{who} has no correlation; choose one",
                           "bc", bc.name)
            if bc.correlation != NO_FLUID and not bc.fluid:
                self.error("empty-fluid", f"{who} has no fluid; choose one", "bc", bc.name)
        if isinstance(bc.T_inf, Constant) and bc.T_inf.value == 0.0:
            self.warning("zero-ambient", f"{who} has an ambient temperature of 0 K; was it "
                         "left unset?", "bc", bc.name)
        if isinstance(bc, RadiationAmbient) and (
            isinstance(bc.emissivity, Constant) and bc.emissivity.value == 0.0
        ):
            self.warning("zero-emissivity", f"{who} has an emissivity of 0, so it radiates "
                         "nothing; was it left unset?", "bc", bc.name)

    def temperature_reference(self) -> None:
        """A steady analysis needs something that fixes the temperature level."""
        model = self.model
        if model.solution.kind != "steady":
            return
        reference = (FixedTemperature, Convection, CorrelationConvection, RadiationAmbient)
        # an in-plane stream fixes its inlet; a through-plane stream is convection to its bulk
        has = any(bc.active and isinstance(bc, reference) for bc in model.bcs) or bool(
            model.streams
        )
        if not has:
            self.error("no-temperature-reference", "a steady analysis needs at least one "
                       "temperature reference (a fixed temperature, convection, radiation or "
                       "a stream); without one the temperature level is undetermined")

    def points_of(self, names: Iterable[str] | None) -> np.ndarray | None:
        """Points [m] of the selections (``None``: the whole domain), or ``None`` if unknown.

        Mesh nodes of the curves (or of the whole mesh) when the mesh is given, else the
        sampled curve polylines or the geometric points themselves. Only points that lie
        on the entities are used: a surface, or the whole domain without a mesh, has no
        such points here and is unknown (Q28.5), because the corners of a bounding box can
        lie outside the shape and give a temperature that does not occur.
        """
        built, mesh = self.built, self.mesh
        if names is None:
            return np.asarray(mesh.nodes)[:, :2] if mesh is not None else None
        chunks: list[np.ndarray] = []
        for name in names:
            selection = self.model.selections.get(name)
            tags = self.tags.get(name)
            if selection is None or not tags:
                return None
            if mesh is not None and selection.dim == CURVE_DIM:
                for block in mesh.facets_on(tags):
                    chunks.append(np.asarray(mesh.nodes)[np.unique(block.conn), :2])
                continue
            assert built is not None  # tags exist only for a built model
            for tag in tags:
                if selection.dim == CURVE_DIM and tag in built.curve_polylines:
                    chunks.append(np.asarray(built.curve_polylines[tag])[:, :2])
                    continue
                fp = built.entities(selection.dim).get(tag)
                if selection.dim != POINT_DIM or fp is None:
                    return None  # no points on the entity itself: unknown
                chunks.append(np.asarray(fp.center[:2], dtype=float).reshape(1, 2))
        return np.vstack(chunks) if chunks else None

    def absolute_temperatures(self) -> list[tuple[float, str, str]]:
        """With radiation, every temperature must be absolute (> 0 K)."""
        model = self.model
        known = _known_temperatures(model, self.points_of)
        radiation = any(bc.active and isinstance(bc, RadiationAmbient) for bc in model.bcs) or bool(
            model.enclosures
        )
        if radiation:
            for value, kind, name in known:
                if value <= 0.0:
                    self.error("non-absolute-temperature", f"{name!r} has a temperature of "
                               f"{value:g} K. Radiation needs absolute temperatures; was a "
                               "value in degrees Celsius entered as kelvin?", kind, name)
        return known

    # ---------------------------------------------------------------------- materials

    def materials(self, known: list[tuple[float, str, str]]) -> None:
        """Transient: rho and cp positive, end time positive; tables cover the range."""
        model = self.model
        used = {r.material for r in model.regions if r.material in model.materials}
        temps = [v for v, _, _ in known if v > 0.0]
        lo, hi = (min(temps), max(temps)) if temps else (None, None)
        transient = model.solution.kind == "transient"
        if transient and not model.solution.end_time > 0.0:
            self.error("bad-end-time", "a transient analysis needs an end time greater than 0",
                       "solution", "")
        for name in sorted(used):
            material = model.materials[name]
            a, b = (lo, hi) if lo is not None else (300.0, 300.0)
            props = (("conductivity", material.k), ("second conductivity", material.k2),
                     ("density", material.rho), ("specific heat", material.cp))
            finite = True
            for label, fn in props:
                if fn is None:
                    continue
                if fn.depends_on_time or fn.depends_on_position:
                    self.error("material-not-temperature-only", f"material {name!r}: the "
                               f"{label} may depend on temperature only (it uses t, x or y)",
                               "material", name)
                if not all(np.isfinite(_values(fn, a, b))):
                    finite = False
                    self.error("non-finite-property", f"material {name!r} has a {label} that "
                               "is not finite (NaN or infinite) at some temperature",
                               "material", name)
            if not finite:
                continue
            if _extremes(material.k, a, b)[0] <= 0.0 or (
                material.k2 is not None and _extremes(material.k2, a, b)[0] <= 0.0
            ):
                self.error("bad-conductivity", f"material {name!r} has a conductivity that "
                           "is not positive", "material", name)
            if transient:
                for label, fn in (("density", material.rho), ("specific heat", material.cp)):
                    if _extremes(fn, a, b)[0] <= 0.0:
                        self.error("bad-capacity", f"material {name!r} has a {label} that is "
                                   "not positive; a transient analysis needs rho and cp > 0",
                                   "material", name)
            if lo is not None:
                self._table_range(material, lo, hi)

    def _table_range(self, material: Material, lo: float, hi: float) -> None:
        props = {"k": material.k, "k2": material.k2, "rho": material.rho, "cp": material.cp}
        for label, fn in props.items():
            if isinstance(fn, Table) and fn.variable == "T" and (
                fn.xs[0] > lo or fn.xs[-1] < hi
            ):
                outside = "held" if fn.extrapolate == "hold" else "extrapolated"
                self.warning("table-range", f"the {label} table of material "
                             f"{material.name!r} covers {fn.xs[0]:g} to {fn.xs[-1]:g} K, but "
                             f"the model's temperatures span {lo:g} to {hi:g} K; values "
                             f"outside the table are {outside}", "material", material.name)

    # ------------------------------------------------------------------- time stepping

    def time_stepping(self) -> None:
        """Step sizes and tolerances are positive (NaN is not).

        The time-step settings are read by the transient solver only, so they are checked
        for a transient analysis only; the nonlinear tolerances are used by both kinds.
        """
        s = self.model.solution
        if s.kind == "transient":
            if not s.dt_min > 0.0:
                self.error("bad-time-step", f"the smallest time step (dt_min) must be greater "
                           f"than 0; got {s.dt_min:g}", "solution", "")
            if s.initial_dt is not None and not s.initial_dt > 0.0:
                self.error("bad-time-step", f"the first time step (initial_dt) must be greater "
                           f"than 0; got {s.initial_dt:g}", "solution", "")
            if s.dt_max is not None:
                if not s.dt_max > 0.0:
                    self.error("bad-time-step", f"the largest time step (dt_max) must be greater "
                               f"than 0; got {s.dt_max:g}", "solution", "")
                elif s.dt_max < s.dt_min:
                    self.error("bad-time-step", f"the largest time step (dt_max = {s.dt_max:g} "
                               f"s) is below the smallest (dt_min = {s.dt_min:g} s)",
                               "solution", "")
            if not s.time_tol > 0.0:
                self.error("bad-time-step", f"the time-step tolerance (time_tol) must be greater "
                           f"than 0; got {s.time_tol:g}", "solution", "")
            if s.max_dT_per_step is not None and not s.max_dT_per_step > 0.0:
                self.error("bad-time-step", f"the largest temperature change per step "
                           f"(max_dT_per_step) must be greater than 0; got "
                           f"{s.max_dT_per_step:g}", "solution", "")
        for name in ("rtol", "ttol"):
            value = getattr(s, name)
            if not value > 0.0:
                self.error("bad-tolerance", f"the nonlinear tolerance {name} must be greater "
                           f"than 0; got {value:g}", "solution", "")

    # ----------------------------------------------------------------- mesh, contacts

    def axis(self) -> None:
        """Axisymmetric: no node left of the axis."""
        if self.mesh is None or not self.model.axisymmetric:
            return
        if self.built is not None:
            diagonal = self.built.diagonal
        else:
            nodes = np.asarray(self.mesh.nodes)[:, :2]
            diagonal = float(np.linalg.norm(nodes.max(axis=0) - nodes.min(axis=0)))
        limit = -AXIS_TOL * diagonal
        n = int(np.count_nonzero(self.mesh.nodes[:, 0] < limit))
        if n:
            self.error("negative-radius", f"{n} node(s) have a negative radius (x < 0). In an "
                       "axisymmetric model x is the radius; move the geometry to x >= 0",
                       "mesh", "")

    def contacts(self, known: list[tuple[float, str, str]]) -> None:
        """A contact curve is an interface between two regions; its conductance is positive."""
        names = [c.name for c in self.model.contacts]
        for name in sorted({n for n in names if names.count(n) > 1}):
            self.error("duplicate-name", f"more than one contact is called {name!r}",
                       "contact", name)
        temps = [v for v, _, _ in known if v > 0.0]
        lo, hi = (min(temps), max(temps)) if temps else (300.0, 300.0)
        for contact in self.model.contacts:
            tags = self._use(contact.selection, (CURVE_DIM,), "contact", contact.name)
            fn = contact.conductance
            if fn.depends_on_T:
                values: list[float] | None = _values(fn, lo, hi)
            else:
                values = _sample(fn, self.points_of([contact.selection]),
                                 _sample_times(self.model, fn, True))
            if values is not None and not (all(np.isfinite(values)) and min(values) > 0.0):
                self.error("bad-conductance", f"contact {contact.name!r} has a conductance "
                           "that is not positive and finite", "contact", contact.name)
            if self.built is None:
                continue
            for tag in tags or []:
                n = len(self.built.curve_surfaces.get(tag, []))
                if n != _INTERFACE_SIDES:
                    self.error("contact-not-interface", f"contact {contact.name!r}: curve "
                               f"{tag} borders {n} region(s); a contact must lie between "
                               "exactly two", "contact", contact.name)

    # ------------------------------------------------------------- streams and network

    def streams(self) -> None:
        """Streams: walls, geometry, multipliers, path, temperature-only inputs, mass flow."""
        model = self.model
        names = [s.name for s in model.streams]
        for name in sorted({n for n in names if names.count(n) > 1}):
            self.error("duplicate-name", f"more than one stream is called {name!r}",
                       "stream", name)
        on_network = {b.stream for b in model.network.branches if b.stream} if (
            model.network is not None
        ) else set()
        for stream in model.streams:
            who = f"stream {stream.name!r}"

            def bad(code: str, message: str, stream: Stream = stream, who: str = who) -> None:
                self.error(code, f"{who}: {message}", "stream", stream.name)

            for wall in stream.walls:
                self._use(wall, (CURVE_DIM,), "stream", stream.name)
            if not (np.isfinite(stream.flow_area) and stream.flow_area > 0.0
                    and np.isfinite(stream.wetted_perimeter) and stream.wetted_perimeter > 0.0):
                bad("bad-stream-geometry", "the flow area and the wetted perimeter must be "
                    "positive and finite")
            if not (np.isfinite(stream.h_multiplier) and stream.h_multiplier > 0.0):
                bad("bad-stream-multiplier", "h_multiplier must be positive")
            if not (np.isfinite(stream.roughness) and stream.roughness >= 0.0):
                bad("bad-stream-roughness", "the roughness must not be negative")
            if stream.n_cells is not None and not stream.n_cells >= 1:
                bad("bad-stream-cells", "n_cells must be at least 1 (or empty for one cell "
                    "per wall edge)")
            if stream.mode == "in_plane" and (not stream.path or len(stream.path) < 2):
                bad("bad-stream-path", "an in-plane stream needs a path of at least two points")
            if stream.T_inlet.depends_on_T:
                bad("stream-temperature-dependence", "the inlet temperature cannot depend on T")
            if stream.h_override is not None and stream.h_override.depends_on_T:
                bad("stream-temperature-dependence", "h_override may depend on time only")
            flow = stream.mass_flow
            if flow is not None and flow.depends_on_T:
                bad("stream-temperature-dependence", "the mass flow may depend on time only")
            elif flow is not None:
                values = _sample(flow, None, _sample_times(model, flow, True))
                if values is not None and not values[0] > 0.0:
                    bad("bad-mass-flow", f"the mass flow must be positive; got {values[0]:g} "
                        "kg/s (reverse the path for flow in the other direction)")
            elif stream.name not in on_network and not (
                stream.mode == "through_plane" and stream.h_override is not None
            ):
                bad("stream-no-mass-flow", "it has no mass flow: give one, or attach the "
                    "stream to a network branch")

    def network(self) -> None:
        """The flow network: the structural checks of the hydraulic solve."""
        net = self.model.network
        if net is None or not net.branches:
            return
        from ..flow.network import network_problems  # lazy: keeps the model layer light

        for ident, message in network_problems(net.nodes, net.branches, self.model.streams):
            self.error("bad-network", message, "network", ident)

    def initial_condition(self) -> None:
        """A transient analysis has a complete initial condition."""
        model = self.model
        if model.solution.kind != "transient":
            return
        ic = model.initial_condition
        who = "initial condition"

        def bad(message: str) -> None:
            self.error("bad-initial-condition", f"the {who}: {message}", "model", who)

        if ic.kind in ("uniform", "expression"):
            if ic.value is None:
                bad(f"'{ic.kind}' needs a value")
            elif ic.value.depends_on_T:
                bad("an initial temperature cannot depend on T")
        elif ic.kind == "per_region":
            if not ic.per_region:
                bad("'per_region' needs a temperature per region")
            else:
                regions = {r.selection for r in model.regions}
                for key, value in ic.per_region.items():
                    if key not in regions:
                        bad(f"'{key}' is not a region of the model")
                    if not np.isfinite(float(value)):
                        bad(f"the temperature of region '{key}' is not finite")
        elif not ic.results_path:
            bad("'from_results' needs a results file")


def not_implemented(model: Model) -> list[tuple[str, str, str]]:
    """Parts of a model that this version cannot solve: ``(kind, name, message)``.

    The model classes and the file format already hold surface-to-surface radiation
    enclosures (tasks M9) and phase change (task M10.2), but no solver term exists for
    them yet. Solving such a model would silently leave them out, so it is refused.
    """
    found: list[tuple[str, str, str]] = []
    for enclosure in model.enclosures:
        found.append((
            "enclosure", enclosure.name,
            f"enclosure {enclosure.name!r}: surface-to-surface radiation is not available "
            "in this version; remove the enclosure (radiation to ambient is available as a "
            "boundary condition)",
        ))
    used = {assignment.material for assignment in model.regions}
    for name in sorted(used):
        material = model.materials.get(name)
        if material is not None and material.phase_change is not None:
            found.append((
                "material", name,
                f"material {name!r} has a phase change, which is not available in this "
                "version; remove the phase change from the material",
            ))
    return found


def _run(check: _Checker) -> list[Issue]:
    """Run the checks in order; the ones that need a built geometry skip themselves."""
    for kind, name, message in not_implemented(check.model):
        check.error("not-implemented", message, kind, name)
    check.selections()
    check.regions()
    check.boundary_conditions()
    check.bc_values()
    check.temperature_reference()
    known = check.absolute_temperatures()
    check.materials(known)
    check.time_stepping()
    check.streams()
    check.network()
    check.initial_condition()
    check.axis()
    check.contacts(known)
    for issue in check.issues:
        log.debug("validation %s [%s]: %s", issue.severity, issue.code, issue.message)
    return check.issues


def validate(model: Model, built: BuiltGeometry, mesh: Mesh | None = None) -> list[Issue]:
    """Check a model before solving.

    Parameters
    ----------
    model : Model
    built : BuiltGeometry
        The current build of the model.
    mesh : Mesh, optional
        The mesh; checks that need it are skipped when it is ``None``.

    Returns
    -------
    list of Issue
        Errors (which block the solve) and warnings, in the order of the checks.
    """
    return _run(_Checker(model, built, mesh))


def validate_model(model: Model, mesh: Mesh | None = None) -> list[Issue]:
    """Checks that need only the model (and the mesh, if given): Data §8.

    Skipped: stale and empty selections, the surface coverage by regions, the contact
    interface check and the points of selections (so a value that varies with position is
    not sampled). The axis check uses the bounding box of the mesh.
    """
    return _run(_Checker(model, None, mesh))
