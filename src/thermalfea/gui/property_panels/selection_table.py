"""Value-per-selection tables (held item 13; conventions C1, C6, C10, C11; task M11.71).

Boundary sizes, point sizes, boundary divisions, the initial temperature per part and the
Mesh panel's refinements give values to named selections. Instead of typed text
(``cooled=1, long sides=40``) each is a small table:

    Boundary                     Elements
    [ cooled · 1 boundary   ▾ ]  [   1 ]           ✕
    [ long sides · 2 bounds ▾ ]  [  40 ]   ✓ ↶     ✕     <- selection changed: not applied
    +   + New

* each row: a dropdown of the compatible selections (a name another row holds is not
  offered again where names must be unique), the value boxes with their units, ✕;
* **changing a row's selection waits for Update (C1)**: the row is marked and shows ✓ and
  ↶; Enter in one of its value boxes applies the whole row, so a row is never half-applied;
  a value alone applies on Enter, like any number box;
* **+** adds a draft row, applied by ✓ or Enter once it has a selection and valid values,
  dropped by ↶; **+ New** picks a new selection in the view (the selection field's New,
  C2) and adds a draft row for it;
* the row whose box has the focus has its selection highlighted in the view (C10);
* an error is shown once, under its row (C11).

The table holds rows ``(selection name, values)`` with values in SI and tells its owner
the whole new list through :attr:`SelectionTable.rows_changed`; the owner stores it in one
undo step. :data:`SELECTION_TABLES` names the dictionary fields of the forms that are shown
this way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.forms import FieldSpec, unit_label
from thermalfea.core.units import UnitSettings
from thermalfea.gui.document import Document
from thermalfea.gui.icons import icon, icon_button
from thermalfea.gui.property_panels.selection_editor import (
    SelectionEditor,
    SelectionRequest,
    role_label,
    selection_label,
)
from thermalfea.gui.scene import SceneView
from thermalfea.model.selections import StaleSelectionError
from thermalfea.model.selections import resolve as resolve_selection

_PENDING_STYLE = "QComboBox { border: 2px solid #e0a000; border-radius: 3px; }"
_ERROR_STYLE = "color: #b00020;"
CHOOSE_TEXT = "(choose…)"

Row = tuple[str, tuple[float, ...]]


@dataclass(frozen=True)
class Column:
    """A value column: a name (for the number box), its header, quantity and limits."""

    name: str
    label: str
    quantity: str | None = None
    kind: str = "float"
    minimum: float | None = None

    def spec(self) -> FieldSpec:
        """The field spec a number box of this column checks against."""
        return FieldSpec(self.name, self.label, self.kind, quantity=self.quantity,
                         minimum=self.minimum)  # fmt: skip


@dataclass(frozen=True)
class TableSpec:
    """A dictionary field shown as a table: the selections' dimensions and the value."""

    dims: tuple[int, ...]
    column: Column


#: The forms' ``{selection: value}`` fields shown as tables: ``(form title, field)``.
SELECTION_TABLES: dict[tuple[str, str], TableSpec] = {
    ("Mesh", "curve_sizes"): TableSpec((1,), Column("size", "Element size", "length",
                                                    minimum=0.0)),  # fmt: skip
    ("Mesh", "point_sizes"): TableSpec((0,), Column("size", "Element size", "length",
                                                    minimum=0.0)),  # fmt: skip
    ("Mesh", "curve_divisions"): TableSpec((1,), Column("count", "Elements", None, "int",
                                                        minimum=1.0)),  # fmt: skip
    ("Initial condition", "per_region"): TableSpec(
        (2,), Column("T", "Temperature", "temperature")
    ),
}


class _FocusWatch(QObject):
    """Calls ``on_focus(row)`` when a widget of a row gets the focus."""

    def __init__(self, on_focus: Callable[[int], None]) -> None:
        super().__init__()
        self.on_focus = on_focus
        self.rows: dict[QObject, int] = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.FocusIn and watched in self.rows:
            self.on_focus(self.rows[watched])
        return False


