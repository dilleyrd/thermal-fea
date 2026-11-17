"""Property forms generated from a :class:`~thermalfea.core.forms.FormSpec` (Plan M8.4).

:class:`FormPanel` shows one editor per field of an object of the model and writes every
accepted change back through ``Document.edit`` (one undo step per change). The object is
found by its *address* (:mod:`thermalfea.gui.addressing`), never by reference, because
``Document.edit`` works on a copy of the model.

Input is validated before it is applied: a number that cannot be parsed or is outside the
field's limits is marked (red background, tooltip) and not applied. After an undo/redo (or
any ``model_changed``) the panel reloads its editors from the model without applying
anything.
"""

from __future__ import annotations

from typing import Any, get_args, get_type_hints

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import (
    FieldSpec,
    FormSpec,
    format_float_list,
    format_str_list,
    format_str_lists,
    format_xy_list,
    from_display,
    parse_float_list,
    parse_str_list,
    parse_str_lists,
    parse_xy_list,
    to_display,
    unit_label,
)
from thermalfea.core.units import UnitSettings, from_si, to_si
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.function_editor import (
    FunctionEditor,
    parse_number,
    same_function,
)
from thermalfea.gui.property_panels.selection_editor import (
    SelectionEditor,
    SelectionRequest,
    store_selection,
)
from thermalfea.gui.scene import SceneView

_BAD_STYLE = "background-color: #ffd0d0;"
NONE_TEXT = "(none)"


def _fmt(value: float) -> str:
    return f"{value:.10g}"


class NumberEdit(QLineEdit):
    """Line edit for one number with display-unit conversion and limits.

    The value is stored in SI. :attr:`committed` carries the SI value (``None`` for an
    empty optional field) and is emitted only for valid input; invalid input is marked
    and nothing is emitted.

    Parameters
    ----------
    spec : FieldSpec
        A ``float`` or ``int`` field.
    settings : UnitSettings
        Display units.
    parent : QWidget, optional
    """

    committed = Signal(object)

    def __init__(
        self, spec: FieldSpec, settings: UnitSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.settings = settings
        self._error = ""
        self.si: float | int | None = None
        self.setToolTip(spec.tooltip)
        self.editingFinished.connect(self.commit)

    def set_settings(self, settings: UnitSettings) -> None:
        """Change the display units and re-show the stored value."""
        self.settings = settings
        self.set_si(self.si)

    def set_si(self, value: float | int | None) -> None:
        """Show an SI value (no signal); clears any error mark."""
        self.si = value
        if value is None:
            self.setText("")
        elif self.spec.quantity:
            self.setText(_fmt(float(from_si(float(value), self.spec.quantity, self.settings))))
        else:
            self.setText(str(value) if self.spec.kind == "int" else _fmt(float(value)))
        self._mark("")

    def error_text(self) -> str:
        """The message of the current input error ("" when valid)."""
        return self._error

    def _mark(self, message: str) -> None:
        self._error = message
        self.setStyleSheet(_BAD_STYLE if message else "")
        self.setToolTip(message or self.spec.tooltip)

    def parse(self) -> float | int | None:
        """Parse the text into an SI value.

        Raises
        ------
        ValueError
            With a message the user can read, if the text is invalid or out of limits.
        """
        text = self.text().strip()
        if not text:
            if self.spec.optional:
                return None
            raise ValueError("a value is required")
        try:
            shown = parse_number(text)
        except ValueError:
            raise ValueError(f"{text!r} is not a number") from None
        if self.spec.kind == "int":
            if not float(shown).is_integer():
                raise ValueError("enter a whole number")
            shown = int(shown)
        value = shown
        if self.spec.quantity:
            value = float(to_si(float(shown), self.spec.quantity, self.settings))
        if self.spec.minimum is not None and value < self.spec.minimum:
            raise ValueError(f"must be at least {self._limit(self.spec.minimum)}")
        if self.spec.maximum is not None and value > self.spec.maximum:
            raise ValueError(f"must be at most {self._limit(self.spec.maximum)}")
        return value

    def _limit(self, si_value: float) -> str:
        if self.spec.quantity:
            shown = _fmt(float(from_si(si_value, self.spec.quantity, self.settings)))
            return f"{shown} {unit_label(self.spec.quantity, self.settings)}"
        return _fmt(si_value)

    def commit(self) -> None:
        """Validate the text and emit :attr:`committed` if it is valid and changed."""
        try:
            value = self.parse()
        except ValueError as exc:
            self._mark(str(exc))
            return
        self._mark("")
        if value == self.si:
            return
        self.si = value
        self.committed.emit(value)


def format_dict(value: dict[str, float] | None) -> str:
    """Text form ``"a=1, b=2"`` of a ``{str: float}`` mapping."""
    return ", ".join(f"{k}={_fmt(float(v))}" for k, v in (value or {}).items())


def parse_dict(text: str) -> dict[str, float]:
    """Parse ``"a=1, b=2"`` into a mapping.

    Raises
    ------
    ValueError
        If an item is not ``key=number``.
    """
    out: dict[str, float] = {}
    for item in text.replace(";", ",").split(","):
        if not item.strip():
            continue
        key, sep, raw = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"{item.strip()!r} is not key=value")
        try:
            out[key.strip()] = parse_number(raw)
        except ValueError:
            raise ValueError(f"{raw.strip()!r} is not a number") from None
    return out


