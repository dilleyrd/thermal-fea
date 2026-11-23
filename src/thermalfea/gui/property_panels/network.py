"""Table editor of the flow network (Plan M8.12).

:class:`NetworkPanel` is shown for the address ``("network",)`` (the Flow > Network node). With
no network in the model it offers "Create network"; otherwise two tables edit the nodes
(id, pressure [Pa], inflow [kg/s]) and the branches (id, from, to, kind, length [m], K_minor,
stream). Node and branch references are combo boxes of the existing ids; the stream column
lists the model's streams with "(none)" for no stream.

Every committed change, add and removal is one ``Document.edit`` (one undo step). An invalid
number or id is marked red, shown in the status label and not applied. A node that a branch
still uses cannot be removed (the status label says which branch). The tables are reloaded
from the model on every ``model_changed``, so undo and redo keep them in sync; reloading never
applies anything.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import unit_label
from thermalfea.core.units import UnitSettings, from_si, to_si
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.model.bcs import FlowNetwork, NetBranch, NetNode

#: Address of the flow network object (``Model.network``).
NETWORK_ADDRESS: Address = ("network",)
NODE_COLUMNS = ("Id", "Pressure [Pa]", "Inflow [kg/s]")
BRANCH_COLUMNS = ("Id", "From", "To", "Kind", "Length [m]", "K minor", "Stream")
#: Header text (without unit) and quantity of the numeric columns; the unit label of the
#: display settings is appended.
_NODE_UNITS = {1: ("Pressure", "pressure"), 2: ("Inflow", "mass_flow")}
_BRANCH_UNITS = {4: ("Length", "length")}
KINDS = ("duct", "loss")
NONE_TEXT = "(none)"
_BAD = QColor("#ffd0d0")
_GOOD = QColor("#ffffff")


def parse_number(
    text: str,
    *,
    optional: bool = False,
    minimum: float | None = None,
    quantity: str | None = None,
    units: UnitSettings | None = None,
) -> float | None:
    """Parse one finite number of a table cell.

    Parameters
    ----------
    text : str
        The cell text; blank means ``None`` when ``optional``.
    optional : bool
        Whether a blank cell is allowed.
    minimum : float, optional
        Smallest accepted value (SI).
    quantity : str, optional
        Quantity of the cell; with ``units`` the typed number is converted to SI.
    units : UnitSettings, optional
        Display units of the typed number.

    Raises
    ------
    ValueError
        With a message for the user if the text is not an allowed number.
    """
    stripped = text.strip()
    if not stripped:
        if optional:
            return None
        raise ValueError("a number is required")
    # a single comma is a decimal point when there is no dot ("0,5")
    number = stripped
    if "." not in stripped and stripped.count(",") == 1:
        number = stripped.replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        raise ValueError(f"{stripped!r} is not a number") from None
    if not math.isfinite(value):
        raise ValueError(f"{stripped!r} is not a finite number")
    if quantity is not None and units is not None:
        value = float(to_si(value, quantity, units))
    if minimum is not None and value < minimum:
        # the bound in the unit the number was typed in
        shown, suffix = minimum, ""
        if quantity is not None and units is not None:
            shown = float(from_si(minimum, quantity, units))
            label = unit_label(quantity, units)
            suffix = f" {label}" if label else ""
        raise ValueError(f"must be at least {shown:g}{suffix}")
    return value


def _show(value: float | None) -> str:
    return "" if value is None else f"{value:.10g}"


def _next_id(prefix: str, used: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


class NetworkPanel(QWidget):
    """Node and branch tables of the flow network of the model.

    Parameters
    ----------
    document : Document
        Receives every change through ``document.edit``.
    parent : QWidget, optional

    Attributes
    ----------
    create_button, remove_network_button : QPushButton
    add_node_button, remove_node_button, add_branch_button, remove_branch_button : QPushButton
    node_table, branch_table : QTableWidget
    status_label : QLabel
        The last refusal or error ("" when none).
    """

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.address: Address = NETWORK_ADDRESS
        self._loading = False

        outer = QVBoxLayout(self)
        title = QLabel("Flow network")
        title.setStyleSheet("font-weight: bold;")
        outer.addWidget(title)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #b00020;")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.empty_widget = QWidget()
        empty = QVBoxLayout(self.empty_widget)
        empty.addWidget(QLabel("The model has no flow network. Create one to add nodes."))
        self.create_button = QPushButton("Create network")
        self.create_button.clicked.connect(lambda _c=False: self.create_network())
        empty.addWidget(self.create_button)
        empty.addStretch(1)
        outer.addWidget(self.empty_widget)

        self.editor_widget = QWidget()
        editor = QVBoxLayout(self.editor_widget)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.addWidget(QLabel("Nodes"))
        self.node_table = self._make_table(NODE_COLUMNS)
        editor.addWidget(self.node_table)
        node_row = QHBoxLayout()
        self.add_node_button = QPushButton("Add node")
        self.remove_node_button = QPushButton("Remove node")
        node_row.addWidget(self.add_node_button)
        node_row.addWidget(self.remove_node_button)
        editor.addLayout(node_row)
        editor.addWidget(QLabel("Branches"))
        self.branch_table = self._make_table(BRANCH_COLUMNS)
        editor.addWidget(self.branch_table)
        branch_row = QHBoxLayout()
        self.add_branch_button = QPushButton("Add branch")
        self.remove_branch_button = QPushButton("Remove branch")
        branch_row.addWidget(self.add_branch_button)
        branch_row.addWidget(self.remove_branch_button)
        editor.addLayout(branch_row)
        self.remove_network_button = QPushButton("Remove network")
        editor.addWidget(self.remove_network_button)
        outer.addWidget(self.editor_widget)
        outer.addStretch(1)

        self.add_node_button.clicked.connect(lambda _c=False: self.add_node())
        self.remove_node_button.clicked.connect(lambda _c=False: self.remove_node())
        self.add_branch_button.clicked.connect(lambda _c=False: self.add_branch())
        self.remove_branch_button.clicked.connect(lambda _c=False: self.remove_branch())
        self.remove_network_button.clicked.connect(lambda _c=False: self.remove_network())
        self.node_table.itemChanged.connect(self._on_node_item)
        self.branch_table.itemChanged.connect(self._on_branch_item)
        document.model_changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _make_table(columns: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        table.verticalHeader().setVisible(False)
        return table

    # ------------------------------------------------------------------- loading
    def network(self) -> FlowNetwork | None:
        """The network of the document's current model (``None`` if there is none)."""
        return self.document.model.network

    def refresh(self) -> None:
        """Reload both tables from the model; applies nothing."""
        network = self.network()
        self._loading = True
        try:
            self._set_headers()
            has_network = network is not None
            self.empty_widget.setVisible(not has_network)
            self.editor_widget.setVisible(has_network)
            if network is None:
                self.node_table.setRowCount(0)
                self.branch_table.setRowCount(0)
                return
            self._fill_nodes(network)
            self._fill_branches(network)
        finally:
            self._loading = False

    def _shown(self, value: float | None, quantity: str) -> str:
        """Cell text of an SI value in the display unit of ``quantity``."""
        if value is None:
            return ""
        return _show(float(from_si(value, quantity, self.document.model.display_units)))

    def _set_headers(self) -> None:
        units = self.document.model.display_units
        for table, columns, unit_columns in (
            (self.node_table, NODE_COLUMNS, _NODE_UNITS),
            (self.branch_table, BRANCH_COLUMNS, _BRANCH_UNITS),
        ):
            labels = list(columns)
            for column, (text, quantity) in unit_columns.items():
                labels[column] = f"{text} [{unit_label(quantity, units)}]"
            table.setHorizontalHeaderLabels(labels)

    def _fill_nodes(self, network: FlowNetwork) -> None:
        table = self.node_table
        table.setRowCount(len(network.nodes))
        for row, node in enumerate(network.nodes):
            table.setItem(row, 0, QTableWidgetItem(node.id))
            table.setItem(row, 1, QTableWidgetItem(self._shown(node.pressure, "pressure")))
            table.setItem(row, 2, QTableWidgetItem(self._shown(node.inflow, "mass_flow")))

    def _fill_branches(self, network: FlowNetwork) -> None:
        table = self.branch_table
        table.setRowCount(len(network.branches))
        node_ids = [node.id for node in network.nodes]
        stream_names = [stream.name for stream in self.document.model.streams]
        for row, branch in enumerate(network.branches):
            table.setItem(row, 0, QTableWidgetItem(branch.id))
            table.setCellWidget(row, 1, self._combo(
                node_ids, branch.node_from,
                lambda v, r=row: self._edit_branch(r, "node_from", v),
            ))  # fmt: skip
            table.setCellWidget(row, 2, self._combo(
                node_ids, branch.node_to,
                lambda v, r=row: self._edit_branch(r, "node_to", v),
            ))  # fmt: skip
            table.setCellWidget(row, 3, self._combo(
                list(KINDS), branch.kind,
                lambda v, r=row: self._edit_branch(r, "kind", v),
            ))  # fmt: skip
            table.setItem(row, 4, QTableWidgetItem(self._shown(branch.length, "length")))
            table.setItem(row, 5, QTableWidgetItem(_show(branch.K_minor)))
            table.setCellWidget(row, 6, self._combo(
                stream_names, branch.stream,
                lambda v, r=row: self._edit_branch(r, "stream", v),
                none_text=NONE_TEXT,
            ))  # fmt: skip

    @staticmethod
    def _combo(
        items: list[str],
        current: str | None,
        on_pick: Callable[[str | None], None],
        none_text: str | None = None,
    ) -> QComboBox:
        """A combo of ``items`` (preceded by ``None`` when ``none_text``) showing ``current``.

        A current value that is not in the list is kept as an extra entry, never replaced.
        """
        entries: list[str | None] = [None, *items] if none_text is not None else list(items)
        if current is not None and current not in entries:
            entries.append(current)
        combo = QComboBox()
        for entry in entries:
            combo.addItem(none_text if entry is None else str(entry))
        combo.setCurrentIndex(entries.index(current) if current in entries else 0)
        combo.activated.connect(lambda i, e=entries: on_pick(e[i]))
        return combo

    # ------------------------------------------------------------------ marking
    def _mark(self, item: QTableWidgetItem, message: str) -> None:
        self._loading = True
        try:
            item.setBackground(_BAD if message else _GOOD)
            item.setToolTip(message)
        finally:
            self._loading = False

    def _reject(self, item: QTableWidgetItem, message: str) -> None:
        self._mark(item, message)
        self.status_label.setText(message)

    def _edit(self, text: str, mutate: Callable[[Any], None]) -> bool:
        """One undo step; a refusal of the model goes to the status label."""
        try:
            changed = self.document.edit(text, mutate)
        except ModelError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText("")
        return changed

    # ------------------------------------------------------------- cell changes
    def _on_node_item(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        network = self.network()
        row, column = item.row(), item.column()
        if network is None or row >= len(network.nodes):
            return
        if column == 0:
            new_id = item.text().strip()
            others = {n.id for i, n in enumerate(network.nodes) if i != row}
            if not new_id or new_id in others:
                self._reject(item, f"node id {new_id!r} is empty or already used")
                return
            old_id = network.nodes[row].id

            def rename(model: Any) -> None:
                net = model.network
                net.nodes[row].id = new_id
                for branch in net.branches:
                    if branch.node_from == old_id:
                        branch.node_from = new_id
                    if branch.node_to == old_id:
                        branch.node_to = new_id

            self._apply(item, "Rename node", rename)
            return
        try:
            value = parse_number(
                item.text(), optional=True, quantity=_NODE_UNITS[column][1],
                units=self.document.model.display_units,
            )
        except ValueError as exc:
            self._reject(item, str(exc))
            return
        field = "pressure" if column == 1 else "inflow"

        def set_value(model: Any) -> None:
            setattr(model.network.nodes[row], field, value)

        self._apply(item, "Edit node", set_value)

    def _on_branch_item(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        network = self.network()
        row, column = item.row(), item.column()
        if network is None or row >= len(network.branches):
            return
        if column == 0:
            new_id = item.text().strip()
            others = {b.id for i, b in enumerate(network.branches) if i != row}
            if not new_id or new_id in others:
                self._reject(item, f"branch id {new_id!r} is empty or already used")
                return
            self._apply(
                item, "Rename branch",
                lambda model: setattr(model.network.branches[row], "id", new_id),
            )  # fmt: skip
            return
        try:
            value = parse_number(
                item.text(), minimum=0.0,
                quantity="length" if column == 4 else None,
                units=self.document.model.display_units,
            )
        except ValueError as exc:
            self._reject(item, str(exc))
            return
        field = "length" if column == 4 else "K_minor"
        self._apply(
            item, f"Edit branch {field}",
            lambda model: setattr(model.network.branches[row], field, value),
        )  # fmt: skip

    def _apply(self, item: QTableWidgetItem, text: str, mutate: Callable[[Any], None]) -> None:
        """Apply a cell change; a refusal marks the cell. (An applied change rebuilds the
        table through ``model_changed``, which deletes ``item``, so it is not touched.)"""
        try:
            self.document.edit(text, mutate)
        except ModelError as exc:
            self._reject(item, str(exc))
            return
        self.status_label.setText("")

    def _edit_branch(self, row: int, field: str, value: str | None) -> None:
        def mutate(model: Any) -> None:
            if model.network is None:
                raise ModelError("the model has no flow network")
            setattr(model.network.branches[row], field, value)

        self._edit(f"Edit branch {field}", mutate)

    # --------------------------------------------------------------- add/remove
    def create_network(self) -> bool:
        """Set ``model.network`` to an empty :class:`FlowNetwork` (one undo step)."""
        return self._edit("Create network", lambda model: setattr(model, "network", FlowNetwork()))

    def remove_network(self) -> bool:
        """Remove the whole network (one undo step)."""
        return self._edit("Remove network", lambda model: setattr(model, "network", None))

    def add_node(self) -> bool:
        """Append a node with a fresh id "N<n>" and no pressure or inflow (one undo step)."""
        network = self.network()
        if network is None:
            self.status_label.setText("create the network first")
            return False
        new_id = _next_id("N", {n.id for n in network.nodes})

        def mutate(model: Any) -> None:
            if model.network is None:
                raise ModelError("create the network first")
            model.network.nodes.append(NetNode(new_id))

        return self._edit("Add node", mutate)

    def remove_node(self) -> bool:
        """Remove the selected node; refused while a branch uses it."""
        network = self.network()
        row = self.node_table.currentRow()
        if network is None or not 0 <= row < len(network.nodes):
            self.status_label.setText("select a node to remove")
            return False
        node_id = network.nodes[row].id
        for branch in network.branches:
            if node_id in (branch.node_from, branch.node_to):
                self.status_label.setText(
                    f"node {node_id!r} is used by branch {branch.id!r}; change or remove the "
                    "branch first"
                )
                return False

        def mutate(model: Any) -> None:
            del model.network.nodes[row]

        return self._edit("Remove node", mutate)

    def add_branch(self) -> bool:
        """Append a branch between the first two nodes (one undo step)."""
        network = self.network()
        if network is None or len(network.nodes) < 2:  # noqa: PLR2004
            self.status_label.setText("add two nodes before adding a branch")
            return False
        new_id = _next_id("B", {b.id for b in network.branches})
        node_from, node_to = network.nodes[0].id, network.nodes[1].id

        def mutate(model: Any) -> None:
            if model.network is None:
                raise ModelError("create the network first")
            model.network.branches.append(NetBranch(new_id, node_from, node_to))

        return self._edit("Add branch", mutate)

    def remove_branch(self) -> bool:
        """Remove the selected branch (one undo step)."""
        network = self.network()
        row = self.branch_table.currentRow()
        if network is None or not 0 <= row < len(network.branches):
            self.status_label.setText("select a branch to remove")
            return False

        def mutate(model: Any) -> None:
            del model.network.branches[row]

        return self._edit("Remove branch", mutate)
