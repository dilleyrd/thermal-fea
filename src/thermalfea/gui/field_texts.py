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

from typing import Any

#: ``(form title, field) -> {stored value: shown text}``.
CHOICE_TEXTS: dict[tuple[str, str], dict[Any, str]] = {
    ("Analysis settings", "kind"): {"steady": "Steady", "transient": "Transient"},
    ("Analysis settings", "output"): {
        "all": "All steps",
        "every_n": "Every n-th step",
        "times": "At given times",
    },
}

#: ``(form title, field) -> what an empty value means``.
EMPTY_TEXTS: dict[tuple[str, str], str] = {
    ("Analysis settings", "initial_dt"): "suggested from the mesh",
    ("Analysis settings", "dt_max"): "no limit",
    ("Analysis settings", "max_dT_per_step"): "no limit",
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
