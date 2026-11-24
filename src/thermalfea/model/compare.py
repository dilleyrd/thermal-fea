"""What changed between the model a result was solved from and the current model (M11.58).

:func:`model_changes` is the single test of whether a result is current: it is current
exactly when the list is empty (GUI identity plan §6).

Both models are serialised (:func:`~thermalfea.model.serialize.to_json`) and normalised
first; what is left after the normalisation is compared, so a difference that no form
describes is still reported (by its section). Then each difference is *described* with
object names and form labels, in the current display units, e.g.
``"load cooling: h 750 W/(m^2 K) → 500 W/(m^2 K)"``.

Ignored by the normalisation (they never change what is computed):
the display units, the model name, the schema version, the cached tags of the selections
(the fingerprints are compared), the derived selection ``all`` and the library source of a
material.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..core import registry
from ..core.errors import ThermalFEAError
from ..core.forms import FieldSpec, FormSpec, form_for, format_value
from ..core.functions import function_from_json
from ..core.units import UnitSettings
from .bcs import Contact, Enclosure, FlowNetwork, Stream
from .geometry_ops import GEOMETRY_FAMILY
from .model import InitialCondition, Model, RegionAssignment
from .selections import ALL_SELECTION
from .serialize import TYPE_KEY, to_json
from .settings import MeshSettings, SolutionSettings

#: Top-level keys of the model JSON that never change a result.
_IGNORED = ("display_units", "name", "schema_version")
_VALUE_KINDS = ("function", "float", "int", "bool", "choice", "str")
_ARROW = " → "


def normalised(data: dict[str, Any]) -> dict[str, Any]:
    """Model JSON without what never changes a result (see the module docstring)."""
    out = {k: v for k, v in data.items() if k not in _IGNORED}
    out["selections"] = {
        name: {k: v for k, v in sel.items() if k != "tags"}
        for name, sel in data.get("selections", {}).items()
        if name != ALL_SELECTION
    }
    out["materials"] = {
        name: {k: v for k, v in mat.items() if k != "source"}
        for name, mat in data.get("materials", {}).items()
    }
    return out


def _as_json(model: Model | dict[str, Any]) -> dict[str, Any]:
    return to_json(model) if isinstance(model, Model) else model


def model_changes(
    solved: Model | dict[str, Any],
    current: Model | dict[str, Any],
    units: UnitSettings | None = None,
) -> list[str]:
    """Readable list of the differences that matter between two models.

    Parameters
    ----------
    solved, current : Model or dict
        The model a result was solved from and the current one (objects or model JSON).
    units : UnitSettings, optional
        Display units of the descriptions; by default those of ``current``.

    Returns
    -------
    list of str
        Empty exactly when the normalised models are equal.
    """
    raw = _as_json(current)
    a, b = normalised(_as_json(solved)), normalised(raw)
    if a == b:
        return []
    if units is None:
        units = current.display_units if isinstance(current, Model) else UnitSettings()
    out: list[str] = []
    for key in _ordered_keys(a, b):
        old, new = a.get(key), b.get(key)
        if old == new:
            continue
        describe = _DESCRIBERS.get(key)
        lines: list[str] = []
        if describe is not None:
            try:
                lines = describe(old, new, units)
            except (ThermalFEAError, KeyError, TypeError, ValueError, AttributeError):
                lines = []  # an unexpected shape: fall back to the section
        out += lines or [f"{_SECTION_TITLES.get(key, key)} changed"]
    return out


_SECTION_ORDER = (
    "analysis", "geometry", "selections", "materials", "regions", "mesh_settings",
    "initial_condition", "bcs", "contacts", "streams", "network", "enclosures", "solution",
)  # fmt: skip
_SECTION_TITLES = {
    "analysis": "Analysis type",
    "geometry": "Geometry",
    "selections": "Selections",
    "materials": "Materials",
    "regions": "Parts",
    "mesh_settings": "Mesh settings",
    "initial_condition": "Initial condition",
    "bcs": "Loads",
    "contacts": "Contacts",
    "streams": "Streams",
    "network": "Flow network",
    "enclosures": "Enclosures",
    "solution": "Analysis settings",
}


def _ordered_keys(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    keys = set(a) | set(b)
    first = [k for k in _SECTION_ORDER if k in keys]
    return first + sorted(keys - set(first))


# -------------------------------------------------------------------------- values
def _value_text(spec: FieldSpec | None, value: Any, units: UnitSettings) -> str | None:
    """Display text of a JSON field value, or ``None`` when it has no short form."""
    if spec is None or spec.kind not in _VALUE_KINDS:
        return None
    if value is None:
        return "none"
    if spec.kind in ("function", "float"):
        decoded = function_from_json(value) if isinstance(value, dict) else value
        return format_value(spec, decoded, units)
    if isinstance(value, (dict, list)):
        return None
    return str(value)


def _field_lines(
    owner: str, form: FormSpec | None, old: dict[str, Any], new: dict[str, Any],
    units: UnitSettings, skip: tuple[str, ...] = (),
) -> list[str]:  # fmt: skip
    """One line per differing field of two JSON objects of the same class."""
    specs = {f.name: f for f in form.fields} if form is not None else {}
    lines: list[str] = []
    for key in sorted(set(old) | set(new)):
        if key in skip or key == TYPE_KEY or old.get(key) == new.get(key):
            continue
        if key == "active":
            lines.append(f"{owner} {'unsuppressed' if new.get(key) else 'suppressed'}")
            continue
        spec = specs.get(key)
        label = spec.label if spec is not None and spec.label else key
        before, after = _value_text(spec, old.get(key), units), _value_text(
            spec, new.get(key), units
        )
        if before is not None and after is not None and before != after:
            lines.append(f"{owner}: {label} {before}{_ARROW}{after}")
        else:
            lines.append(f"{owner}: {label} changed")
    return lines


def _form_of(family: str | None, cls: type | None, item: dict[str, Any]) -> FormSpec | None:
    try:
        if family is not None:
            cls = registry.class_by_tag(family, item[TYPE_KEY])
        return form_for(cls) if cls is not None else None
    except (ThermalFEAError, KeyError):
        return None


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------- named collections
def _named(
    noun: str, family: str | None = None, cls: type | None = None
) -> Callable[[Any, Any, UnitSettings], list[str]]:
    """Describer of a list of objects that have a ``name`` (loads, contacts, ...)."""

    def describe(old: list[dict], new: list[dict], units: UnitSettings) -> list[str]:
        before = {item["name"]: item for item in old or []}
        after = {item["name"]: item for item in new or []}
        lines = _matched(noun, before, after, units, family, cls)
        if not lines and [i["name"] for i in old or []] != [i["name"] for i in new or []]:
            lines.append(f"{_plural(noun).capitalize()} reordered")
        return lines

    return describe


def _plural(noun: str) -> str:
    return noun + ("es" if noun.endswith("s") else "s")


def _matched(
    noun: str, before: dict[str, dict], after: dict[str, dict], units: UnitSettings,
    family: str | None, cls: type | None,
) -> list[str]:  # fmt: skip
    """Added, removed, renamed and changed objects of two name -> JSON maps."""
    lines: list[str] = []
    removed = [n for n in before if n not in after]
    added = [n for n in after if n not in before]
    for name in list(removed):  # an object whose only change is its name was renamed
        body = {k: v for k, v in before[name].items() if k != "name"}
        twin = next(
            (n for n in added if _same({k: v for k, v in after[n].items() if k != "name"}, body)),
            None,
        )
        if twin is not None:
            lines.append(f"Renamed {noun} {name}{_ARROW}{twin}")
            removed.remove(name)
            added.remove(twin)
    # renamed and edited: the same place in the list and the same type
    order_old, order_new = list(before), list(after)
    pairs: list[tuple[str, str]] = []
    for name in list(removed):
        place = order_old.index(name)
        twin = order_new[place] if place < len(order_new) else None
        if twin in added and before[name].get(TYPE_KEY) == after[twin].get(TYPE_KEY):
            pairs.append((name, twin))
            removed.remove(name)
            added.remove(twin)
    for name, twin in pairs:
        lines.append(f"Renamed {noun} {name}{_ARROW}{twin}")
        form = _form_of(family, cls, after[twin])
        lines += _field_lines(f"{noun.capitalize()} {twin}", form, before[name], after[twin],
                              units, ("name",))  # fmt: skip
    lines += [f"Removed {noun} {n}" for n in removed]
    lines += [f"Added {noun} {n}" for n in added]
    for name in before:
        if name in after and not _same(before[name], after[name]):
            old, new = before[name], after[name]
            if TYPE_KEY in old and old.get(TYPE_KEY) != new.get(TYPE_KEY):
                lines.append(f"{noun.capitalize()} {name}: type changed")
                continue
            form = _form_of(family, cls, new)
            lines += _field_lines(f"{noun.capitalize()} {name}", form, old, new, units, ("name",))
    return lines


def _materials(old: dict, new: dict, units: UnitSettings) -> list[str]:
    from ..materials.material import Material

    named_old = {n: {**m, "name": n} for n, m in (old or {}).items()}
    named_new = {n: {**m, "name": n} for n, m in (new or {}).items()}
    return _matched("material", named_old, named_new, units, None, Material)


def _selections(old: dict, new: dict, units: UnitSettings) -> list[str]:
    before = {n: {**s, "name": n} for n, s in (old or {}).items()}
    after = {n: {**s, "name": n} for n, s in (new or {}).items()}
    lines: list[str] = []
    removed = [n for n in before if n not in after]
    added = [n for n in after if n not in before]
    for name in list(removed):
        body = {k: v for k, v in before[name].items() if k != "name"}
        twin = next(
            (n for n in added if _same({k: v for k, v in after[n].items() if k != "name"}, body)),
            None,
        )
        if twin is not None:
            lines.append(f"Renamed selection {name}{_ARROW}{twin}")
            removed.remove(name)
            added.remove(twin)
    lines += [f"Removed selection {n}" for n in removed]
    lines += [f"Added selection {n}" for n in added]
    lines += [
        f"Selection {n} redefined"
        for n in before
        if n in after and not _same(before[n], after[n])
    ]
    return lines


def _regions(old: list, new: list, units: UnitSettings) -> list[str]:
    old, new = old or [], new or []
    form = form_for(RegionAssignment)
    lines: list[str] = []

    def title(item: dict) -> str:
        return item.get("name") or item.get("selection") or "(unnamed)"

    for a, b in zip(old, new, strict=False):
        if not _same(a, b):
            lines += _field_lines(f"Part {title(b)}", form, a, b, units)
    lines += [f"Removed part {title(a)}" for a in old[len(new):]]
    lines += [f"Added part {title(b)}" for b in new[len(old):]]
    return lines


def _geometry(old: list, new: list, units: UnitSettings) -> list[str]:
    old, new = old or [], new or []
    ids_old, ids_new = [op["id"] for op in old], [op["id"] for op in new]
    if ids_old == ids_new:
        lines: list[str] = []
        for a, b in zip(old, new, strict=True):
            if not _same(a, b):
                if a.get(TYPE_KEY) != b.get(TYPE_KEY):
                    lines.append(f"Geometry step {b['id']}: type changed")
                    continue
                form = _form_of(GEOMETRY_FAMILY, None, b)
                lines += _field_lines(f"Geometry step {b['id']}", form, a, b, units, ("id",))
        return lines
    if sorted(ids_old) == sorted(ids_new) and all(
        _same(a, next(b for b in new if b["id"] == a["id"])) for a in old
    ):
        return ["Geometry steps reordered"]
    before = {op["id"]: {**op, "name": op["id"]} for op in old}
    after = {op["id"]: {**op, "name": op["id"]} for op in new}
    return _matched("geometry step", before, after, units, GEOMETRY_FAMILY, None) or [
        "Geometry changed"
    ]


def _settings(owner: str, cls: type) -> Callable[[Any, Any, UnitSettings], list[str]]:
    def describe(old: dict, new: dict, units: UnitSettings) -> list[str]:
        return _field_lines(owner, form_for(cls), old or {}, new or {}, units)

    return describe


def _analysis(old: Any, new: Any, units: UnitSettings) -> list[str]:
    return [f"Analysis type: {old}{_ARROW}{new}"]


def _network(old: Any, new: Any, units: UnitSettings) -> list[str]:
    if old is None:
        return ["Added flow network"]
    if new is None:
        return ["Removed flow network"]
    return _field_lines("Flow network", form_for(FlowNetwork), old, new, units)


_DESCRIBERS: dict[str, Callable[[Any, Any, UnitSettings], list[str]]] = {
    "analysis": _analysis,
    "geometry": _geometry,
    "selections": _selections,
    "materials": _materials,
    "regions": _regions,
    "mesh_settings": _settings("Mesh", MeshSettings),
    "initial_condition": _settings("Initial condition", InitialCondition),
    "solution": _settings("Analysis settings", SolutionSettings),
    "bcs": _named("load", family=registry.BC_FAMILY),
    "contacts": _named("contact", cls=Contact),
    "streams": _named("stream", cls=Stream),
    "enclosures": _named("enclosure", cls=Enclosure),
    "network": _network,
}
