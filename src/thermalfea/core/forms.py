"""Form metadata of model classes (Plan M8.4): what a property panel needs, without Qt.

A :class:`FormSpec` describes the editable fields of one dataclass (a boundary condition,
mesh settings, ...). The GUI generates its panels from it, so a class registered with
:func:`thermalfea.core.registry.register_bc` gets a panel without any GUI code.

``form_for(cls)`` returns the spec registered for a class (``register_bc(..., form=...)``
for boundary conditions, :func:`register_form` for other classes) or derives one from the
dataclass fields and type hints. A field may carry hints in its ``metadata``::

    h: Function = field(metadata={"label": "Film coefficient", "quantity": "htc"})

Recognised keys: ``label``, ``quantity``, ``minimum``, ``maximum``, ``tooltip``, ``kind``,
``choices``, ``selection_dims``. The fields ``name`` and ``active`` are never part of a
form: the model tree renames and suppresses objects.
"""

from __future__ import annotations

import dataclasses
import re
import types
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from . import registry
from .errors import ModelError
from .functions import Constant, Function
from .units import QUANTITIES, UnitSettings, from_si, to_si
from .units import unit_label as unit_label  # re-exported: forms and panels import it here

FieldKind = Literal[
    "float", "int", "bool", "str", "choice", "function", "selection", "selection_list", "dict",
    "str_list", "str_lists", "xy_list", "float_list",
]
FIELD_KINDS: tuple[str, ...] = (
    "float", "int", "bool", "str", "choice", "function", "selection", "selection_list", "dict",
    "str_list", "str_lists", "xy_list", "float_list",
)

#: Fields every object has that a form never shows.
EXCLUDED_FIELDS = ("name", "active")

@dataclass(frozen=True)
class FieldSpec:
    """One editable field of a form.

    Parameters
    ----------
    name : str
        Attribute name on the edited object.
    label : str
        Text shown beside the editor.
    kind : {"float", "int", "bool", "str", "choice", "function", "selection", \
"selection_list", "dict"}
        Which editor is used. ``selection`` is the name of a model selection,
        ``selection_list`` a list of such names, ``dict`` a ``{str: float}`` mapping,
        ``str_list`` a list of words (``"a, b"``), ``str_lists`` a list of such lists
        (``"a, b; c, d"``), ``xy_list`` a list of ``(x, y)`` pairs (``"0,0; 1,0"``) and
        ``float_list`` a list of numbers (``"0.5, 1, 2"``).
    quantity : str, optional
        Quantity of :data:`thermalfea.core.units.QUANTITIES` for unit conversion (the
        value is stored in SI, shown in display units); ``None`` for none/dimensionless.
    minimum, maximum : float, optional
        Inclusive limits of the SI value (numbers and constant functions).
    choices : tuple, optional
        Allowed values of a ``choice`` field (``None`` is a legal entry).
    optional : bool
        The value may be ``None``.
    tooltip : str
        Help text.
    selection_dims : tuple of int, optional
        Geometry dimensions a selection field accepts (0 point, 1 curve, 2 surface);
        ``None`` allows any.
    """

    name: str
    label: str
    kind: str
    quantity: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple | None = None
    optional: bool = False
    tooltip: str = ""
    selection_dims: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ModelError(f"field {self.name!r}: unknown form kind {self.kind!r}")
        if self.quantity is not None and self.quantity not in QUANTITIES:
            raise ModelError(f"field {self.name!r}: unknown quantity {self.quantity!r}")
        if self.kind == "choice" and not self.choices:
            raise ModelError(f"field {self.name!r}: a choice field needs choices")


def _convert_value(spec: FieldSpec, value: Any, convert: Any) -> Any:
    """Apply ``convert(number)`` to the numbers of a field value of a quantity."""
    if spec.quantity is None or value is None:
        return value
    if spec.kind == "dict":
        return {k: float(convert(float(v))) for k, v in value.items()}
    if spec.kind == "float_list":
        return [float(convert(float(v))) for v in value]
    if spec.kind == "xy_list":
        return [(float(convert(float(x))), float(convert(float(y)))) for x, y in value]
    return float(convert(float(value)))


def to_display(spec: FieldSpec, value: Any, settings: UnitSettings) -> Any:
    """Convert a stored (SI) field value to display units.

    Works for ``float`` and ``int`` values and for the numbers inside ``dict`` (values),
    ``float_list`` and ``xy_list`` (both columns) fields of a quantity; a field without a
    quantity, and ``None``, are returned unchanged.
    """
    quantity = spec.quantity
    return _convert_value(spec, value, lambda v: from_si(v, quantity, settings))  # type: ignore[arg-type]


