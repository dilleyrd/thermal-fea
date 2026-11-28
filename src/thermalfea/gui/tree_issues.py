"""Problems marked in the model tree (convention C13, task M11.78).

A tree item that Validate would complain about carries the warning icon, and its tooltip
lists the messages ("error: ..." / "warning: ..."). The marks follow the edits: a single-shot
timer (:data:`DEBOUNCE_MS`) restarted on every change of the model, the build, the mesh or
their staleness runs the validation, so typing does not validate on every keystroke.

What is run
-----------
With a current built geometry (and the mesh when it is current) the full
:func:`~thermalfea.model.validate.validate` runs, as the Validate command does. Without one
(nothing built yet, or the build is stale) :func:`~thermalfea.model.validate.validate_model`
runs: the checks that need only the model. A load with an empty selection, a part without a
material or a material with a property not set are found either way. A failure of the
validation itself clears the marks; it never reaches the user from here.

Where a mark goes
-----------------
The item of :func:`~thermalfea.gui.issues.address_for_issue`; when the issue has no address
or the tree has no such item, the section item of the issue's kind (a load -> *Loads &
Boundary Conditions*), else nothing. An item with several issues gets one mark. The icon and
tooltip an item had are kept in the item and put back when its mark goes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QTreeWidgetItem

from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.icons import icon
from thermalfea.gui.issues import address_for_issue
from thermalfea.model.validate import Issue, validate, validate_model

if TYPE_CHECKING:
    from thermalfea.gui.document import Document
    from thermalfea.gui.main_window import MainWindow
    from thermalfea.gui.tree import ModelTree

_log = logging.getLogger(__name__)

#: Milliseconds the model must stay unchanged before it is validated.
DEBOUNCE_MS = 300
#: ``Issue.kind`` -> section key of the tree, for an issue without an item of its own.
_SECTION_OF_KIND: dict[str, str] = {
    "bc": "loads",
    "boundary condition": "loads",
    "model": "loads",  # e.g. no temperature reference
    "stream": "streams",
    "network": "network",
    "enclosure": "enclosures",
    "contact": "contacts",
    "material": "materials",
    "region": "regions",
    "selection": "selections",
    "mesh": "mesh",
    "solution": "analysis",
}
_SAVED = Qt.ItemDataRole.UserRole + 1  # (icon, tooltip) an item had before it was marked


class TreeIssueController(QObject):
    """Validates after a pause and marks the tree items that have issues.

    Parameters
    ----------
    document : Document
    tree : ModelTree
    parent : QObject, optional

    Attributes
    ----------
    issues : list of Issue
        The issues of the last validation (empty after a failure).
    timer : QTimer
        The single-shot debounce timer.
    """

    def __init__(self, document: Document, tree: ModelTree, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.tree = tree
        self.issues: list[Issue] = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)
        self.timer.timeout.connect(self.refresh)
        for signal in (document.model_changed, document.geometry_built, document.mesh_changed,
                       document.stale_changed):
            signal.connect(self.schedule)
        # the tree creates new items on a rebuild: put the marks of the last run on them at once
        tree.rebuilt.connect(self.apply)
        self.schedule()

    def schedule(self) -> None:
        """(Re)start the debounce timer."""
        self.timer.start()

    def validate(self) -> list[Issue]:
        """Validate as far as the document allows; ``[]`` if the validation itself fails."""
        document = self.document
        try:
            if document.built is not None and not document.geometry_stale:
                mesh = document.mesh if not document.mesh_stale else None
                return validate(document.model, document.built, mesh)
            return validate_model(document.model)
        except ThermalFEAError as exc:
            _log.warning("Validation for the tree marks failed: %s", exc)
            return []

    def refresh(self) -> None:
        """Validate now and mark the items."""
        self.timer.stop()
        self.issues = self.validate()
        self.apply()

    def apply(self) -> None:
        """Put the marks of :attr:`issues` on the current items (and take the others off)."""
        found: dict[int, tuple[QTreeWidgetItem, list[Issue]]] = {}
        for issue in self.issues:
            item = self._item_of(issue)
            if item is not None:
                found.setdefault(id(item), (item, []))[1].append(issue)
        blocked = self.tree.blockSignals(True)  # setIcon/setToolTip must not look like a rename
        try:
            self._walk_clear(found)
            for item, issues in found.values():
                self._mark(item, issues)
        finally:
            self.tree.blockSignals(blocked)

    # ------------------------------------------------------------------ internals
    def _item_of(self, issue: Issue) -> QTreeWidgetItem | None:
        tree = self.tree
        address = address_for_issue(self.document.model, issue)
        if address is not None:
            if address[0] == "section":
                return self._section(address[1])
            item = tree.item_for(address)
            if item is not None:
                return item
        key = _SECTION_OF_KIND.get(issue.kind)
        return self._section(key) if key is not None else None

    def _section(self, key: str) -> QTreeWidgetItem | None:
        try:
            return self.tree.section_item(key)
        except KeyError:
            return None

    def _walk_clear(self, keep: dict[int, Any]) -> None:
        def walk(item: QTreeWidgetItem) -> None:
            if id(item) not in keep:
                self._unmark(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    @staticmethod
    def _mark(item: QTreeWidgetItem, issues: list[Issue]) -> None:
        saved = item.data(0, _SAVED)
        if saved is None:  # keep what the tree gave the item, once
            saved = (item.icon(0), item.toolTip(0))
            item.setData(0, _SAVED, saved)
        lines = [f"{i.severity}: {i.message}" for i in issues]
        original = saved[1]
        item.setIcon(0, icon("warning"))
        item.setToolTip(0, "\n".join([*lines, original] if original else lines))

    @staticmethod
    def _unmark(item: QTreeWidgetItem) -> None:
        saved = item.data(0, _SAVED)
        if saved is None:
            return
        previous: QIcon = saved[0]
        item.setIcon(0, previous)
        item.setToolTip(0, saved[1])
        item.setData(0, _SAVED, None)


def attach_tree_issues(
    window: MainWindow, document: Document, tree: ModelTree
) -> TreeIssueController:
    """Mark the tree items that have validation issues (C13); lives as long as ``window``."""
    controller = TreeIssueController(document, tree, window)
    window.tree_issues = controller  # type: ignore[attr-defined]
    return controller