class _RowWidgets:
    """The widgets of one row."""

    def __init__(self) -> None:
        self.combo = QComboBox()
        self.edits: list = []
        self.update_button = icon_button("update", "Update: apply this row")
        self.revert_button = icon_button("revert", "Revert: undo the change of this row")
        self.remove_button = icon_button("remove", "Remove this row")
        self.error = QLabel("")
        self.error.setStyleSheet(_ERROR_STYLE)
        self.error.setWordWrap(True)
        self.error.setVisible(False)


class SelectionTable(QWidget):
    """A table of ``(selection, values)`` rows.

    Parameters
    ----------
    document : Document
    view : SceneView or None
        For highlighting a focused row's selection and for picking new selections.
    dims : tuple of int
        Dimensions of the selections the rows may name.
    columns : list of Column
        The value columns.
    units : UnitSettings
        Display units of the value boxes.
    unique : bool
        A selection may appear in one row only (dictionary fields); refinements allow more.
    row_check : callable, optional
        ``check(values) -> None`` raising ``ValueError`` with a readable message for a row
        whose values are inconsistent (e.g. size min > size max).
    parent : QWidget, optional

    Signals
    -------
    rows_changed(list)
        A row was applied or removed: the whole new list of rows, values in SI.
    """

    rows_changed = Signal(list)

    def __init__(
        self,
        document: Document,
        view: SceneView | None,
        dims: tuple[int, ...],
        columns: list[Column],
        units: UnitSettings,
        unique: bool = True,
        row_check: Callable[[tuple[float, ...]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.document = document
        self.view = view
        self.dims = dims
        self.columns = list(columns)
        self.units = units
        self.unique = unique
        self.row_check = row_check
        self._stored: list[Row] = []
        #: The shown rows: ``[name, values or None (draft), stored index or None]``.
        self._rows: list[list] = []
        self._widgets: list[_RowWidgets] = []
        self._watch = _FocusWatch(self._on_focus)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self.grid)
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignTop)
        # table-level commands: an icon and a word ("+ Add", "New…" with the pick icon)
        self.add_button = icon_button("add", "Add a row for a selection")
        self.add_button.setText("Add")
        self.add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_button.clicked.connect(lambda _c=False: self.add_row())
        buttons.addWidget(self.add_button)
        # New…: the selection field's New pick, without its dropdown row
        self.picker = SelectionEditor(
            document, view, FieldSpec("new", "New", "selection", selection_dims=dims)
        )
        for widget in (self.picker.combo, self.picker.edit_button, self.picker.update_button,
                       self.picker.revert_button):  # fmt: skip
            widget.hide()
        self.picker.apply_handler = self._create_selection
        new = self.picker.new_button
        new.setIcon(icon("pick"))
        new.setText("New…")
        new.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        new.setToolTip("New selection: pick it in the view and add a row")
        new.setAccessibleName(new.toolTip())
        picker_row = self.picker.layout().itemAt(1).layout()  # the hidden dropdown's row
        picker_row.addStretch(1)  # keep New… at the left
        buttons.addWidget(self.picker, 1)  # its strip opens below, across the table
        column.addLayout(buttons)
        self.empty_label = QLabel("none")
        self.empty_label.setStyleSheet("color: palette(mid);")
        column.insertWidget(0, self.empty_label)
        document.model_changed.connect(self._refill_choices)

    # ------------------------------------------------------------------- values
    def rows(self) -> list[Row]:
        """The stored rows (what the object holds)."""
        return list(self._stored)

    def has_pending(self) -> bool:
        """True while a row waits for Update (a changed selection or a draft)."""
        return any(self._row_pending(i) for i in range(len(self._rows)))

    def set_rows(self, rows: list[Row]) -> None:
        """Show the stored rows (drops pending changes)."""
        self._stored = [(str(n), tuple(float(v) for v in vals)) for n, vals in rows]
        self._rows = [[name, values, i] for i, (name, values) in enumerate(self._stored)]
        self._rebuild()

    def set_units(self, units: UnitSettings) -> None:
        """Change the display units of the value boxes."""
        self.units = units
        self._rebuild()

    # ---------------------------------------------------------------- building
    def _names(self) -> list[str]:
        model = self.document.model
        return [n for n, s in model.selections.items() if s.dim in self.dims]

    def _rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._widgets = []
        self._watch.rows.clear()
        model = self.document.model
        self.grid.addWidget(QLabel(role_label(model, self.dims)), 0, 0)
        for c, col in enumerate(self.columns, start=1):
            unit = unit_label(col.quantity, self.units) if col.quantity else ""
            self.grid.addWidget(QLabel(f"{col.label} [{unit}]" if unit else col.label), 0, c)
        for r, row in enumerate(self._rows):
            self._add_row_widgets(r, row)
        self.grid.setColumnStretch(0, 3)
        for c in range(1, len(self.columns) + 1):
            self.grid.setColumnStretch(c, 2)
        self.empty_label.setVisible(not self._rows)
        for label_col in range(len(self.columns) + 1):
            item = self.grid.itemAtPosition(0, label_col)
            if item is not None and item.widget() is not None:
                item.widget().setVisible(bool(self._rows))
        self._refill_choices()

    def _add_row_widgets(self, r: int, row: list) -> None:
        from thermalfea.gui.property_panels.form import NumberEdit  # form imports this module

        w = _RowWidgets()
        grid_row = 1 + 2 * r
        self.grid.addWidget(w.combo, grid_row, 0)
        w.combo.activated.connect(lambda i, r=r: self._on_choose(r, i))
        values = row[1]
        for c, col in enumerate(self.columns):
            edit = NumberEdit(col.spec(), self.units)
            value = values[c] if values is not None else None
            if value is not None and col.kind == "int":
                value = int(value)  # a count shows as 40, not 40.0
            edit.set_si(value)
            if values is None:
                edit.setText("")
            edit.returnPressed.connect(lambda r=r: self.apply_row(r))
            edit.editingFinished.connect(lambda r=r: self._on_value_left(r))
            self.grid.addWidget(edit, grid_row, 1 + c)
            w.edits.append(edit)
            edit.installEventFilter(self._watch)
            self._watch.rows[edit] = r
        w.combo.installEventFilter(self._watch)
        self._watch.rows[w.combo] = r
        icons = QWidget()
        icon_row = QHBoxLayout(icons)
        icon_row.setContentsMargins(0, 0, 0, 0)
        for button in (w.update_button, w.revert_button, w.remove_button):
            icon_row.addWidget(button)
        w.update_button.clicked.connect(lambda _c=False, r=r: self.apply_row(r))
        w.revert_button.clicked.connect(lambda _c=False, r=r: self.revert_row(r))
        w.remove_button.clicked.connect(lambda _c=False, r=r: self.remove_row(r))
        self.grid.addWidget(icons, grid_row, 1 + len(self.columns))
        self.grid.addWidget(w.error, grid_row + 1, 0, 1, 2 + len(self.columns))
        self._widgets.append(w)

    def _refill_choices(self) -> None:
        model = self.document.model
        names = self._names()
        for r, w in enumerate(self._widgets):
            name = self._rows[r][0]
            taken = {row[0] for i, row in enumerate(self._rows) if i != r} if self.unique else set()
            w.combo.blockSignals(True)
            w.combo.clear()
            if not name:
                w.combo.addItem(CHOOSE_TEXT, "")
            for n in names:
                if n not in taken:
                    w.combo.addItem(selection_label(model, n), n)
            if name and w.combo.findData(name) < 0:  # dangling: kept visible, never replaced
                w.combo.addItem(selection_label(model, name), name)
            w.combo.setCurrentIndex(max(w.combo.findData(name), 0))
            w.combo.blockSignals(False)
            self._show_state(r)

    def _row_pending(self, r: int) -> bool:
        name, _values, stored = self._rows[r]
        return stored is None or self._stored[stored][0] != name

    def _show_state(self, r: int) -> None:
        w = self._widgets[r]
        pending = self._row_pending(r)
        w.combo.setStyleSheet(_PENDING_STYLE if pending else "")
        w.update_button.setVisible(pending)
        w.revert_button.setVisible(pending)
        w.remove_button.setVisible(self._rows[r][2] is not None)

    # ------------------------------------------------------------------ actions
    def _on_choose(self, r: int, index: int) -> None:
        name = str(self._widgets[r].combo.itemData(index) or "")
        self._rows[r][0] = name
        self._set_row_error(r, "")
        self._show_state(r)
        self._highlight(name)

    def _on_value_left(self, r: int) -> None:
        """Leaving a value box: a stored row whose selection is unchanged applies it."""
        if r < len(self._rows) and not self._row_pending(r):
            self.apply_row(r)

    def _parse(self, r: int) -> tuple[float, ...]:
        w = self._widgets[r]
        values = []
        for edit, col in zip(w.edits, self.columns, strict=True):
            value = edit.parse()
            if value is None:
                raise ValueError(f"{col.label.lower()}: a value is required")
            values.append(float(value))
        result = tuple(values)
        if self.row_check is not None:
            self.row_check(result)
        return result

    def apply_row(self, r: int) -> bool:
        """Apply row ``r`` (Update or Enter): its selection and values, in one step."""
        if r >= len(self._rows):
            return False
        name = self._rows[r][0]
        if not name:
            self._set_row_error(r, "choose a selection")
            return False
        try:
            values = self._parse(r)
        except ValueError as exc:
            self._set_row_error(r, str(exc))
            return False
        self._set_row_error(r, "")
        new = list(self._stored)
        stored = self._rows[r][2]
        if stored is None:
            new.append((name, values))
        else:
            if new[stored] == (name, values):
                return False
            new[stored] = (name, values)
        self.rows_changed.emit(new)
        return True

    def revert_row(self, r: int) -> None:
        """Drop the pending change of row ``r`` (a draft row disappears)."""
        stored = self._rows[r][2]
        if stored is None:
            del self._rows[r]
        else:
            self._rows[r] = [self._stored[stored][0], self._stored[stored][1], stored]
        self._rebuild()

    def remove_row(self, r: int) -> None:
        """Remove a stored row (one undo step)."""
        stored = self._rows[r][2]
        if stored is None:
            self.revert_row(r)
            return
        new = [row for i, row in enumerate(self._stored) if i != stored]
        self.rows_changed.emit(new)

    def add_row(self, name: str = "") -> int:
        """Add a draft row (applied by Update or Enter); returns its index."""
        self._rows.append([name, None, None])
        self._rebuild()
        r = len(self._rows) - 1
        if self._widgets[r].edits:
            self._widgets[r].edits[0].setFocus()
        return r

    def _create_selection(self, request: SelectionRequest) -> str | None:
        """The New pick's handler: create the selection, then add a draft row for it."""
        name = self.picker._default_apply(request)
        if name:
            self.add_row(name)
        return name

    def _set_row_error(self, r: int, message: str) -> None:
        if r < len(self._widgets):
            self._widgets[r].error.setText(message)
            self._widgets[r].error.setVisible(bool(message))

    def row_error(self, r: int) -> str:
        """The error shown under row ``r``."""
        return self._widgets[r].error.text() if r < len(self._widgets) else ""

    def row_widgets(self, r: int) -> _RowWidgets:
        """The widgets of row ``r`` (combo, edits, icons, error)."""
        return self._widgets[r]

    # -------------------------------------------------------------- highlighting
    def _on_focus(self, r: int) -> None:
        if r < len(self._rows):
            self._highlight(self._rows[r][0])

    def _highlight(self, name: str) -> None:
        if self.view is None or self.document.built is None or not name:
            return
        selection = self.document.model.selections.get(name)
        if selection is None:
            return
        try:
            tags = resolve_selection(selection, self.document.built)
        except StaleSelectionError:
            return
        self.view.highlight(selection.dim, tags)


__all__ = ["CHOOSE_TEXT", "SELECTION_TABLES", "Column", "Row", "SelectionTable", "TableSpec"]
