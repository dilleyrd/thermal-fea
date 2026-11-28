"""The dialog of one geometry tool (Plan M8.5).

:class:`GeometryOpDialog` is used *non-modally* (``show()``, never ``exec()``): it stays
open while the user clicks in the viewport. Every field has numeric entry; while it is
open, clicks in the viewport fill the next fields (snapped to the grid when snapping is
on). Fields that name earlier operations (:class:`RefEditor`) are filled from the combo
box of existing operations or from the current viewport selection.

``OK`` adds the operation and closes, ``Apply`` adds it and stays open for the next one,
``Cancel`` closes. Errors are shown in the dialog (red text), never raised.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import (
    FieldSpec,
    format_str_list,
    format_str_lists,
    format_xy_list,
    from_display,
    parse_str_list,
    parse_str_lists,
    parse_xy_list,
    to_display,
    unit_label,
)
from thermalfea.gui.geometry_defs import DEFAULTS, ToolDef, make_op
from thermalfea.gui.pick import manager_for
from thermalfea.gui.property_panels.form import NumberEdit
from thermalfea.model import geometry_edit as edit

if TYPE_CHECKING:
    from thermalfea.gui.geometry_tools import GeometryController


_PLACEHOLDER_ID = "<new>"


class RefEditor(QWidget):
    """Edits one operation id or a list of them.

    A text line (comma-separated ids), a combo box of the existing operations of the right
    kind (choosing one sets / appends it) and a button taking the ids from the viewport
    selection.

    Parameters
    ----------
    kind : {"str", "str_list", "str_lists"}
        One id, a list of ids, or a list of id lists (holes; no combo, no button).
    parent : QWidget, optional

    Attributes
    ----------
    line : QLineEdit
    combo : QComboBox
    selection_button : QPushButton
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.line = QLineEdit()
        self.combo = QComboBox()
        self.selection_button = QPushButton("Selection")
        self.selection_button.setToolTip("Take the operations of the viewport selection.")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.line, 1)
        if kind != "str_lists":
            lay.addWidget(self.combo)
            lay.addWidget(self.selection_button)
        else:
            self.combo.hide()
            self.selection_button.hide()
        self.combo.activated.connect(self._chosen)

    def set_candidates(self, ids: list[str]) -> None:
        """Offer ``ids`` in the combo box."""
        self.combo.clear()
        self.combo.addItem("Add...")
        self.combo.addItems(ids)

    def _chosen(self, index: int) -> None:
        if index <= 0:
            return
        op_id = self.combo.itemText(index)
        if self.kind == "str":
            self.line.setText(op_id)
        elif op_id not in parse_str_list(self.line.text()):
            self.set_value([*parse_str_list(self.line.text()), op_id])
        self.combo.setCurrentIndex(0)

    def set_value(self, value: Any) -> None:
        """Show a value (an id, a list of ids or a list of lists)."""
        if self.kind == "str":
            self.line.setText(str(value or ""))
        elif self.kind == "str_list":
            self.line.setText(format_str_list(list(value or [])))
        else:
            self.line.setText(format_str_lists(list(value or [])))

    def value(self) -> Any:
        """The ids as typed (a string, a list or a list of lists)."""
        text = self.line.text()
        if self.kind == "str":
            return text.strip()
        return parse_str_list(text) if self.kind == "str_list" else parse_str_lists(text)

    def mark(self, message: str) -> None:
        """Mark the line as wrong (or clear the mark with an empty message)."""
        self.line.setStyleSheet("background-color: #ffd0d0;" if message else "")
        self.line.setToolTip(message)


