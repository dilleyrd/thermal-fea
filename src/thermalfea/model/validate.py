"""Validation of a model before solving (Data §8).

``validate(model, built, mesh)`` returns a list of :class:`Issue` records. Errors block
the solve; warnings do not. Each issue names the object it concerns so the GUI can select
it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
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
SURFACE_DIM, CURVE_DIM = 2, 1
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


def _sample(fn: Function | None) -> float | None:
    """Value of a function at t = 0 if it does not depend on temperature, else ``None``."""
    if fn is None or fn.depends_on_T:
        return None
    return float(np.max(np.asarray(fn(t=0.0))))


def _extremes(fn: Function, lo: float, hi: float) -> tuple[float, float]:
    """Smallest and largest value of a property over the temperature range [lo, hi]."""
    if isinstance(fn, Table) and fn.variable == "T":
        inside = [y for x, y in zip(fn.xs, fn.ys, strict=True) if lo <= x <= hi]
        values = [*inside, float(fn(T=lo)), float(fn(T=hi))]
    else:
        values = [float(v) for v in np.asarray(fn(T=np.linspace(lo, hi, 11))).ravel()]
    return min(values), max(values)


def _known_temperatures(model: Model) -> list[tuple[float, str, str]]:
    """Temperatures the model states explicitly: (value [K], kind, name)."""
    found: list[tuple[float, str, str]] = []
    for bc in model.bcs:
        if not bc.active:
            continue
        for attr in ("T", "T_inf"):
            value = _sample(getattr(bc, attr, None)) if hasattr(bc, attr) else None
            if value is not None:
                found.append((value, "bc", bc.name))
    for stream in model.streams:
        value = _sample(stream.T_inlet)
        if value is not None:
            found.append((value, "stream", stream.name))
    for enclosure in model.enclosures:
        value = _sample(enclosure.T_ambient)
        if value is not None:
            found.append((value, "enclosure", enclosure.name))
    ic = model.initial_condition
    if model.solution.kind == "transient":
        if ic.kind in ("uniform", "expression") and (value := _sample(ic.value)) is not None:
            found.append((value, "model", "initial condition"))
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

    def absolute_temperatures(self) -> list[tuple[float, str, str]]:
        """With radiation, every temperature must be absolute (> 0 K)."""
        model = self.model
        known = _known_temperatures(model)
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
    check.selections()
    check.regions()
    check.boundary_conditions()
    check.temperature_reference()
    known = check.absolute_temperatures()
    check.materials(known)
    check.axis()
    check.contacts()
    for issue in check.issues:
        log.debug("validation %s [%s]: %s", issue.severity, issue.code, issue.message)
    return check.issues
