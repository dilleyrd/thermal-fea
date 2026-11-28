"""Window-side texts of form fields: readable choices and the meaning of empty (M11.68).

Two conventions of ``docs/gui-conventions.md`` live here, so the model and its form specs
keep their stored values and need no change:

* **C8, readable choices.** A dropdown shows readable text ("Transient", "Every n-th
  step"); the model stores the same values as before. :func:`choice_text` gives the text
  of a stored value, falling back to the value itself.
* **C7, the meaning of empty.** An optional box shows what an empty value means in grey
  hint text ("no limit", "suggested from the mesh"); an optional formula field names its
  empty mode by that meaning instead of "None". :func:`empty_text` gives it, or ``""``.

Both tables are keyed by ``(form title, field name)``: the title of the field's
:class:`~thermalfea.core.forms.FormSpec` ("Analysis settings") and the field's name.
Later tasks (M11.72, M11.73) fill in the other panels.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from thermalfea.convection.correlation_info import CORRELATION_INFO

#: Text of each cross-section of a stream (Theory §8.1); shared with the dialogs.
CROSS_SECTION_TEXTS: dict[str, str] = {
    "circular": "Circular",
    "parallel_plates": "Parallel plates, both heated",
    "parallel_plates_one_side": "Parallel plates, one side insulated",
    "square": "Square",
    "rectangle_1_43": "Rectangle, sides 1.43 : 1",
    "rectangle_2": "Rectangle, sides 2 : 1",
    "rectangle_3": "Rectangle, sides 3 : 1",
    "rectangle_4": "Rectangle, sides 4 : 1",
    "rectangle_8": "Rectangle, sides 8 : 1",
    "triangle": "Triangle",
    "annulus_inner": "Annulus, inner surface heated",
    "annulus_outer": "Annulus, outer surface heated",
}

#: Text of each correlation: its title in :data:`CORRELATION_INFO`.
CORRELATION_TEXTS: dict[str, str] = {cid: info.title for cid, info in CORRELATION_INFO.items()}

#: Text of the kind of a network branch.
BRANCH_KIND_TEXTS: dict[str, str] = {"duct": "Duct", "loss": "Loss (K factor)"}

#: ``(form title, field) -> {stored value: shown text}``.
CHOICE_TEXTS: dict[tuple[str, str], dict[Any, str]] = {
    ("Analysis settings", "kind"): {"steady": "Steady", "transient": "Transient"},
    ("Analysis settings", "output"): {
        "all": "All steps",
        "every_n": "Every n-th step",
        "times": "At given times",
    },
    ("Initial condition", "kind"): {
        "uniform": "Uniform",
        "expression": "Expression of x and y",
        "per_region": "Per part",
        "from_results": "From a results file",
    },
    ("Mesh", "order"): {1: "Linear (1)", 2: "Quadratic (2)"},
    ("Mesh", "element_shape"): {"tri": "Triangles", "quad": "Quadrilaterals (quad-dominant)"},
    ("Mesh", "algorithm"): {
        "delaunay": "Delaunay",
        "frontal": "Frontal",
        "frontal_quad": "Frontal for quadrilaterals",
    },
    ("Stream", "mode"): {
        "in_plane": "Along a path in the plane",
        "through_plane": "Through the plane",
    },
    ("Stream", "cross_section"): CROSS_SECTION_TEXTS,
    ("Stream", "nu_option"): {
        "auto": "Automatic",
        "dittus_boelter": "Dittus–Boelter",
        "sieder_tate": "Sieder–Tate",
    },
    ("Correlation Convection", "correlation"): CORRELATION_TEXTS,
    ("Correlation Convection", "face_direction"): {
        None: "(automatic)",
        "up": "Facing up",
        "down": "Facing down",
    },
    ("Correlation Convection", "wall_T_mode"): {
        "local": "Local wall temperature",
        "average": "Mean wall temperature",
    },
    ("Boolean", "kind"): {
        "union": "Union",
        "cut": "Cut (subtract the tools)",
        "intersect": "Intersection",
    },
    ("Transform", "kind"): {
        "translate": "Move",
        "rotate": "Rotate",
        "mirror": "Mirror",
        "scale": "Scale",
    },
    ("Import File", "format"): {"step": "STEP", "brep": "BREP", "dxf": "DXF"},
}

#: Field name -> the symbol that labels, load labels and tree summaries show (decision H).
SYMBOLS: dict[str, str] = {
    "T": "T",
    "q": "q",
    "P": "P",
    "Q": "Q",
    "h": "h",
    "T_inf": "T∞",
    "emissivity": "ε",
    "conductance": "h",
}


def symbol_of(field: str) -> str:
    """The typeset symbol of a field name ("T_inf" -> "T∞"); the name itself if it has none."""
    return SYMBOLS.get(field, field)


def cross_section_text(value: str) -> str:
    """The text of a stream cross-section id ("annulus_inner" -> "Annulus, inner ...")."""
    return CROSS_SECTION_TEXTS.get(value, str(value))


def correlation_text(value: str) -> str:
    """The text of a correlation id: its title."""
    return CORRELATION_TEXTS.get(value, str(value))


def branch_kind_text(value: str) -> str:
    """The text of a network branch kind ("loss" -> "Loss (K factor)")."""
    return BRANCH_KIND_TEXTS.get(value, str(value))


def add_choices(combo: Any, values: Iterable[Any], text_of: Any) -> None:
    """Add one item per value: the readable ``text_of(value)`` shown, the value as item data."""
    for value in values:
        combo.addItem(text_of(value), value)

#: ``(form title, field) -> what an empty value means``.
EMPTY_TEXTS: dict[tuple[str, str], str] = {
    ("Analysis settings", "initial_dt"): "suggested from the mesh",
    ("Analysis settings", "dt_max"): "no limit",
    ("Analysis settings", "max_dT_per_step"): "no limit",
    ("Correlation Convection", "char_length"): "from the geometry",
    ("Correlation Convection", "velocity"): "not used",
    ("Stream", "n_cells"): "one per wall edge",
    ("Stream", "diameter_ratio"): "required for an annulus",
    ("Stream", "mass_flow"): "from network",
    ("Stream", "h_override"): "use the correlation",
    ("Material", "k2"): "isotropic",
    ("Initial condition", "results_path"): "results file (.h5)",
}

#: Text of an empty choice (``None``) that has no meaning of its own.
NONE_TEXT = "(none)"


def choice_text(form: str, field: str, value: Any) -> str:
    """The text a dropdown shows for the stored ``value`` of ``field`` in form ``form``."""
    texts = CHOICE_TEXTS.get((form, field), {})
    if value in texts:
        return texts[value]
    return NONE_TEXT if value is None else str(value)


def empty_text(form: str, field: str) -> str:
    """What an empty value of ``field`` in form ``form`` means ("" when not given)."""
    return EMPTY_TEXTS.get((form, field), "")
