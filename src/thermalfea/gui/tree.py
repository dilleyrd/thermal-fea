"""The model tree (Plan M8.4): the objects of the model, with context-menu actions.

Top-level nodes: Geometry, Materials, Regions, Selections, Mesh, Initial Condition, Loads & Boundary
Conditions, Flow (Streams, Network), Enclosures, Analysis Settings, Solution. While Contacts,
Flow and Enclosures are all empty they fold into one dimmed node (M11.51). The tree is
rebuilt from ``document.model`` on every ``model_changed``; expansion and the current item
survive a rebuild.

Every action is a method that edits through ``Document.edit`` (one undo step each) and is
offered by :meth:`ModelTree.actions_for`, which the context menu and the tests both use.
The "Add" entries of the loads node come from the boundary-condition registry: one per
registered class, titled by its :class:`~thermalfea.core.forms.FormSpec`, so a newly
registered load appears without editing this module.

Objects are identified by addresses (:mod:`thermalfea.gui.addressing`);
:attr:`ModelTree.object_selected` emits the address of the current item, or
``("section", key)`` for a node that is not an object.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QKeyEvent, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from thermalfea.core import registry
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import copy_name, default_instance, form_for, unique_name
from thermalfea.gui.addressing import Address, exists, resolve
from thermalfea.gui.dialogs.new_load import LOAD_DIALOGS
from thermalfea.gui.dialogs.new_stream import NewStreamDialog
from thermalfea.gui.document import Document
from thermalfea.gui.part_colors import color_of_material, color_of_part
from thermalfea.gui.tree_summary import summary_for
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Contact, FlowNetwork, Stream
from thermalfea.model.geometry_edit import dependents, rename_operation
from thermalfea.model.model import Model, RegionAssignment, check_part_name, part_name
from thermalfea.model.selections import (
    ALL_SELECTION,
    delete_selection,
    rename_selection,
    selection_users,
)
from thermalfea.model.vocabulary import entity_word

#: ``(key, title)`` of the top-level nodes, in display order.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("geometry", "Geometry"),
    ("regions", "Parts"),
    ("selections", "Selections"),
    ("materials", "Materials"),
    ("mesh", "Mesh"),
    ("initial", "Initial Condition"),
    ("loads", "Loads & Boundary Conditions"),
    ("contacts", "Contacts"),
    ("flow", "Flow"),
    ("enclosures", "Enclosures"),
    ("analysis", "Analysis Settings"),
    ("solution", "Results"),
)
#: Section key -> address of the settings object the node itself edits.
SECTION_OBJECTS: dict[str, Address] = {
    "mesh": ("mesh_settings",),
    "initial": ("initial_condition",),
    "analysis": ("solution",),
}
#: Model lists of objects that can be renamed, duplicated and deleted.
_NAMED_LISTS = ("bcs", "streams", "enclosures", "contacts")
#: Sections folded into one node while all of them are empty (M11.51), and its title.
FOLDED_SECTIONS: tuple[str, ...] = ("contacts", "flow", "enclosures")
FOLDED_TITLE = "Contacts · Flow · Enclosures"
_SUPPRESSED_BRUSH = QBrush(QColor("#808080"))
_ROLE = Qt.ItemDataRole.UserRole
_ROLE_ICONS: dict[str, QIcon] = {}


def role_icon(role: str) -> QIcon:
    """A small glyph of an entity role: a square (part), a bar (boundary/edge), a dot (point)."""
    icon = _ROLE_ICONS.get(role)
    if icon is not None:
        return icon
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#4a78b0"))
    if role == "part":
        painter.drawRect(3, 3, 10, 10)
    elif role in ("boundary", "edge"):
        painter.drawRect(2, 6, 12, 4)
    else:
        painter.drawEllipse(5, 5, 6, 6)
    painter.end()
    icon = QIcon(pixmap)
    _ROLE_ICONS[role] = icon
    return icon


_SWATCHES: dict[str, QIcon] = {}


def swatch_icon(color: str) -> QIcon:
    """A small square of ``color``: the color a part or material has in the viewport."""
    icon = _SWATCHES.get(color)
    if icon is None:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QColor("#606060"))
        painter.setBrush(QColor(color))
        painter.drawRect(2, 2, 11, 11)
        painter.end()
        icon = _SWATCHES[color] = QIcon(pixmap)
    return icon


@dataclass(frozen=True)
class NodeRef:
    """What a tree item stands for.

    Attributes
    ----------
    section : str
        Key of the section node, or of the section an object belongs to.
    address : tuple or None
        Address of the object; ``None`` for a plain section node.
    """

    section: str
    address: Address | None = None


def _default_menu_executor(menu: QMenu, global_pos: QPoint) -> None:
    menu.exec(global_pos)


class ModelTree(QTreeWidget):
    """Tree of the model's objects.

    Parameters
    ----------
    document : Document
    parent : QWidget, optional

    Signals
    -------
    object_selected(object)
        The current item changed by user action; see the module docstring.
    rebuilt()
        :meth:`rebuild` finished (the items are new objects).
    error_occurred(str)
        An action was refused (the message says why).
    edit_requested(object)
        "Edit" was chosen for a geometry operation (its address); the operation is also
        made current so the property panel shows its parameters.

    Attributes
    ----------
    menu_executor : callable
        ``menu_executor(menu, global_pos)`` shows a context menu; tests replace it.
    """

    object_selected = Signal(object)
    error_occurred = Signal(str)
    edit_requested = Signal(object)
    rebuilt = Signal()  # all items were created anew (marks on items must be applied again)

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.menu_executor: Callable[[QMenu, QPoint], None] = _default_menu_executor
        self._rebuilding = False
        self._expanded: dict[Any, bool] = {}
        self._actions: list[QAction] = []
        #: Providers of view objects shown under the Solution node (see :meth:`add_provider`).
        self.providers: list[Any] = []
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        # geometry operations replay in order: the history can never be reordered
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setAcceptDrops(False)
        self.setDragEnabled(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.currentItemChanged.connect(self._on_current_changed)
        self.itemChanged.connect(self._on_item_changed)
        self.itemExpanded.connect(lambda item: self._remember(item, True))
        self.itemCollapsed.connect(lambda item: self._remember(item, False))
        document.model_changed.connect(self.rebuild)
        for signal in (
            document.geometry_built,
            document.mesh_changed,
            document.results_changed,
            document.stale_changed,
        ):
            signal.connect(self.refresh_summaries)
        self.rebuild()

    def set_summary_visible(self, visible: bool) -> None:
        """Show or hide the summary column (column 1)."""
        self.setColumnHidden(1, not visible)

    def edit(self, index: Any, trigger: Any = None, event: Any = None) -> bool:
        """Only column 0 (the name) is ever edited."""
        if index.column() != 0:
            return False
        return super().edit(index, trigger, event)

    def refresh_summaries(self) -> None:
        """Set the summary text of every item (column 1) from the document state."""
        brush = self.palette().brush(QPalette.ColorRole.PlaceholderText)
        self._rebuilding = True
        self.blockSignals(True)
        try:

            def walk(item: QTreeWidgetItem) -> None:
                ref = self.ref_of(item)
                if ref is not None:
                    text = summary_for(self.document, ref.section, ref.address, self.providers)
                    item.setText(1, text)
                    item.setToolTip(1, text)
                    item.setForeground(1, brush)
                for i in range(item.childCount()):
                    walk(item.child(i))

            for i in range(self.topLevelItemCount()):
                walk(self.topLevelItem(i))
        finally:
            self.blockSignals(False)
            self._rebuilding = False

    def add_provider(self, provider: Any) -> None:
        """Let ``provider`` contribute objects under the Solution node and their actions.

        These objects are view state, not part of the model (the result displays of
        :mod:`thermalfea.gui.results_tools`). The provider offers:

        * ``objects_changed`` -- a signal; the tree rebuilds when it fires;
        * ``tree_items() -> list[(text, address, renameable)]`` -- the child items;
        * ``owns(address) -> bool`` -- whether an address belongs to it;
        * ``tree_actions(address or None) -> list[(text, slot, data)]`` -- the context-menu
          actions of the Solution node (``None``) or of one of its objects;
        * ``rename(address, new_name)`` -- inline rename; raises ``ModelError`` if refused.

        Parameters
        ----------
        provider : object
        """
        self.providers.append(provider)
        provider.objects_changed.connect(self.rebuild)
        self.rebuild()

    def _provider_of(self, address: Address | None) -> Any:
        if address is None:
            return None
        return next((p for p in self.providers if p.owns(address)), None)

    # -------------------------------------------------------------------- building
    def _remember(self, item: QTreeWidgetItem, expanded: bool) -> None:
        if not self._rebuilding:
            self._expanded[self._key(item)] = expanded

    def _key(self, item: QTreeWidgetItem) -> Any:
        ref = self.ref_of(item)
        return None if ref is None else (ref.section, ref.address)

    @staticmethod
    def ref_of(item: QTreeWidgetItem | None) -> NodeRef | None:
        """The :class:`NodeRef` of an item."""
        return None if item is None else item.data(0, _ROLE)

    def address_of(self, item: QTreeWidgetItem | None) -> Address | None:
        """The object address of an item (``None`` for a plain section node)."""
        ref = self.ref_of(item)
        return None if ref is None else ref.address

    def _make_item(
        self,
        parent: QTreeWidget | QTreeWidgetItem,
        text: str,
        ref: NodeRef,
        tooltip: str = "",
        renameable: bool = False,
        suppressed: bool = False,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, _ROLE, ref)
        flags = item.flags()
        if renameable:
            flags |= Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)
        if tooltip:
            item.setToolTip(0, tooltip)
        if suppressed:
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
            item.setForeground(0, _SUPPRESSED_BRUSH)
            item.setToolTip(0, (tooltip + " (suppressed)").strip())
        return item

    def rebuild(self) -> None:
        """Rebuild all items from the document's model, keeping expansion and current item."""
        current = self.address_of(self.currentItem())
        current_ref = self.ref_of(self.currentItem())
        self._rebuilding = True
        self.blockSignals(True)
        try:
            self.clear()
            self._populate(self.document.model)
            for i in range(self.topLevelItemCount()):
                self._restore_expansion(self.topLevelItem(i))
            target = None
            if current is not None:
                target = self.item_for(current)
            elif current_ref is not None:
                target = self._find_section(current_ref.section)
            if target is not None:
                self.setCurrentItem(target)
        finally:
            self.blockSignals(False)
            self._rebuilding = False
        self.refresh_summaries()
        self.rebuilt.emit()

    def _restore_expansion(self, item: QTreeWidgetItem) -> None:
        item.setExpanded(self._expanded.get(self._key(item), item.parent() is None))
        for i in range(item.childCount()):
            self._restore_expansion(item.child(i))

    @staticmethod
    def is_folded(model: Model) -> bool:
        """``True`` while Contacts, Flow and Enclosures are all empty (M11.51)."""
        return (
            not model.contacts
            and not model.streams
            and model.network is None
            and not model.enclosures
        )

    def _populate(self, model: Model) -> None:
        folded = self.is_folded(model)
        sections: dict[str, QTreeWidgetItem] = {}
        for key, title in SECTIONS:
            if folded and key in FOLDED_SECTIONS:
                if key == "contacts":  # one dimmed node takes the place of the three
                    self._make_folded_item(self)
                continue
            sections[key] = self._make_item(self, title, NodeRef(key, SECTION_OBJECTS.get(key)))
        for i, op in enumerate(model.geometry):
            self._make_item(
                sections["geometry"], op.id, NodeRef("geometry", ("geometry", i)),
                tooltip=type(op).__name__, renameable=True,
            )  # fmt: skip
        for name in model.materials:
            item = self._make_item(
                sections["materials"],
                name,
                NodeRef("materials", ("materials", name)),
                renameable=True,
            )
            item.setIcon(0, swatch_icon(color_of_material(name, model)))
        for i, region in enumerate(model.regions):
            item = self._make_item(
                sections["regions"], part_name(region), NodeRef("regions", ("regions", i)),
                tooltip=f"{region.selection or '(no selection)'} -> {region.material}",
                renameable=True,
            )  # fmt: skip
            item.setIcon(0, swatch_icon(color_of_part(i)))
        names = [n for n in model.selections if n != ALL_SELECTION]
        names += [n for n in model.selections if n == ALL_SELECTION]  # "all" last
        for name in names:
            item = self._make_item(
                sections["selections"], name, NodeRef("selections", ("selections", name)),
                renameable=name != ALL_SELECTION,
            )  # fmt: skip
            try:
                item.setIcon(0, role_icon(entity_word(model.selections[name].dim, model)))
            except ModelError:
                pass
        for i, bc in enumerate(model.bcs):
            title = self._title_of(type(bc))
            self._make_item(
                sections["loads"], bc.name, NodeRef("loads", ("bcs", i)), tooltip=title,
                renameable=True, suppressed=not bc.active,
            )  # fmt: skip
        for i, contact in enumerate(model.contacts):
            self._make_item(
                sections["contacts"], contact.name,
                NodeRef("contacts", ("contacts", i)), renameable=True,
            )  # fmt: skip
        if not folded:
            streams = self._make_item(sections["flow"], "Streams", NodeRef("streams"))
            for i, stream in enumerate(model.streams):
                self._make_item(
                    streams, stream.name, NodeRef("streams", ("streams", i)), renameable=True
                )
            self._make_item(sections["flow"], "Network", NodeRef("network", ("network",)))
            for i, enclosure in enumerate(model.enclosures):
                self._make_item(
                    sections["enclosures"], enclosure.name,
                    NodeRef("enclosures", ("enclosures", i)), renameable=True,
                )  # fmt: skip
        for provider in self.providers:
            for text, address, renameable in provider.tree_items():
                self._make_item(
                    sections["solution"],
                    text,
                    NodeRef("solution", address),
                    renameable=renameable,
                )

    def _make_folded_item(self, parent: QTreeWidget) -> QTreeWidgetItem:
        """The dimmed node standing for the folded sections (M11.51)."""
        item = self._make_item(
            parent, FOLDED_TITLE, NodeRef("folded"),
            tooltip="No contacts, streams, network or enclosures yet",
        )  # fmt: skip
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)
        item.setForeground(0, self.palette().brush(QPalette.ColorRole.PlaceholderText))
        return item

    @staticmethod
    def _title_of(cls: type) -> str:
        return form_for(cls).title

    # -------------------------------------------------------------------- lookup
    def _find_section(self, key: str) -> QTreeWidgetItem | None:
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            ref = self.ref_of(item)
            if ref is not None and ref.address is None and ref.section == key:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self.topLevelItemCount()):
            found = walk(self.topLevelItem(i))
            if found is not None:
                return found
        return None

    def section_item(self, key: str) -> QTreeWidgetItem:
        """The top-level (or flow sub-) node of a section key."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if self.ref_of(item).section == key:  # type: ignore[union-attr]
                return item
        found = self._find_section(key)
        if found is None:
            raise KeyError(key)
        return found

    def item_for(self, address: Address) -> QTreeWidgetItem | None:
        """The item standing for the object at ``address``."""

        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if self.address_of(item) == address:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self.topLevelItemCount()):
            found = walk(self.topLevelItem(i))
            if found is not None:
                return found
        return None

    def select_address(self, address: Address) -> bool:
        """Make the item of ``address`` current (emits :attr:`object_selected`)."""
        item = self.item_for(address)
        if item is None:
            return False
        self.setCurrentItem(item)
        return True

    def _on_current_changed(self, current: QTreeWidgetItem | None, _prev: Any) -> None:
        if self._rebuilding or current is None:
            return
        ref = self.ref_of(current)
        if ref is None:
            return
        self.object_selected.emit(ref.address if ref.address else ("section", ref.section))

    # ------------------------------------------------------------------- actions
    def actions_for(self, item: QTreeWidgetItem | None) -> list[QAction]:
        """The context-menu actions of an item.

        Parameters
        ----------
        item : QTreeWidgetItem or None

        Returns
        -------
        list of QAction
            Ready to trigger. Add actions of the loads node have
            ``data() == ("add_bc", tag)`` and are generated from the registry.
        """
        for old in self._actions:
            old.deleteLater()
        self._actions = []
        ref = self.ref_of(item)
        if ref is None:
            return []
        out: list[QAction] = []

        def add(text: str, slot: Callable[[], object], data: Any = None) -> None:
            action = QAction(text, self)
            action.setData(data)
            action.triggered.connect(lambda _checked=False: self._guarded(slot))
            out.append(action)

        model = self.document.model
        provider = self._provider_of(ref.address)
        if provider is None and ref.address is None and ref.section == "solution":
            for p in self.providers:
                for text, slot, data in p.tree_actions(None):
                    add(text, slot, data)
        elif provider is not None:
            for text, slot, data in provider.tree_actions(ref.address):
                add(text, slot, data)
        elif ref.address is None and ref.section == "loads":
            for tag in registry.bc_tags():
                title = self._title_of(registry.bc_info(tag).cls)
                add(f"Add {title}", lambda t=tag: self.request_bc(t), ("add_bc", tag))
        elif ref.address is None and ref.section == "materials":
            add("Add material", self.add_material, ("add_material", None))
        elif ref.address is None and ref.section == "regions":
            add("Add part", self.add_region, ("add_region", None))
        elif ref.address is None and ref.section == "folded":
            add("Add contact", self.add_contact, ("add_contact", None))
            add("Add stream", self.add_stream, ("add_stream", None))
            add("Create network", self.create_network, ("create_network", None))
        elif ref.address is None and ref.section == "streams":
            add("Add stream", self.add_stream, ("add_stream", None))
        elif ref.address is None and ref.section == "contacts":
            add("Add contact", self.add_contact, ("add_contact", None))
        elif ref.address is not None and ref.address[0] == "selections":
            address = ref.address
            if address[1] != ALL_SELECTION:
                add("Rename", lambda: self.begin_rename(address), ("rename", address))
            add("Delete", lambda: self.delete_selection_item(address), ("delete", address))
            used = bool(selection_users(model, address[1]))
            out[-1].setEnabled(address[1] != ALL_SELECTION and not used)
        elif ref.address is not None and ref.address[0] in _NAMED_LISTS + ("materials",):
            address = ref.address
            add("Rename", lambda: self.begin_rename(address), ("rename", address))
            add("Duplicate", lambda: self.duplicate(address), ("duplicate", address))
            if exists(model, address) and hasattr(resolve(model, address), "active"):
                active = resolve(model, address).active
                add(
                    "Suppress" if active else "Unsuppress",
                    lambda: self.set_suppressed(address, active),
                    ("suppress", address),
                )
            add("Delete", lambda: self.delete(address), ("delete", address))
        elif ref.address is not None and ref.address[0] == "geometry":
            address = ref.address
            add("Edit", lambda: self.edit_operation(address), ("edit_op", address))
            add("Rename", lambda: self.begin_rename(address), ("rename", address))
            add(
                "Delete operation", lambda: self.delete_operation(address),
                ("delete_op", address),
            )  # fmt: skip
        elif ref.address is not None and ref.address[0] == "regions":
            address = ref.address
            add("Rename", lambda: self.begin_rename(address), ("rename", address))
            add("Delete", lambda: self.delete(address), ("delete", address))
        self._actions = out
        return out

    def _guarded(self, slot: Callable[[], object]) -> None:
        try:
            slot()
        except ModelError as exc:
            self.error_occurred.emit(str(exc))

    def build_menu(self, item: QTreeWidgetItem | None) -> QMenu:
        """A menu of :meth:`actions_for` (a submenu "Add" collects the add actions)."""
        menu = QMenu(self)
        adds = QMenu("Add", menu)
        for action in self.actions_for(item):
            data = action.data()
            (adds if data and data[0] == "add_bc" else menu).addAction(action)
        if not adds.isEmpty():
            first = menu.actions()[0] if menu.actions() else None
            if first is None:
                menu.addMenu(adds)
            else:
                menu.insertMenu(first, adds)
        return menu

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        menu = self.build_menu(item)
        if not menu.isEmpty():
            self.menu_executor(menu, self.viewport().mapToGlobal(pos))

    # -------------------------------------------------------------------- edits
    def _names(self, model: Model, name: str) -> list[str]:
        """Names used in the list or dict an address's collection holds."""
        if name == "materials":
            return list(model.materials)
        return [obj.name for obj in getattr(model, name)]

    def add_bc(self, tag: str, selection: str = "") -> Address:
        """Add a boundary condition of a registered class; return its address.

        Parameters
        ----------
        tag : str
            Registry tag of the class.
        selection : str
            Name of its selection (may stay empty until the user picks one).
        """
        cls = registry.bc_info(tag).cls
        title = self._title_of(cls)
        holder: list[int] = []

        def mutate(model: Model) -> None:
            name = unique_name(title, [bc.name for bc in model.bcs])
            model.bcs.append(default_instance(cls, name=name, selection=selection))
            holder.append(len(model.bcs) - 1)

        self.document.edit(f"Add {title}", mutate)
        address = ("bcs", holder[0])
        self.select_address(address)
        return address

    def request_bc(self, tag: str) -> Address | None:
        """What the "Add" menu entry of a load does (M11.9).

        A correlation convection and a radiation condition open a non-modal dialog
        (``self.load_dialog``) that asks for their values; the load is added when it is
        accepted, as one undo step, holding exactly the values typed. Any other load is
        added at once with :meth:`add_bc`.

        Returns
        -------
        tuple or None
            Address of the new load; ``None`` while a dialog is open.
        """
        dialog_class = LOAD_DIALOGS.get(tag)
        if dialog_class is None:
            return self.add_bc(tag)
        dialog = dialog_class(self, self.document.model.display_units)
        dialog.load_requested.connect(lambda load, t=tag: self._add_new_bc(t, load))
        self.load_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return None

    def _add_new_bc(self, tag: str, template: Any) -> Address:
        """Add the load a :class:`NewLoadDialog` built (one undo step)."""
        title = self._title_of(registry.bc_info(tag).cls)
        holder: list[int] = []

        def mutate(model: Model) -> None:
            name = unique_name(title, [bc.name for bc in model.bcs])
            model.bcs.append(replace(template, name=name))
            holder.append(len(model.bcs) - 1)

        self.document.edit(f"Add {title}", mutate)
        address = ("bcs", holder[0])
        self.select_address(address)
        return address

    def add_material(self) -> Address:
        """Add a material "Material <n>" whose properties are all zero.

        Zero means "not set yet" (owner's decision, 2026-11-24): validation refuses a
        conductivity that is not positive, and a transient analysis also refuses a zero
        density or specific heat, so an unedited material cannot be solved by mistake. One
        undo step.

        Returns
        -------
        tuple
            Address of the new material.
        """
        holder: list[str] = []

        def mutate(model: Model) -> None:
            name = unique_name("Material", list(model.materials))
            model.materials[name] = Material(name, k=0.0, rho=0.0, cp=0.0)
            holder.append(name)

        self.document.edit("Add material", mutate)
        address = ("materials", holder[0])
        self.select_address(address)
        return address

    def add_region(self) -> Address:
        """Append a region with an empty selection, the first material and default geometry.

        Thickness 1.0 m and material angle 0.0 rad. One undo step.

        Returns
        -------
        tuple
            Address of the new region.
        """
        holder: list[int] = []

        def mutate(model: Model) -> None:
            material = next(iter(model.materials), "")
            name = unique_name("Part", {part_name(r) for r in model.regions})
            model.regions.append(
                RegionAssignment(
                    selection="", material=material, thickness=1.0, material_angle=0.0,
                    name=name,
                )
            )  # fmt: skip
            holder.append(len(model.regions) - 1)

        self.document.edit("Add part", mutate)
        address = ("regions", holder[0])
        self.select_address(address)
        return address

    def add_contact(self) -> Address:
        """Add a contact "Contact <n>" with an empty selection and conductance 0 (Constant).

        The conductance is the neutral value of :func:`~thermalfea.core.forms.default_instance`
        (no physical value is assumed); the user sets it in the contact panel. One undo step.

        Returns
        -------
        tuple
            Address of the new contact.
        """
        holder: list[int] = []

        def mutate(model: Model) -> None:
            name = unique_name("Contact", [c.name for c in model.contacts])
            model.contacts.append(default_instance(Contact, name=name, selection=""))
            holder.append(len(model.contacts) - 1)

        self.document.edit("Add contact", mutate)
        address = ("contacts", holder[0])
        self.select_address(address)
        return address

    def add_stream(self) -> Address | None:
        """Add a stream "Stream <n>" wetting no walls.

        With a model that has a stream, the new stream copies every value of the first one
        (mode, path, fluid, flow area, ...), so it is valid as the first one is. Otherwise
        the values are asked for in a non-modal :class:`NewStreamDialog`
        (``self.stream_dialog``) and the stream is added when it is
        accepted. One undo step.

        Returns
        -------
        tuple or None
            Address of the new stream; ``None`` while the dialog is open.
        """
        if not self.document.model.streams:
            dialog = NewStreamDialog(self, self.document.model.display_units)
            dialog.stream_requested.connect(self._add_new_stream)
            self.stream_dialog = dialog
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return None
        holder: list[int] = []

        def mutate(model: Model) -> None:
            template = model.streams[0]
            name = unique_name("Stream", [s.name for s in model.streams])
            stream = copy.deepcopy(template)
            stream.name = name
            stream.walls = []
            model.streams.append(stream)
            holder.append(len(model.streams) - 1)

        self.document.edit("Add stream", mutate)
        address = ("streams", holder[0])
        self.select_address(address)
        return address

    def _add_new_stream(self, template: Stream) -> Address:
        """Add the stream a :class:`NewStreamDialog` built (one undo step)."""
        holder: list[int] = []

        def mutate(model: Model) -> None:
            name = unique_name("Stream", [s.name for s in model.streams])
            model.streams.append(replace(template, name=name, walls=[]))
            holder.append(len(model.streams) - 1)

        self.document.edit("Add stream", mutate)
        address = ("streams", holder[0])
        self.select_address(address)
        return address

    def create_network(self) -> bool:
        """Set ``model.network`` to an empty :class:`FlowNetwork` (one undo step).

        The same edit as the "Create network" button of the network panel.
        """
        return self.document.edit(
            "Create network", lambda model: setattr(model, "network", FlowNetwork())
        )

    def rename(self, address: Address, new_name: str) -> bool:
        """Rename an object (unique within its list); ``False`` if nothing changed.

        Raises
        ------
        ModelError
            If the name is empty or already used.
        """
        new_name = new_name.strip()
        if address[0] == "regions":
            index = address[1]

            def rename_part(model: Model) -> None:
                region = model.regions[index]
                if part_name(region) != new_name:
                    region.name = check_part_name(model, new_name, index)

            return self.document.edit(f"Rename part {new_name}", rename_part)
        if address[0] == "geometry":
            old_id = resolve(self.document.model, address).id
            return self.document.edit(
                f"Rename geometry step {new_name}",
                lambda model: rename_operation(model, old_id, new_name),
            )
        if address[0] == "selections":
            old = address[1]
            changed = self.document.edit(
                f"Rename selection {new_name}",
                lambda model: rename_selection(model, old, new_name),
            )
            if changed:
                self.select_address(("selections", new_name))
            return changed
        if not new_name:
            raise ModelError("a name cannot be empty")

        def mutate(model: Model) -> None:
            collection = address[0]
            used = self._names(model, collection)
            obj = resolve(model, address)
            if new_name == obj.name:
                return
            if new_name in used:
                raise ModelError(f"the name {new_name!r} is already used")
            if collection == "materials":
                old = obj.name
                model.materials = {
                    (new_name if k == old else k): v for k, v in model.materials.items()
                }
                obj.name = new_name
                for region in model.regions:
                    if region.material == old:
                        region.material = new_name
            elif collection == "streams":
                old = obj.name
                obj.name = new_name
                if model.network is not None:  # branches name the stream they carry
                    for branch in model.network.branches:
                        if branch.stream == old:
                            branch.stream = new_name
            else:
                obj.name = new_name

        changed = self.document.edit(f"Rename {new_name}", mutate)
        if changed and address[0] == "materials":
            self.select_address(("materials", new_name))
        return changed

    def duplicate(self, address: Address) -> Address:
        """Copy an object under a new unique name; return the copy's address."""
        holder: list[Address] = []

        def mutate(model: Model) -> None:
            obj = copy.deepcopy(resolve(model, address))
            name = copy_name(
                obj.name, self._names(model, address[0]), keep_digits=address[0] == "materials"
            )
            obj.name = name
            if address[0] == "materials":
                model.materials[name] = obj
                holder.append(("materials", name))
            else:
                collection = getattr(model, address[0])
                collection.insert(address[1] + 1, obj)
                holder.append((address[0], address[1] + 1))

        self.document.edit("Duplicate", mutate)
        self.select_address(holder[0])
        return holder[0]

    def set_suppressed(self, address: Address, suppressed: bool) -> bool:
        """Suppress (``active = False``) or restore an object that has ``active``."""

        def mutate(model: Model) -> None:
            obj = resolve(model, address)
            if not hasattr(obj, "active"):
                raise ModelError("this object cannot be suppressed")
            obj.active = not suppressed

        name = resolve(self.document.model, address).name
        return self.document.edit(f"{'Suppress' if suppressed else 'Unsuppress'} {name}", mutate)

    def delete(self, address: Address) -> bool:
        """Delete an object."""

        def mutate(model: Model) -> None:
            resolve(model, address)  # raises if it is gone
            if address[0] == "materials":
                del model.materials[address[1]]
            else:
                del getattr(model, address[0])[address[1]]

        obj = resolve(self.document.model, address)
        label = getattr(obj, "name", address[0])
        return self.document.edit(f"Delete {label}", mutate)

    def delete_selection_item(self, address: Address) -> bool:
        """Delete the unused selection at ``address`` (one undo step).

        Raises
        ------
        ModelError
            If it is ``all`` or still used (nothing changes).
        """
        name = address[1]
        return self.document.edit(
            f"Delete selection {name}", lambda model: delete_selection(model, name)
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        """Page Down / Page Up step to the next / previous selection (Selections only)."""
        step = {Qt.Key.Key_PageDown: 1, Qt.Key.Key_PageUp: -1}.get(event.key())
        current = self.currentItem()
        address = self.address_of(current)
        if step is not None and address is not None and address[0] == "selections":
            parent = current.parent()
            target = parent.child(parent.indexOfChild(current) + step) if parent else None
            if target is not None:
                self.setCurrentItem(target)
            event.accept()
            return
        super().keyPressEvent(event)

    def edit_operation(self, address: Address) -> None:
        """Show the parameters of a geometry operation for editing."""
        resolve(self.document.model, address)  # raises if it is gone
        self.select_address(address)
        self.edit_requested.emit(address)

    def delete_operation(self, address: Address) -> bool:
        """Delete a geometry operation from the history.

        Raises
        ------
        ModelError
            If a later operation refers to it (nothing is changed).
        """
        op = resolve(self.document.model, address)
        op_id = op.id

        def mutate(model: Model) -> None:
            ops = model.geometry
            users = dependents(ops, op_id)
            if users:
                raise ModelError(
                    f"cannot delete {op_id!r}: {', '.join(users)} refer(s) to it; "
                    "delete or change those first"
                )
            del ops[address[1]]

        return self.document.edit(f"Delete {op_id}", mutate)

    def mark_addresses(self, addresses: list[Address]) -> None:
        """Show the items of ``addresses`` in bold (an inspected entity's objects, M11.61);
        the previous marks are cleared, and an empty list clears them all."""
        wanted = {tuple(a) for a in addresses}
        self._marked = wanted

        def walk(item: QTreeWidgetItem) -> None:
            ref = self.ref_of(item)
            font = item.font(0)
            font.setBold(ref is not None and ref.address is not None and ref.address in wanted)
            item.setFont(0, font)
            for i in range(item.childCount()):
                walk(item.child(i))

        self.blockSignals(True)
        try:
            for i in range(self.topLevelItemCount()):
                walk(self.topLevelItem(i))
        finally:
            self.blockSignals(False)

    def begin_rename(self, address: Address) -> None:
        """Start inline editing of an item's text."""
        item = self.item_for(address)
        if item is not None:
            self.editItem(item, 0)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Inline rename finished: apply it, or restore the old text if refused."""
        if self._rebuilding or column != 0:
            return
        address = self.address_of(item)
        provider = self._provider_of(address)
        if provider is not None:
            try:
                provider.rename(address, item.text(0))
            except ModelError as exc:
                self.error_occurred.emit(str(exc))
            self.rebuild()
            return
        renameable = _NAMED_LISTS + ("materials", "selections", "regions", "geometry")
        if address is None or address[0] not in renameable:
            return
        try:
            self.rename(address, item.text(0))
        except ModelError as exc:
            self.error_occurred.emit(str(exc))
        self.rebuild()
