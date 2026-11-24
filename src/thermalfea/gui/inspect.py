"""What is on one geometry entity: the report behind hover and inspect (M11.60).

:func:`entity_report` answers "what is this?" for an entity ``(dim, tag)`` of the current
build: its role (part, boundary, point; :mod:`thermalfea.model.vocabulary`), the named
selections that contain it, everything that uses those selections (loads and contacts,
suppressed ones marked, streams, mesh settings, parts) and every part it belongs to or
touches (an interface boundary touches two). Nothing here draws; the hover tooltip and the
Inspect panel (M11.61) only format the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thermalfea.core.errors import ModelError
from thermalfea.gui.document import Document
from thermalfea.model.selections import StaleSelectionError, resolve, selection_users
from thermalfea.model.vocabulary import domain_dim, entity_word


@dataclass
class EntityUse:
    """One object acting on the entity through a selection."""

    address: tuple
    label: str
    selection: str
    suppressed: bool = False


@dataclass
class EntityReport:
    """Everything known about one entity of the current build.

    Attributes
    ----------
    dim, tag : int
        The entity.
    role : str
        "part", "boundary", "edge" or "point" ("" when the dimension has no role).
    title : str
        e.g. ``"Boundary 6"``.
    built : bool
        ``False`` when there is no current build (the lists are then empty).
    selections : list of str
        Named selections containing the entity (``all`` included).
    uses : list of EntityUse
        Users of those selections.
    parts : list of tuple
        ``(address, label)`` of every part the entity belongs to or bounds.
    """

    dim: int
    tag: int
    role: str
    title: str
    built: bool = True
    selections: list[str] = field(default_factory=list)
    uses: list[EntityUse] = field(default_factory=list)
    parts: list[tuple[tuple, str]] = field(default_factory=list)

    def addresses(self) -> list[tuple]:
        """Tree addresses of everything in the report (for marking the tree)."""
        out: list[tuple] = [("selections", name) for name in self.selections]
        out += [u.address for u in self.uses]
        out += [address for address, _ in self.parts]
        return list(dict.fromkeys(out))

    def lines(self) -> list[str]:
        """The report as text lines (tooltip and panel)."""
        if not self.built:
            return [self.title, "the geometry is not built"]
        out = [self.title]
        if self.parts:
            out.append("part: " + ", ".join(label for _, label in self.parts))
        named = [s for s in self.selections if s != "all"]
        out.append("in: " + (", ".join(named) if named else "no named selection"))
        acting = [u for u in self.uses if u.address[0] in ("bcs", "contacts", "streams")]
        for use in acting:
            out.append(use.label + (" (suppressed)" if use.suppressed else ""))
        return out


def _part_label(region: object) -> str:
    return getattr(region, "name", "") or getattr(region, "selection", "")


def entity_report(document: Document, dim: int, tag: int) -> EntityReport:
    """Report on the entity ``(dim, tag)`` of the document's current build.

    Parameters
    ----------
    document : Document
    dim, tag : int
        A geometry entity (point, curve or surface today).

    Returns
    -------
    EntityReport
        With ``built`` False and empty lists when there is no current build.
    """
    model = document.model
    try:
        role = entity_word(dim, model)
    except ModelError:
        role = ""
    title = f"{role.capitalize() or 'Entity'} {tag}"
    built = document.built
    if built is None or document.geometry_stale:
        return EntityReport(dim, tag, role, title, built=False)
    report = EntityReport(dim, tag, role, title)

    resolved: dict[str, tuple[int, list[int]]] = {}
    for name, selection in model.selections.items():
        try:
            resolved[name] = (int(selection.dim), resolve(selection, built))
        except StaleSelectionError:
            continue
        if resolved[name][0] == dim and tag in resolved[name][1]:
            report.selections.append(name)

    for name in report.selections:
        for use in selection_users(model, name):
            if use.address[0] == "regions":
                continue  # parts are listed by geometry below, with every part touched
            suppressed = use.address[0] == "bcs" and not model.bcs[use.address[1]].active
            report.uses.append(EntityUse(use.address, use.label, name, suppressed))

    surfaces = _surfaces_touching(built, dim, tag, domain_dim(model))
    for i, region in enumerate(model.regions):
        found = resolved.get(region.selection)
        if found is not None and set(found[1]) & surfaces:
            report.parts.append((("regions", i), _part_label(region)))
    return report


def _surfaces_touching(built, dim: int, tag: int, top: int) -> set[int]:
    """Tags of the domain entities the entity is, bounds, or ends a boundary of."""
    if dim == top:
        return {tag}
    if dim == top - 1:
        return set(built.curve_surfaces.get(tag, []))
    if dim == 0:
        return {
            surface
            for curve in built.point_curves.get(tag, [])
            for surface in built.curve_surfaces.get(curve, [])
        }
    return set()
