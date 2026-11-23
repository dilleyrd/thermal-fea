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
from ..core.functions import Function, Table
from ..core.mesh import Mesh
from ..materials import library
from ..materials.material import Material
from .bcs import (
    Convection,
    CorrelationConvection,
    FixedTemperature,
    RadiationAmbient,
)
from .model import Model
from .selections import StaleSelectionError, resolve

if TYPE_CHECKING:  # the builder imports gmsh; this module must not (Plan §3)
    from ..geometry.builder import BuiltGeometry

log = logging.getLogger(__name__)

#: The user power law h = C |dT|^n needs no fluid properties.
NO_FLUID = "power_law"
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
    else ``[min, max]``. Position dependence is read from an expression's variable names
    (the Function protocol has no such flag yet, M11.23).
    """
    if fn is None or fn.depends_on_T:
        return None
    x: np.ndarray | float = 0.0
    y: np.ndarray | float = 0.0
    if frozenset(getattr(fn, "_names", ())) & {"x", "y"}:
        if points is None or len(points) == 0:
            return None
        x, y = points[:, 0], points[:, 1]
    values = np.concatenate([np.asarray(fn(t=t, x=x, y=y), dtype=float).ravel() for t in times])
    lo, hi = float(np.min(values)), float(np.max(values))
    return [lo] if lo == hi else [lo, hi]


def _extremes(fn: Function, lo: float, hi: float) -> tuple[float, float]:
    """Smallest and largest value of a property over the temperature range [lo, hi]."""
    if isinstance(fn, Table) and fn.variable == "T":
        inside = [y for x, y in zip(fn.xs, fn.ys, strict=True) if lo <= x <= hi]
        values = [*inside, float(fn(T=lo)), float(fn(T=hi))]
    else:
        values = [float(v) for v in np.asarray(fn(T=np.linspace(lo, hi, 11))).ravel()]
    return min(values), max(values)


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
    def __init__(self, model: Model, built: BuiltGeometry, mesh: Mesh | None) -> None:
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
            wanted = " or ".join({0: "points", 1: "curves", 2: "surfaces"}[d] for d in dims)
            self.error("wrong-selection", f"{kind} {owner!r} needs a selection of {wanted}, "
                       f"but {name!r} is not", kind, owner)
            return None
        return self.tags.get(name)  # None when stale (already reported)

    # ------------------------------------------------------------------------ regions

    def regions(self) -> None:
        """Every surface has exactly one region assignment; materials and fluids exist."""
        model = self.model
        owners: dict[int, list[str]] = {tag: [] for tag in self.built.surfaces}
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
            centre = self.built.surfaces[tag].center
            where = f"surface {tag} (centre {centre[0]:.4g}, {centre[1]:.4g})"
            if not names:
                self.error("no-region", f"{where} has no region assignment (no material)",
                           "region", "")
            elif len(names) > 1:
                self.error("multiple-regions", f"{where} is assigned by more than one region: "
                           f"{', '.join(map(repr, names))}", "region", names[-1])

        fluids = library.fluids()
        for bc in model.bcs:
            needs_fluid = isinstance(bc, CorrelationConvection) and bc.correlation != NO_FLUID
            if needs_fluid and bc.active and bc.fluid not in fluids:
                self.error("missing-fluid", f"boundary condition {bc.name!r} uses unknown "
                           f"fluid {bc.fluid!r}", "bc", bc.name)
        for stream in model.streams:
            if stream.fluid not in fluids:
                self.error("missing-fluid", f"stream {stream.name!r} uses unknown fluid "
                           f"{stream.fluid!r}", "stream", stream.name)

    # ------------------------------------------------------------ boundary conditions

    def boundary_conditions(self) -> None:
        """Selections of the BCs; no curve carries two fixed temperatures."""
        fixed_on: dict[int, list[str]] = {}
        for bc in self.model.bcs:
            if not bc.active:
                continue
            is_fixed = isinstance(bc, FixedTemperature)
            tags = self._use(bc.selection, (0, 1, 2) if not is_fixed else (0, 1),
                             "boundary condition", bc.name)
            selection = self.model.selections.get(bc.selection)
            if is_fixed and tags and selection is not None and selection.dim == CURVE_DIM:
                for tag in tags:
                    fixed_on.setdefault(tag, []).append(bc.name)
        for tag, names in fixed_on.items():
            if len(names) > 1:
                self.error("double-fixed-temperature", f"curve {tag} carries more than one "
                           f"fixed temperature: {', '.join(map(repr, names))}", "bc", names[-1])

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
        limit = -AXIS_TOL * self.built.diagonal
        n = int(np.count_nonzero(self.mesh.nodes[:, 0] < limit))
        if n:
            self.error("negative-radius", f"{n} node(s) have a negative radius (x < 0). In an "
                       "axisymmetric model x is the radius; move the geometry to x >= 0",
                       "mesh", "")

    def contacts(self) -> None:
        """A contact curve is an interface between exactly two regions."""
        for contact in self.model.contacts:
            tags = self._use(contact.selection, (CURVE_DIM,), "contact", contact.name)
            for tag in tags or []:
                n = len(self.built.curve_surfaces.get(tag, []))
                if n != _INTERFACE_SIDES:
                    self.error("contact-not-interface", f"contact {contact.name!r}: curve "
                               f"{tag} borders {n} region(s); a contact must lie between "
                               "exactly two", "contact", contact.name)


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
    check = _Checker(model, built, mesh)
    for kind, name, message in not_implemented(model):
        check.error("not-implemented", message, kind, name)
    check.selections()
    check.regions()
    check.boundary_conditions()
    check.temperature_reference()
    known = check.absolute_temperatures()
    check.materials(known)
    check.time_stepping()
    check.axis()
    check.contacts()
    for issue in check.issues:
        log.debug("validation %s [%s]: %s", issue.severity, issue.code, issue.message)
    return check.issues