#: Kinds shown as one line of text: ``kind -> (format, parse)``.
_TEXT_LISTS: dict[str, tuple[Any, Any]] = {
    "str_list": (format_str_list, parse_str_list),
    "str_lists": (format_str_lists, parse_str_lists),
    "xy_list": (format_xy_list, parse_xy_list),
    "float_list": (format_float_list, parse_float_list),
}


class FormPanel(QWidget):
    """A form for one object of the model, generated from a :class:`FormSpec`.

    Parameters
    ----------
    spec : FormSpec
        The fields to show.
    document : Document
        Receives every edit through ``document.edit``.
    address : tuple
        Address of the edited object (see :mod:`thermalfea.gui.addressing`).
    view : SceneView, optional
        Viewport used by selection fields for picking.
    parent : QWidget, optional

    Signals
    -------
    value_changed(str, object)
        ``(field_name, new_value)`` after a change was applied to the model.

    Attributes
    ----------
    editors : dict of str to QWidget
        The editor widget of each field.
    """

    value_changed = Signal(str, object)

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.document = document
        self.address = address
        self.view = view
        self.editors: dict[str, QWidget] = {}
        self._choices: dict[str, tuple] = {}
        self._open_lists: set[str] = set()
        self._unit_labels: dict[str, QLabel] = {}
        self._errors: dict[str, str] = {}
        self._refreshing = False
        self._units = document.model.display_units

        outer = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(self.title_label)
        if spec.description:
            description = QLabel(spec.description)
            description.setWordWrap(True)
            outer.addWidget(description)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)
        self.form_layout = QFormLayout()
        outer.addLayout(self.form_layout)
        outer.addStretch(1)

        for field in spec.fields:
            self._add_field(field)
        document.model_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ building
    def _add_field(self, field: FieldSpec) -> None:
        editor, unit = self._make_editor(field)
        self.editors[field.name] = editor
        label = QLabel(field.label)
        if field.tooltip:
            label.setToolTip(field.tooltip)
            editor.setToolTip(field.tooltip)
        if unit is not None:
            self._unit_labels[field.name] = unit
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(editor)
            lay.addWidget(unit)
            self.form_layout.addRow(label, row)
        else:
            self.form_layout.addRow(label, editor)

    def _make_editor(self, f: FieldSpec) -> tuple[QWidget, QLabel | None]:
        name = f.name
        if f.kind in ("float", "int"):
            number = NumberEdit(f, self._units)
            number.committed.connect(lambda v, n=name: self._apply(n, v))
            return number, QLabel(unit_label(f.quantity, self._units))
        if f.kind == "bool":
            box = QCheckBox()
            box.toggled.connect(lambda v, n=name: self._apply(n, bool(v)))
            return box, None
        if f.kind == "str":
            listed = self.field_choices(f)
            if listed:
                self._choices[name] = tuple(listed)
                self._open_lists.add(name)
                pick = QComboBox()
                pick.addItems([str(c) for c in listed])
                pick.activated.connect(lambda i, n=name: self._apply(n, self._choices[n][i]))
                return pick, None
            line = QLineEdit()
            line.editingFinished.connect(lambda n=name, w=line: self._on_text(n, w.text()))
            return line, None
        if f.kind == "choice":
            assert f.choices is not None
            self._choices[name] = tuple(f.choices)
            combo = QComboBox()
            for choice in f.choices:
                combo.addItem(NONE_TEXT if choice is None else str(choice))
            combo.activated.connect(lambda i, n=name: self._apply(n, self._choices[n][i]))
            return combo, None
        if f.kind == "function":
            func = FunctionEditor(
                f.quantity, self._units, f.minimum, f.maximum, optional=f.optional
            )
            func.function_changed.connect(lambda v, n=name: self._apply(n, v))
            return func, None
        if f.kind in ("selection", "selection_list"):
            sel = SelectionEditor(self.document, self.view, f)
            sel.value_changed.connect(lambda v, n=name: self._apply(n, v))
            sel.apply_handler = lambda request, n=name: self._apply_request(n, request)
            return sel, None
        if f.kind == "dict":
            line = QLineEdit()
            line.editingFinished.connect(lambda n=name, w=line: self._on_dict(n, w))
            return line, self._unit_label_for(f)
        if f.kind in _TEXT_LISTS:
            line = QLineEdit()
            line.editingFinished.connect(lambda n=name, w=line: self._on_text_list(n, w))
            return line, self._unit_label_for(f)
        raise ModelError(f"unsupported form kind {f.kind!r}")  # pragma: no cover

    def _unit_label_for(self, f: FieldSpec) -> QLabel | None:
        """Unit label beside a list or mapping field of a quantity (``None`` otherwise)."""
        return QLabel(unit_label(f.quantity, self._units)) if f.quantity else None

    def field_choices(self, field: FieldSpec) -> tuple[str, ...] | None:
        """Closed list of values of a text (``str``) field, shown as a combo box.

        The default offers none (a line edit). A subclass overrides it to supply a list
        that lives in a layer the model may not import (for example the correlation
        identifiers). A stored value outside the list is added to the combo box so it is
        never silently replaced.

        Parameters
        ----------
        field : FieldSpec
            A field of kind ``"str"``.

        Returns
        -------
        tuple of str or None
        """
        return None

    # ------------------------------------------------------------------- loading
    def current_object(self) -> Any:
        """The edited object in the document's current model."""
        return resolve(self.document.model, self.address)

    def refresh(self) -> None:
        """Reload every editor from the model; applies nothing."""
        self._refreshing = True
        try:
            try:
                obj = self.current_object()
            except ModelError:
                self.setEnabled(False)
                return
            self.setEnabled(True)
            units = self.document.model.display_units
            if units != self._units:
                self._units = units
                for field in self.spec.fields:
                    editor = self.editors[field.name]
                    if isinstance(editor, NumberEdit):
                        editor.set_settings(units)
                    elif isinstance(editor, FunctionEditor):
                        editor.set_units(units)
                    unit = self._unit_labels.get(field.name)
                    if unit is not None:
                        unit.setText(unit_label(field.quantity, units))
            name = getattr(obj, "name", "") or getattr(obj, "id", "")
            self.title_label.setText(f"{self.spec.title}: {name}" if name else self.spec.title)
            for field in self.spec.fields:
                self._load(field, getattr(obj, field.name, None))
        finally:
            self._refreshing = False

    def _load(self, f: FieldSpec, value: Any) -> None:
        editor = self.editors[f.name]
        self._errors.pop(f.name, None)
        if isinstance(editor, NumberEdit):
            if editor.si != value or editor.error_text():
                editor.set_si(value)
        elif isinstance(editor, QCheckBox):
            editor.blockSignals(True)
            editor.setChecked(bool(value))
            editor.blockSignals(False)
        elif isinstance(editor, QComboBox):
            editor.blockSignals(True)
            choices = self._choices[f.name]
            if f.name in self._open_lists and value not in choices:
                # a value that is not in the offered list stays visible, not replaced
                choices = (*choices, value if value is not None else "")
                self._choices[f.name] = choices
                editor.addItem(str(choices[-1]))
            editor.setCurrentIndex(choices.index(value) if value in choices else 0)
            editor.blockSignals(False)
        elif isinstance(editor, FunctionEditor):
            if editor.error_text() or not same_function(editor.function(), value):
                editor.set_function(value)
        elif isinstance(editor, SelectionEditor):
            # an object without a name (a region) lends the title of its form instead
            owner = getattr(self.current_object(), "name", None) or self.spec.title
            editor.name_hint = f"{owner} {f.label.lower()}"
            editor.set_value(value)
        elif isinstance(editor, QLineEdit):
            editor.setStyleSheet("")
            if f.kind == "dict":
                editor.setText(format_dict(to_display(f, value, self._units)))
            elif f.kind in _TEXT_LISTS:
                editor.setText(_TEXT_LISTS[f.kind][0](to_display(f, value, self._units)))
            else:
                editor.setText(str(value or ""))
        self._show_error()

    # ------------------------------------------------------------------ applying
    def error_text(self, name: str | None = None) -> str:
        """Message of the last rejected input of a field (all fields when ``None``)."""
        if name is not None:
            return self._errors.get(name, "")
        return "; ".join(f"{n}: {m}" for n, m in self._errors.items())

    def _show_error(self) -> None:
        self.error_label.setText(self.error_text())
        self.error_label.setVisible(bool(self._errors))

    def _set_error(self, name: str, message: str) -> None:
        if message:
            self._errors[name] = message
        else:
            self._errors.pop(name, None)
        self._show_error()

    def _set_attribute(self, model: Any, name: str, value: Any) -> None:
        obj = resolve(model, self.address)
        setattr(obj, name, value)
        post = getattr(obj, "__post_init__", None)
        if post is not None:  # re-validate and re-coerce like construction does
            post()

    def apply(self, name: str, value: Any) -> bool:
        """Set a field to ``value`` through ``document.edit``; ``False`` if rejected."""
        return self._apply(name, value)

    def _apply(self, name: str, value: Any) -> bool:
        if self._refreshing:
            return False
        field = self.spec.field(name)
        if isinstance(value, dict):
            value = dict(value)
        elif isinstance(value, list):
            value = list(value)
        try:
            changed = self.document.edit(
                f"Edit {field.label}", lambda m: self._set_attribute(m, name, value)
            )
        except ModelError as exc:
            self._set_error(name, str(exc))
            return False
        self._set_error(name, "")
        if changed:
            self.value_changed.emit(name, value)
        return changed

    def _apply_request(self, name: str, request: SelectionRequest) -> None:
        """Create the picked selection and store its name in the field (one undo step)."""
        field = self.spec.field(name)

        def mutate(model: Any) -> None:
            store_selection(model, self.document.built, request)
            current = getattr(resolve(model, self.address), name)
            if field.kind == "selection_list":
                value = list(current) if request.name in current else [*current, request.name]
            else:
                value = request.name
            self._set_attribute(model, name, value)

        try:
            self.document.edit(f"Set {field.label}", mutate)
        except ModelError as exc:
            self._set_error(name, str(exc))
            return
        self._set_error(name, "")
        self.value_changed.emit(name, request.name)

    def _on_text(self, name: str, text: str) -> None:
        field = self.spec.field(name)
        value: str | None = text
        if not text.strip() and field.optional:
            value = None
        self._apply(name, value)

    def _on_dict(self, name: str, line: QLineEdit) -> None:
        try:
            value = parse_dict(line.text())
        except ValueError as exc:
            line.setStyleSheet(_BAD_STYLE)
            line.setToolTip(str(exc))
            self._set_error(name, str(exc))
            return
        if self._dict_of_int(name):  # e.g. numbers of divisions: whole numbers, kept as int
            if any(not float(v).is_integer() for v in value.values()):
                message = "enter whole numbers"
                line.setStyleSheet(_BAD_STYLE)
                line.setToolTip(message)
                self._set_error(name, message)
                return
            value = {key: int(v) for key, v in value.items()}
        line.setStyleSheet("")
        line.setToolTip(self.spec.field(name).tooltip)
        self._apply(name, from_display(self.spec.field(name), value, self._units))

    def _dict_of_int(self, name: str) -> bool:
        """True when the dataclass declares the field as a mapping to ``int``."""
        try:
            hint = get_type_hints(type(resolve(self.document.model, self.address))).get(name)
        except Exception:  # an unresolvable annotation: treat the values as numbers
            return False
        args = get_args(hint)
        return bool(args) and args[-1] is int

    def _on_text_list(self, name: str, line: QLineEdit) -> None:
        parse = _TEXT_LISTS[self.spec.field(name).kind][1]
        try:
            value = parse(line.text())
        except ValueError as exc:
            line.setStyleSheet(_BAD_STYLE)
            line.setToolTip(str(exc))
            self._set_error(name, str(exc))
            return
        line.setStyleSheet("")
        line.setToolTip(self.spec.field(name).tooltip)
        self._apply(name, from_display(self.spec.field(name), value, self._units))