class GeometryOpDialog(QDialog):
    """Non-modal dialog adding one geometry operation.

    Parameters
    ----------
    controller : GeometryController
        Gives the document, viewport, grid snap and the viewport selection.
    tool : ToolDef
        The tool (see :data:`thermalfea.gui.geometry_defs.TOOLS`).
    preset : dict, optional
        Initial field values (SI), e.g. ``{"objects": ["rect1"]}``.
    parent : QWidget, optional

    Signals
    -------
    applied(str)
        The id of an operation just added.

    Attributes
    ----------
    editors : dict of str to QWidget
        Editor of each field: :class:`NumberEdit`, :class:`RefEditor`, ``QLineEdit``,
        ``QCheckBox`` or ``QComboBox``.
    id_edit : QLineEdit
        Optional id of the new operation (blank: generated).
    error_label : QLabel
        The last error; empty when there is none.
    placement : Placement or None
        The click-to-place state.
    """

    applied = Signal(str)

    def __init__(
        self,
        controller: GeometryController,
        tool: ToolDef,
        preset: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.tool = tool
        self.document = controller.document
        self.editors: dict[str, QWidget] = {}
        self.specs: dict[str, FieldSpec] = {}
        self._labels: dict[str, QLabel] = {}  # the row labels, relabelled on a unit change
        self._snap_unit: QLabel | None = None
        self._connected = False
        self.placement = edit.Placement(tool.placement) if tool.placement else None
        self.setWindowTitle(tool.title)
        self.setModal(False)

        outer = QVBoxLayout(self)
        if tool.selection == "boolean":
            rule = QLabel(
                "Objects: the earliest selected shape; tools: the other selected shapes. "
                "Select more shapes and press 'Selection' to fill the tools."
            )
            rule.setWordWrap(True)
            outer.addWidget(rule)
        if tool.placement:
            hint = QLabel(f"Click in the viewport to place ({tool.placement}).")
            hint.setWordWrap(True)
            outer.addWidget(hint)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)
        self.form = QFormLayout()
        outer.addLayout(self.form)

        self._units = self.document.model.display_units
        self.document.model_changed.connect(self._on_model_changed)
        for spec in tool.specs():
            self._add_field(spec)
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("automatic")
        self.form.addRow(QLabel("Id"), self.id_edit)
        if tool.placement:
            self._add_snap_row(outer)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        if tool.key == "polygon":
            finish = QPushButton("Finish")
            finish.setToolTip("Close the polygon and add it.")
            finish.clicked.connect(self.accept)
            self.finish_button = finish
            last = QPushButton("Remove last vertex")
            last.clicked.connect(self.remove_last_vertex)
            self.remove_last_button = last
            self.buttons.addButton(finish, QDialogButtonBox.ButtonRole.ActionRole)
            self.buttons.addButton(last, QDialogButtonBox.ButtonRole.ActionRole)
        outer.addWidget(self.buttons)

        self.refresh_candidates()
        for name, value in {**DEFAULTS, **(preset or {})}.items():
            if name in self.editors:
                self.set_value(name, value)
        view = controller.view
        if tool.placement and view is not None:
            view.point_picked.connect(self._on_pick)
            self._connected = True
            # a placing dialog is a pick of the one pick workflow (C2): toolbar "None" while
            # open, Enter in the view adds (OK), Esc closes without adding (Cancel)
            manager_for(view).start(self, "none", cancel=self.reject, confirm=self.accept)

    # ------------------------------------------------------------------ building
    def _add_field(self, spec: FieldSpec) -> None:
        name = spec.name
        self.specs[name] = spec
        editor: QWidget
        rule = self._ref_rule(name)
        if rule is not None and spec.kind in ("str", "str_list", "str_lists"):
            editor = RefEditor(spec.kind)
            editor.selection_button.clicked.connect(lambda _c=False, n=name: self.use_selection(n))
        elif spec.kind == "float":
            number = NumberEdit(spec, self._units)
            number.setPlaceholderText(unit_label(spec.quantity, self._units))
            editor = number
        elif spec.kind == "bool":
            editor = QCheckBox()
        elif spec.kind == "choice":
            combo = QComboBox()
            for choice in spec.choices or ():
                combo.addItem(str(choice))
            editor = combo
        else:  # str, xy_list
            editor = QLineEdit()
        if spec.tooltip:
            editor.setToolTip(spec.tooltip)
        self.editors[name] = editor
        label = QLabel(self._field_label(spec))
        self._labels[name] = label
        self.form.addRow(label, editor)

    def _field_label(self, spec: FieldSpec) -> str:
        """The row label of a field; its unit comes from the display settings, not the label."""
        label = spec.label
        if spec.quantity:
            base = re.sub(r"\s*\[[^\]]*\]$", "", label)
            label = f"{base} [{unit_label(spec.quantity, self._units)}]"
        return label

    def _on_model_changed(self) -> None:
        """Show the fields in the new display units when the units changed while open."""
        units = self.document.model.display_units
        if units == self._units:
            return
        # Text fields of lists are shown in display units: read them in the old units first.
        xy_values: dict[str, Any] = {}
        for name, spec in self.specs.items():
            if spec.kind == "xy_list":
                try:
                    xy_values[name] = self.value(name)
                except ValueError:
                    pass
        self._units = units
        for name, editor in self.editors.items():
            spec = self.specs[name]
            if isinstance(editor, NumberEdit):
                editor.set_settings(units)  # re-shows the stored SI value in the new units
                if spec.quantity:
                    editor.setPlaceholderText(unit_label(spec.quantity, units))
            self._labels[name].setText(self._field_label(spec))
        if self._snap_unit is not None:
            self.snap_spacing.set_settings(units)
            self._snap_unit.setText(unit_label("length", units))
        for name, value in xy_values.items():
            self.set_value(name, value)

    def _ref_rule(self, name: str) -> tuple[type, ...] | None:
        return edit.REF_RULES.get((self.tool.cls, name))

    def _add_snap_row(self, outer: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self.snap_box = QCheckBox("Snap to grid")
        self.snap_box.setChecked(self.controller.snap.enabled)
        self.snap_box.toggled.connect(lambda on: self.controller.set_snap(enabled=bool(on)))
        spacing = FieldSpec("spacing", "Grid spacing", "float", quantity="length", minimum=1e-12)
        self.snap_spacing = NumberEdit(spacing, self._units)
        self.snap_spacing.set_si(self.controller.snap.spacing)
        self.snap_spacing.committed.connect(
            lambda v: self.controller.set_snap(spacing=float(v))
        )
        row.addWidget(self.snap_box)
        row.addWidget(self.snap_spacing)
        self._snap_unit = QLabel(unit_label("length", self._units))
        row.addWidget(self._snap_unit)
        outer.addLayout(row)
        self.controller.snap_changed.connect(self._sync_snap)

    def _sync_snap(self) -> None:
        snap = self.controller.snap
        self.snap_box.blockSignals(True)
        self.snap_box.setChecked(snap.enabled)
        self.snap_box.blockSignals(False)
        if self.snap_spacing.si != snap.spacing:
            self.snap_spacing.set_si(snap.spacing)

    # --------------------------------------------------------------- field access
    def refresh_candidates(self) -> None:
        """Reload the combo boxes with the operations that exist now."""
        for name, editor in self.editors.items():
            rule = self._ref_rule(name)
            if isinstance(editor, RefEditor) and rule is not None:
                earlier = self.document.model.geometry
                editor.set_candidates(edit.candidate_ids(earlier, rule))

    def set_value(self, name: str, value: Any) -> None:
        """Show a value (SI) in a field."""
        editor = self.editors[name]
        if isinstance(editor, NumberEdit):
            editor.set_si(float(value))
        elif isinstance(editor, RefEditor):
            editor.set_value(value)
        elif isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QComboBox):
            editor.setCurrentText(str(value))
        elif self.specs[name].kind == "xy_list":
            shown = to_display(self.specs[name], list(value), self._units)
            editor.setText(format_xy_list(shown))  # type: ignore[attr-defined]
        else:
            editor.setText(str(value))  # type: ignore[attr-defined]

    def value(self, name: str) -> Any:
        """Read a field.

        Raises
        ------
        ValueError
            With a message the user can read, if the text is invalid.
        """
        editor = self.editors[name]
        spec = self.specs[name]
        if isinstance(editor, NumberEdit):
            result = editor.parse()
            editor.si = result
            return result
        if isinstance(editor, RefEditor):
            return editor.value()
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, QComboBox):
            return editor.currentText()
        text = editor.text()  # type: ignore[attr-defined]
        if spec.kind == "xy_list":
            return from_display(spec, parse_xy_list(text), self._units)
        return text.strip()

    def values(self) -> dict[str, Any]:
        """Every field's value.

        Raises
        ------
        ValueError
            Listing the fields that are wrong.
        """
        out: dict[str, Any] = {}
        problems: list[str] = []
        for name, editor in self.editors.items():
            try:
                out[name] = self.value(name)
            except ValueError as exc:
                problems.append(f"{self.specs[name].label}: {exc}")
                if isinstance(editor, NumberEdit):
                    editor._mark(str(exc))
                elif isinstance(editor, RefEditor):
                    editor.mark(str(exc))
        if problems:
            raise ValueError("; ".join(problems))
        return out

    # ------------------------------------------------------------------- picking
    def _on_pick(self, x: float, y: float, _z: float = 0.0) -> None:
        """A viewport click: snap it and fill the fields it determines."""
        if self.placement is None:
            return
        sx, sy = self.controller.snap.snap(x, y)
        for name, value in self.placement.pick(sx, sy).items():
            if name in self.editors:
                self.set_value(name, value)
        self._set_error("")

    def remove_last_vertex(self) -> None:
        """Drop the last polygon vertex (and its click)."""
        if self.placement is None or not self.placement.picks:
            return
        self.placement.picks.pop()
        self.set_value("vertices", list(self.placement.picks))

    def use_selection(self, name: str) -> None:
        """Fill a reference field from the viewport selection.

        ``tools`` leaves out what ``objects`` already holds.
        """
        rule = self._ref_rule(name)
        editor = self.editors[name]
        if rule is None or not isinstance(editor, RefEditor):
            return
        ids = self.controller.selected_ops(rule)
        if name == "tools" and "objects" in self.editors:
            taken = set(self._ids_of("objects"))
            ids = [i for i in ids if i not in taken]
        editor.set_value(ids[0] if editor.kind == "str" and ids else ids)
        if not ids:
            self._set_error("The selection holds no operation of the right kind.")
        else:
            self._set_error("")

    def _ids_of(self, name: str) -> list[str]:
        editor = self.editors[name]
        value = editor.value() if isinstance(editor, RefEditor) else []
        return [value] if isinstance(value, str) else list(value)

    # -------------------------------------------------------------------- applying
    def _set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def apply(self) -> bool:
        """Validate and add the operation; ``False`` (error shown) if it is not valid."""
        try:
            values = self.values()
            op_id = self.id_edit.text().strip() or None
            op = make_op(self.tool, values, op_id or _PLACEHOLDER_ID)
            edit.validate_op(op, self.document.model.geometry)
            new_id = self.controller.add_operation(self.tool, values, op_id)
        except (ValueError, ModelError) as exc:
            self._set_error(str(exc))
            return False
        self._set_error("")
        if self.placement is not None:
            self.placement.reset()
        self.id_edit.clear()
        self.refresh_candidates()
        self.applied.emit(new_id)
        return True

    def accept(self) -> None:
        """Add the operation; close only if it was added."""
        if self.apply():
            super().accept()

    def done(self, result: int) -> None:
        """Stop listening to the viewport and close."""
        view = self.controller.view
        if self._connected and view is not None:
            try:
                view.point_picked.disconnect(self._on_pick)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
            manager_for(view).finish(self)
        if self.tool.placement:
            try:
                self.controller.snap_changed.disconnect(self._sync_snap)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