def from_display(spec: FieldSpec, value: Any, settings: UnitSettings) -> Any:
    """Convert a field value typed in display units to SI (inverse of :func:`to_display`)."""
    quantity = spec.quantity
    return _convert_value(spec, value, lambda v: to_si(v, quantity, settings))  # type: ignore[arg-type]


@dataclass
class FormSpec:
    """The form of one class.

    Parameters
    ----------
    title : str
        Human name of the class ("Convection"); used for menus, default object names and
        panel headings.
    fields : list of FieldSpec
    category : str
        Group of the class; ``"load"`` for boundary conditions.
    description : str
        One-line help text.
    """

    title: str
    fields: list[FieldSpec]
    category: str = "load"
    description: str = ""

    def field(self, name: str) -> FieldSpec:
        """Return the spec of the named field."""
        for spec in self.fields:
            if spec.name == name:
                return spec
        raise KeyError(name)


_FORMS: dict[type, FormSpec] = {}


def register_form(cls: type, spec: FormSpec) -> None:
    """Register the form of a class that is not a boundary condition."""
    _FORMS[cls] = spec


def format_str_list(value: list[str] | None) -> str:
    """Text ``"a, b"`` of a list of words."""
    return ", ".join(value or [])


def parse_str_list(text: str) -> list[str]:
    """Parse ``"a, b"`` (commas or semicolons) into a list of words; empty items are dropped."""
    return [w.strip() for w in text.replace(";", ",").split(",") if w.strip()]


def format_str_lists(value: list[list[str]] | None) -> str:
    """Text ``"a, b; c, d"`` of a list of word lists."""
    return "; ".join(format_str_list(v) for v in (value or []))


def parse_str_lists(text: str) -> list[list[str]]:
    """Parse ``"a, b; c, d"`` into a list of word lists; empty groups are dropped."""
    groups = (parse_str_list(g) for g in text.split(";"))
    return [g for g in groups if g]


def format_xy_list(value: list[tuple[float, float]] | None) -> str:
    """Text ``"0,0; 1,0.5"`` of a list of coordinate pairs."""
    return "; ".join(f"{x:.10g}, {y:.10g}" for x, y in (value or []))


def parse_xy_list(text: str) -> list[tuple[float, float]]:
    """Parse ``"0,0; 1,0.5"`` into coordinate pairs.

    Raises
    ------
    ValueError
        If an item is not two numbers.
    """
    out: list[tuple[float, float]] = []
    for item in text.split(";"):
        if not item.strip():
            continue
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 2:  # noqa: PLR2004
            raise ValueError(f"{item.strip()!r} is not 'x, y'")
        try:
            out.append((float(parts[0]), float(parts[1])))
        except ValueError:
            raise ValueError(f"{item.strip()!r} is not 'x, y' with numbers") from None
    return out


def format_float_list(value: list[float] | None) -> str:
    """Text ``"0.5, 1, 2"`` of a list of numbers."""
    return ", ".join(f"{v:.10g}" for v in (value or []))


def parse_float_list(text: str) -> list[float]:
    """Parse ``"0.5, 1, 2"`` (commas or semicolons) into numbers.

    Raises
    ------
    ValueError
        If an item is not a finite number.
    """
    out: list[float] = []
    for item in text.replace(";", ",").split(","):
        if not item.strip():
            continue
        try:
            value = float(item)
        except ValueError:
            raise ValueError(f"{item.strip()!r} is not a number") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{item.strip()!r} is not a finite number")
        out.append(value)
    return out


def _title(cls: type) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cls.__name__)


def _unwrap(hint: Any) -> tuple[Any, bool]:
    """Return ``(hint without None, optional)``."""
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(hint) if a is not type(None)]
        optional = len(args) != len(get_args(hint))
        if len(args) == 1:
            return args[0], optional
        return hint, optional
    return hint, False


