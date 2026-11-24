"""Editor of a :class:`~thermalfea.core.functions.Function` (Plan M8.4).

Three modes: *constant* (one number), *table* (editable two-column grid, piecewise linear,
with a preview plot) and *expression* (text validated while typing by the real
:class:`~thermalfea.core.functions.Expression`). Values are stored in SI; numbers and
table values are shown in the display units of the field's quantity. Expressions are
always in SI (t in s, x and y in m, T in K).

:attr:`FunctionEditor.function_changed` is emitted only for valid input, and only when the
user finishes an edit (Enter / focus loss for a number or an expression, a changed cell
for a table).

Paste rule (:func:`parse_pasted`)
---------------------------------
Clipboard text is read line by line; blank lines are ignored. A line is split at tabs if
it has any, else at semicolons, else at commas, else at white space. Only the first two
cells of a line are used. With tab or semicolon separators a single comma inside a number
is a decimal comma (``"1,5"``); with comma separators it is a separator, so ``"1,5"`` is
two cells. The first line is skipped when it is not numeric (a header). Any other
non-numeric cell rejects the whole paste. A successful paste replaces the whole grid.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import unit_label
from thermalfea.core.functions import (
    Constant,
    Expression,
    Function,
    Table,
    function_to_json,
)
from thermalfea.core.units import UnitSettings, from_si, is_si, si_label, to_si
from thermalfea.gui.property_panels.function_preview import FunctionPreview

MODES = ("constant", "table", "expression", "none")
_MODE_LABELS = {
    "constant": "Constant",
    "table": "Table",
    "expression": "Expression",
    "none": "None",
}
_VARIABLE_LABELS = {"t": "time (t)", "T": "temperature (T)"}
_BAD_STYLE = "background-color: #ffd0d0;"
_VARIABLE_TIPS = {"t": "t [s]", "x": "x [m]", "y": "y [m]", "T": "T [K]"}


def _allowed_words(allowed: tuple[str, ...]) -> str:
    """The allowed variables in words, e.g. ``"time (t) and position (x, y)"``."""
    parts = []
    if "t" in allowed:
        parts.append("time (t)")
    position = [v for v in ("x", "y") if v in allowed]
    if position:
        parts.append(f"position ({', '.join(position)})")
    if "T" in allowed:
        parts.append("temperature (T)")
    return " and ".join(parts)


def parse_number(text: str) -> float:
    """Parse one number typed by the user (a single decimal comma is accepted)."""
    s = text.strip()
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    return float(s)


def parse_pasted(text: str) -> list[tuple[float, float]]:
    """Parse clipboard text into ``(x, y)`` rows; the rule is in the module docstring.

    Raises
    ------
    ValueError
        If the text has no usable rows or a cell is not a number.
    """
    rows: list[tuple[float, float]] = []
    first = True
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        decimal_comma = False
        if "\t" in line:
            cells, decimal_comma = line.split("\t"), True
        elif ";" in line:
            cells, decimal_comma = line.split(";"), True
        elif "," in line:
            cells = line.split(",")
        else:
            cells = line.split()
        cells = [c.strip() for c in cells]
        while cells and not cells[-1]:
            cells.pop()
        if len(cells) < 2:
            raise ValueError(f"line {number}: need two values (x and y)")
        try:
            values = []
            for cell in cells[:2]:
                if decimal_comma and cell.count(",") == 1 and "." not in cell:
                    cell = cell.replace(",", ".")
                values.append(float(cell))
        except ValueError:
            if first:  # a header line
                first = False
                continue
            raise ValueError(f"line {number}: {line.strip()!r} is not two numbers") from None
        first = False
        rows.append((values[0], values[1]))
    if not rows:
        raise ValueError("nothing to paste: no numeric rows found")
    return rows


class _Grid(QTableWidget):
    """Table widget that reports Ctrl+V instead of ignoring it."""

    paste_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            return
        super().keyPressEvent(event)


class FunctionEditor(QWidget):
    """Edit a function as a constant, a table or an expression.

    Parameters
    ----------
    quantity : str, optional
        Quantity of the values (for display-unit conversion of constants and table
        values); ``None`` for none.
    settings : UnitSettings, optional
        Display units; default SI/kelvin.
    minimum, maximum : float, optional
        Inclusive limits of a constant's SI value.
    optional : bool
        Add a "None" mode that emits ``None``.
    variables : tuple of str, optional
        The variables of ``t, x, y, T`` the function may use (``None``: all). The table's
        variable box offers those of ``t`` and ``T`` among them, and an expression that uses
        another is refused. A function loaded with :meth:`set_function` that breaks this is
        shown as it is, with the error, and never emitted.
    parent : QWidget, optional

    Signals
    -------
    function_changed(object)
        A valid new function (or ``None`` in "None" mode).
    """

    function_changed = Signal(object)

    def __init__(
        self,
        quantity: str | None = None,
        settings: UnitSettings | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        optional: bool = False,
        parent: QWidget | None = None,
        variables: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.variables = variables
        self._table_variables = tuple(
            v for v in ("t", "T") if variables is None or v in variables
        )
        self._expression_tip = "SI units. Variables: " + ", ".join(
            _VARIABLE_TIPS[v]
            for v in ("t", "x", "y", "T")
            if variables is None or v in variables
        ) + "."
        self.quantity = quantity
        self.settings = settings if settings is not None else UnitSettings()
        self.minimum = minimum
        self.maximum = maximum
        self.optional = optional
        self._loading = False
        self._function: Function | None = None
        self._error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode_combo = QComboBox()
        for mode in MODES if optional else MODES[:3]:
            if mode == "table" and not self._table_variables:
                continue  # no variable a table could be a function of
            self.mode_combo.addItem(_MODE_LABELS[mode], mode)
        layout.addWidget(self.mode_combo)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self._build_constant_page()
        self._build_table_page()
        self._build_expression_page()
        self.stack.addWidget(QWidget())  # "none"
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.set_units(self.settings)
        self._show_mode("constant")

    # ------------------------------------------------------------------ building
    def _build_constant_page(self) -> None:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        self.value_edit = QLineEdit("0")
        self.unit_label = QLabel("")
        row.addWidget(self.value_edit)
        row.addWidget(self.unit_label)
        self.value_edit.textChanged.connect(self._check_live)
        self.value_edit.editingFinished.connect(self.commit)
        self.stack.addWidget(page)

    def _build_table_page(self) -> None:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.variable_combo = QComboBox()
        for key in self._table_variables:
            self.variable_combo.addItem(_VARIABLE_LABELS[key], key)
        self.extrapolate_combo = QComboBox()
        self.extrapolate_combo.addItem("hold ends", "hold")
        self.extrapolate_combo.addItem("extrapolate linearly", "linear")
        top.addWidget(QLabel("As a function of"))
        top.addWidget(self.variable_combo)
        top.addWidget(self.extrapolate_combo)
        col.addLayout(top)
        self.grid = _Grid(0, 2)
        self.grid.setMinimumHeight(110)
        col.addWidget(self.grid)
        buttons = QHBoxLayout()
        self.add_row_button = QPushButton("Add row")
        self.remove_row_button = QPushButton("Remove row")
        self.paste_button = QPushButton("Paste")
        self.paste_button.setToolTip("Paste two columns (e.g. from Excel) over the table.")
        for button in (self.add_row_button, self.remove_row_button, self.paste_button):
            buttons.addWidget(button)
        col.addLayout(buttons)
        self.preview = FunctionPreview()
        col.addWidget(self.preview)
        self.add_row_button.clicked.connect(self.add_row)
        self.remove_row_button.clicked.connect(self.remove_selected_rows)
        self.paste_button.clicked.connect(self.paste_from_clipboard)
        self.grid.paste_requested.connect(self.paste_from_clipboard)
        self.grid.itemChanged.connect(self._on_cell_changed)
        self.variable_combo.currentIndexChanged.connect(self._on_table_option_changed)
        self.extrapolate_combo.currentIndexChanged.connect(self._on_table_option_changed)
        self.stack.addWidget(page)

    def _build_expression_page(self) -> None:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        self.expr_edit = QLineEdit()
        self.expr_edit.setPlaceholderText("e.g. 300 + 20*sin(2*pi*t/60)")
        self.expr_edit.setToolTip(self._expression_tip)
        col.addWidget(self.expr_edit)
        self.si_note = QLabel("")
        self.si_note.setWordWrap(True)
        self.si_note.setStyleSheet("color: #805000;")
        col.addWidget(self.si_note)
        self.expr_edit.textChanged.connect(self._check_live)
        self.expr_edit.editingFinished.connect(self.commit)
        self.stack.addWidget(page)

    # --------------------------------------------------------------------- units
    def set_units(self, settings: UnitSettings) -> None:
        """Change the display units (table cells keep their SI meaning)."""
        old_si = self._table_si_rows()
        old_value = self._constant_si()
        self.settings = settings
        unit = unit_label(self.quantity, settings)
        self.unit_label.setText(unit)
        self._update_si_note()
        self._loading = True
        try:
            if old_value is not None:
                self.value_edit.setText(self._fmt(self._y_from_si(old_value)))
            if old_si is not None:
                self._fill_grid(*old_si)
        finally:
            self._loading = False
        self._update_headers()
        self._update_preview()

    def _update_si_note(self) -> None:
        """Say, when the display units are not SI, that expressions are written in SI."""
        settings = self.settings
        used = [q for q in (self.quantity, "time", "length", "temperature") if q is not None]
        if all(is_si(q, settings) for q in used):
            self.si_note.setText("")
            self.si_note.setVisible(False)
            return
        result = f" Result in {si_label(self.quantity)}." if self.quantity else ""
        self.si_note.setText(
            f"Expressions are always in SI: t [s], x, y [m], T [K].{result}"
        )
        self.si_note.setVisible(True)

    def _y_to_si(self, value: float) -> float:
        return float(to_si(value, self.quantity, self.settings)) if self.quantity else value

    def _y_from_si(self, value: float) -> float:
        return float(from_si(value, self.quantity, self.settings)) if self.quantity else value

    def _x_quantity(self) -> str:
        return "temperature" if self.variable_combo.currentData() == "T" else "time"

    def _x_to_si(self, value: float) -> float:
        return float(to_si(value, self._x_quantity(), self.settings))

    def _x_from_si(self, value: float) -> float:
        return float(from_si(value, self._x_quantity(), self.settings))

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:.10g}"

    def _update_headers(self) -> None:
        xq = self._x_quantity()
        ylabel = unit_label(self.quantity, self.settings)
        xlabel = unit_label(xq, self.settings)
        self.grid.setHorizontalHeaderLabels(
            [f"{self.variable_combo.currentData()} [{xlabel}]", f"value [{ylabel}]"]
        )

    # ---------------------------------------------------------------- public API
    @property
    def mode(self) -> str:
        """The current mode: ``constant``, ``table``, ``expression`` or ``none``."""
        return str(self.mode_combo.currentData())

    def function(self) -> Function | None:
        """The last valid function (``None`` in "None" mode or before any)."""
        return self._function

    def error_text(self) -> str:
        """The message of the current input error ("" when the input is valid)."""
        return self._error

    def set_function(self, function: Function | None) -> None:
        """Show ``function`` without emitting :attr:`function_changed`."""
        self._loading = True
        try:
            with QSignalBlocker(self.mode_combo):
                if function is None:
                    self._select_mode("none" if self.optional else "constant")
                elif isinstance(function, Table):
                    if self.mode_combo.findData("table") < 0:  # a table this field has no use for
                        self.mode_combo.addItem(_MODE_LABELS["table"], "table")
                    self._select_mode("table")
                    with QSignalBlocker(self.variable_combo):
                        if self.variable_combo.findData(function.variable) < 0:
                            # shown as it is (an old file); the error says it is not allowed
                            self.variable_combo.addItem(
                                _VARIABLE_LABELS[function.variable], function.variable
                            )
                        self.variable_combo.setCurrentIndex(
                            self.variable_combo.findData(function.variable)
                        )
                    self.extrapolate_combo.setCurrentIndex(
                        self.extrapolate_combo.findData(function.extrapolate)
                    )
                    self._update_headers()
                    self._fill_grid(function.xs, function.ys)
                elif isinstance(function, Expression):
                    self._select_mode("expression")
                    self.expr_edit.setText(function.text)
                elif isinstance(function, Constant):
                    self._select_mode("constant")
                    self.value_edit.setText(self._fmt(self._y_from_si(function.value)))
                else:  # a user-defined Function: shown as an expression-less constant
                    self._select_mode("constant")
                    self.value_edit.setText(self._fmt(self._y_from_si(float(function()))))
            self._function = function
            self._set_error(self._variable_error(function) or "")
            self._update_preview()
        finally:
            self._loading = False

    def commit(self) -> None:
        """Validate the current input; emit :attr:`function_changed` if valid and new."""
        if self._loading:
            return
        try:
            function = self._evaluate()
        except (ModelError, ValueError) as exc:
            self._set_error(str(exc))
            self._update_preview()
            return
        self._set_error("")
        self._update_preview()
        if same_function(function, self._function):
            return
        self._function = function
        self.function_changed.emit(function)

    # ------------------------------------------------------------------ internals
    def _select_mode(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(index)
        self._show_mode(mode)

    def _show_mode(self, mode: str) -> None:
        page = {"constant": 0, "table": 1, "expression": 2, "none": 3}[mode]
        # a stacked widget is as tall as its tallest page: let the hidden pages ignore their
        # size, or a constant leaves the room of the table and its preview empty
        ignored, preferred = QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        for index in range(self.stack.count()):
            policy = preferred if index == page else ignored
            self.stack.widget(index).setSizePolicy(policy, policy)
        self.stack.setCurrentIndex(page)
        self.stack.adjustSize()
        self.stack.updateGeometry()

    def _on_mode_changed(self, _index: int) -> None:
        if self._loading:
            return
        mode = self.mode
        self._show_mode(mode)
        current = self._function
        if isinstance(current, Constant):  # carry the value over to the new mode
            if mode == "table" and self.grid.rowCount() == 0:
                self._loading = True
                self._fill_grid([0.0], [current.value])
                self._loading = False
            elif mode == "expression" and not self.expr_edit.text().strip():
                self.expr_edit.setText(self._fmt(current.value))
        self.commit()

    def _constant_si(self) -> float | None:
        try:
            return self._y_to_si(parse_number(self.value_edit.text()))
        except ValueError:
            return None

    def _table_si_rows(self) -> tuple[list[float], list[float]] | None:
        try:
            rows = self._grid_rows()
        except ValueError:
            return None
        if not rows:
            return None
        return [self._x_to_si(x) for x, _ in rows], [self._y_to_si(y) for _, y in rows]

    def _cell(self, row: int, col: int) -> str:
        item = self.grid.item(row, col)
        return item.text().strip() if item is not None else ""

    def _grid_rows(self) -> list[tuple[float, float]]:
        """Display-unit ``(x, y)`` of every non-blank row; ``ValueError`` if malformed."""
        rows = []
        for r in range(self.grid.rowCount()):
            sx, sy = self._cell(r, 0), self._cell(r, 1)
            if not sx and not sy:
                continue
            try:
                rows.append((parse_number(sx), parse_number(sy)))
            except ValueError:
                raise ValueError(f"table row {r + 1}: enter two numbers") from None
        return rows

    def _fill_grid(self, xs: list[float], ys: list[float]) -> None:
        """Show SI ``xs`` / ``ys`` in the grid (display units); no signals."""
        with QSignalBlocker(self.grid):
            self.grid.setRowCount(len(xs))
            for r, (x, y) in enumerate(zip(xs, ys, strict=True)):
                self.grid.setItem(r, 0, QTableWidgetItem(self._fmt(self._x_from_si(x))))
                self.grid.setItem(r, 1, QTableWidgetItem(self._fmt(self._y_from_si(y))))

    def _variable_error(self, function: Function | None) -> str | None:
        """The message if ``function`` uses a variable this field does not allow."""
        allowed = self.variables
        if allowed is None:
            return None
        bad = False
        if isinstance(function, Table):
            bad = function.variable not in allowed
        elif isinstance(function, Expression):
            bad = (
                (function.depends_on_T and "T" not in allowed)
                or (function.depends_on_time and "t" not in allowed)
                or (function.depends_on_position and not {"x", "y"} & set(allowed))
            )
        if not bad:
            return None
        return f"this value may depend on {_allowed_words(allowed)} only"

    def _evaluate(self) -> Function | None:
        function = self._evaluate_input()
        message = self._variable_error(function)
        if message:
            raise ValueError(message)
        return function

    def _evaluate_input(self) -> Function | None:
        mode = self.mode
        if mode == "none":
            return None
        if mode == "constant":
            try:
                value = self._y_to_si(parse_number(self.value_edit.text()))
            except ValueError:
                raise ValueError("enter a number") from None
            self._check_limits(value)
            return Constant(value)
        if mode == "expression":
            return Expression(self.expr_edit.text())
        rows = self._grid_rows()
        ys = [self._y_to_si(y) for _, y in rows]
        for value in ys:  # the limits apply to every table value (the dependent ones)
            self._check_limits(value)
        return Table(
            [self._x_to_si(x) for x, _ in rows],
            ys,
            self.variable_combo.currentData(),
            self.extrapolate_combo.currentData(),
        )

    def _check_limits(self, value: float) -> None:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"value must be at least {self._limit_text(self.minimum)}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"value must be at most {self._limit_text(self.maximum)}")

    def _limit_text(self, si_value: float) -> str:
        shown = self._fmt(self._y_from_si(si_value))
        return f"{shown} {unit_label(self.quantity, self.settings)}".strip()

    def _check_live(self, *_args: object) -> None:
        """Validate while typing: mark the field, never emit."""
        if self._loading:
            return
        try:
            self._evaluate()
        except (ModelError, ValueError) as exc:
            self._set_error(str(exc))
        else:
            self._set_error("")

    def _set_error(self, message: str) -> None:
        self._error = message
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        for edit, tip in ((self.value_edit, ""), (self.expr_edit, self._expression_tip)):
            bad = bool(message) and edit.isVisibleTo(self)
            edit.setStyleSheet(_BAD_STYLE if bad else "")
            edit.setToolTip(message if bad else tip)

    def _update_preview(self) -> None:
        if self.mode != "table":
            return
        try:
            rows = self._grid_rows()
        except ValueError:
            rows = []
        rows.sort()
        xq = unit_label(self._x_quantity(), self.settings)
        yq = unit_label(self.quantity, self.settings)
        self.preview.plot(
            [x for x, _ in rows],
            [y for _, y in rows],
            f"{self.variable_combo.currentData()} [{xq}]",
            f"value [{yq}]" if yq else "value",
        )

    # --------------------------------------------------------------------- table
    def add_row(self) -> None:
        """Append a blank row (blank rows are ignored)."""
        with QSignalBlocker(self.grid):
            r = self.grid.rowCount()
            self.grid.setRowCount(r + 1)
            self.grid.setItem(r, 0, QTableWidgetItem(""))
            self.grid.setItem(r, 1, QTableWidgetItem(""))

    def remove_selected_rows(self) -> None:
        """Remove the selected rows (or the last row if none is selected)."""
        rows = sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True)
        if not rows and self.grid.rowCount():
            rows = [self.grid.rowCount() - 1]
        for r in rows:
            self.grid.removeRow(r)
        self.commit()

    def paste_text(self, text: str) -> bool:
        """Replace the grid by pasted text (see the module docstring); emit if valid.

        Returns
        -------
        bool
            ``True`` if the text was accepted.
        """
        try:
            rows = parse_pasted(text)
        except ValueError as exc:
            self._set_error(f"paste rejected: {exc}")
            return False
        with QSignalBlocker(self.grid):
            self.grid.setRowCount(len(rows))
            for r, (x, y) in enumerate(rows):
                self.grid.setItem(r, 0, QTableWidgetItem(self._fmt(x)))
                self.grid.setItem(r, 1, QTableWidgetItem(self._fmt(y)))
        self.commit()
        return True

    def paste_from_clipboard(self) -> None:
        """Paste the clipboard text into the grid."""
        self.paste_text(QGuiApplication.clipboard().text())

    def _on_cell_changed(self, _item: Any) -> None:
        self.commit()

    def _on_table_option_changed(self, _index: int) -> None:
        if self._loading:
            return
        self._update_headers()
        self.commit()


def same_function(a: Function | None, b: Function | None) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return function_to_json(a) == function_to_json(b)
    except ModelError:
        return a is b