def _derive_field(f: dataclasses.Field, hint: Any) -> FieldSpec | None:
    meta = dict(f.metadata)
    base, optional = _unwrap(hint)
    kind: str | None = None
    choices: tuple | None = None
    if base is Function:
        kind = "function"
    elif base is bool:
        kind = "bool"
    elif base is int:
        kind = "int"
    elif base is float:
        kind = "float"
    elif base is str:
        kind = "selection" if f.name == "selection" else "str"
    elif get_origin(base) is Literal:
        kind, choices = "choice", tuple(get_args(base))
        if optional:
            choices += (None,)
    elif get_origin(base) is dict and get_args(base)[:1] == (str,):
        kind = "dict"
    elif get_origin(base) is list and get_args(base) == (str,):
        kind = "selection_list" if "wall" in f.name or "selection" in f.name else None
    kind = meta.get("kind", kind)
    if kind is None:
        return None
    return FieldSpec(
        name=f.name,
        label=meta.get("label", f.name.replace("_", " ").capitalize()),
        kind=kind,
        quantity=meta.get("quantity"),
        minimum=meta.get("minimum"),
        maximum=meta.get("maximum"),
        choices=meta.get("choices", choices),
        optional=optional,
        tooltip=meta.get("tooltip", ""),
        selection_dims=meta.get("selection_dims"),
    )


def derive_form(cls: type) -> FormSpec:
    """Derive a form from the fields and type hints of a dataclass.

    Fields whose type has no editor (lists of numbers, nested objects, ...) are left out.
    """
    if not dataclasses.is_dataclass(cls):
        raise ModelError(f"{cls.__name__} is not a dataclass")
    try:
        hints = get_type_hints(cls)
    except Exception:  # unresolvable annotation: fall back to the raw ones
        hints = {f.name: f.type for f in dataclasses.fields(cls)}
    specs = []
    for f in dataclasses.fields(cls):
        if not f.init or f.name in EXCLUDED_FIELDS or f.name.startswith("_"):
            continue
        spec = _derive_field(f, hints.get(f.name, f.type))
        if spec is not None:
            specs.append(spec)
    doc = (cls.__doc__ or "").strip().splitlines()
    category = "load" if _is_bc(cls) else "settings"
    return FormSpec(_title(cls), specs, category, doc[0] if doc else "")


def _is_bc(cls: type) -> bool:
    base = registry.families().get(registry.BC_FAMILY)
    return base is not None and isinstance(cls, type) and issubclass(cls, base)


def form_for(cls: type) -> FormSpec:
    """Return the form of a class: the registered spec, else one derived from the class.

    Parameters
    ----------
    cls : type
        A dataclass, typically a boundary condition.
    """
    if cls in _FORMS:
        return _FORMS[cls]
    if _is_bc(cls):
        try:
            info = registry.bc_info(cls)
        except ModelError:
            info = None
        if info is not None and isinstance(info.form, FormSpec):
            return info.form
    return derive_form(cls)


def default_value(f: dataclasses.Field, hint: Any) -> Any:
    """A neutral value for a required field of type ``hint`` (used by "Add")."""
    base, optional = _unwrap(hint)
    if optional:
        return None
    if base is Function:
        return Constant(0.0)
    if base is bool:
        return False
    if base is int:
        return 0
    if base is float:
        return 0.0
    if base is str:
        return ""
    if get_origin(base) is Literal:
        return get_args(base)[0]
    if get_origin(base) is dict:
        return {}
    if get_origin(base) is list:
        return []
    raise ModelError(f"cannot give field {f.name!r} a default value")


def default_instance(cls: type, **given: Any) -> Any:
    """Create an instance of a dataclass, filling required fields with neutral values.

    Parameters
    ----------
    cls : type
        A dataclass.
    **given
        Values for some fields (e.g. ``name``).
    """
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        if f.name in given:
            kwargs[f.name] = given[f.name]
        elif (
            f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        ):
            kwargs[f.name] = default_value(f, hints[f.name])
    return cls(**kwargs)


def unique_name(base: str, existing: set[str] | list[str], start: int = 1) -> str:
    """Return ``"<base> <n>"`` with the smallest ``n >= start`` not in ``existing``."""
    used = set(existing)
    n = start
    while f"{base} {n}" in used:
        n += 1
    return f"{base} {n}"


def copy_name(name: str, existing: set[str] | list[str], keep_digits: bool = False) -> str:
    """Return a new unique name for a copy of ``name`` ("Convection 1" -> "Convection 2").

    A trailing counter (blank, then digits) is replaced. With ``keep_digits`` the whole
    name is kept and a counter appended, for names whose digits are part of the name
    (material grades: "Aluminum, Alloy 2024-T6" -> "Aluminum, Alloy 2024-T6 2").
    """
    stem = name if keep_digits else (re.sub(r"\s+\d+$", "", name) or name)
    return unique_name(stem, existing, start=2)
