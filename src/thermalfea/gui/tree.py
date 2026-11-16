"""The model tree (Plan M8.4): the objects of the model, with context-menu actions.

Top-level nodes: Geometry, Materials, Regions, Mesh, Initial Condition, Loads & Boundary
Conditions, Flow (Streams, Network), Enclosures, Analysis Settings, Solution. The tree is
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
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem, QWidget

from thermalfea.core import registry
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import copy_name, default_instance, form_for, unique_name
from thermalfea.gui.addressing import Address, exists, resolve
from thermalfea.gui.dialogs.new_stream import NewStreamDialog
from thermalfea.gui.document import Document
from thermalfea.materials import library
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Contact, Stream
from thermalfea.model.geometry_edit import dependents
from thermalfea.model.model import Model, RegionAssignment

#: ``(key, title)`` of the top-level nodes, in display order.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("geometry", "Geometry"),
    ("materials", "Materials"),
    ("regions", "Regions"),
    ("mesh", "Mesh"),
    ("initial", "Initial Condition"),
    ("loads", "Loads & Boundary Conditions"),
    ("contacts", "Contacts"),
    ("flow", "Flow"),
    ("enclosures", "Enclosures"),
    ("analysis", "Analysis Settings"),
    ("solution", "Solution"),
)
#: Section key -> address of the settings object the node itself edits.
SECTION_OBJECTS: dict[str, Address] = {
    "mesh": ("mesh_settings",),
    "initial": ("initial_condition",),
    "analysis": ("solution",),
}
#: Model lists of objects that can be renamed, duplicated and deleted.
_NAMED_LISTS = ("bcs", "streams", "enclosures", "contacts")
_SUPPRESSED_BRUSH = QBrush(QColor("#808080"))
_ROLE = Qt.ItemDataRole.UserRole


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

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.menu_executor: Callable[[QMenu, QPoint], None] = _default_menu_executor
        self._rebuilding = False
        self._expanded: dict[Any, bool] = {}
        self._actions: list[QAction] = []
        #: Providers of view objects shown under the Solution node (see :meth:`add_provider`).
        self.providers: list[Any] = []
        self.setHeaderHidden(True)
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
        self.rebuild()

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

    def _restore_expansion(self, item: QTreeWidgetItem) -> None:
        item.setExpanded(self._expanded.get(self._key(item), item.parent() is None))
        for i in range(item.childCount()):
            self._restore_expansion(item.child(i))

    def _populate(self, model: Model) -> None:
        sections: dict[str, QTreeWidgetItem] = {}
        for key, title in SECTIONS:
            sections[key] = self._make_item(
                self, title, NodeRef(key, SECTION_OBJECTS.get(key))
            )
        for i, op in enumerate(model.geometry):
            self._make_item(
                sections["geometry"], op.id, NodeRef("geometry", ("geometry", i)),
                tooltip=type(op).__name__,
            )  # fmt: skip
        for name in model.materials:
            self._make_item(
                sections["materials"], name, NodeRef("materials", ("materials", name)),
                renameable=True,
            )
        for i, region in enumerate(model.regions):
            self._make_item(
                sections["regions"], f"{region.selection} -> {region.material}",
                NodeRef("regions", ("regions", i)),
            )  # fmt: skip
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
                    sections["solution"], text, NodeRef("solution", address),
                    renameable=renameable,
                )

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
                add(f"Add {title}", lambda t=tag: self.add_bc(t), ("add_bc", tag))
        elif ref.address is None and ref.section == "materials":
            add("Add material", self.add_material, ("add_material", None))
        elif ref.address is None and ref.section == "regions":
            add("Add region", self.add_region, ("add_region", None))
        elif ref.address is None and ref.section == "streams":
            add("Add stream", self.add_stream, ("add_stream", None))
        elif ref.address is None and ref.section == "contacts":
            add("Add contact", self.add_contact, ("add_contact", None))
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
            add(
                "Delete operation", lambda: self.delete_operation(address),
                ("delete_op", address),
            )  # fmt: skip
        elif ref.address is not None and ref.address[0] == "regions":
            address = ref.address
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

    def add_material(self) -> Address:
        """Add a material "Material <n>" with the properties of the first built-in solid.

        The properties are a copy of a library entry (no numbers are invented here). One
        undo step.

        Returns
        -------
        tuple
            Address of the new material.
        """
        template = next(iter(library.solids().values()))
        holder: list[str] = []

        def mutate(model: Model) -> None:
            name = unique_name("Material", list(model.materials))
            model.materials[name] = Material.from_json({**template.to_json(), "name": name})
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
            model.regions.append(
                RegionAssignment(
                    selection="", material=material, thickness=1.0, material_angle=0.0
                )
            )
            holder.append(len(model.regions) - 1)

        self.document.edit("Add region", mutate)
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
        """Add an in-plane stream "Stream <n>" wetting no walls.

        With a model that has a stream, the new stream copies every value of the first one
        (path, fluid, flow area, ...). Otherwise the values are asked for in a non-modal
        :class:`NewStreamDialog` (``self.stream_dialog``) and the stream is added when it is
        accepted. One undo step.

        Returns
        -------
        tuple or None
            Address of the new stream; ``None`` while the dialog is open.
        """
        if not self.document.model.streams:
            dialog = NewStreamDialog(self)
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
            stream.mode = "in_plane"
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

    def rename(self, address: Address, new_name: str) -> bool:
        """Rename an object (unique within its list); ``False`` if nothing changed.

        Raises
        ------
        ModelError
            If the name is empty or already used.
        """
        new_name = new_name.strip()
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
        return self.document.edit(
            f"{'Suppress' if suppressed else 'Unsuppress'} {name}", mutate
        )

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

    def begin_rename(self, address: Address) -> None:
        """Start inline editing of an item's text."""
        item = self.item_for(address)
        if item is not None:
            self.editItem(item, 0)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        """Inline rename finished: apply it, or restore the old text if refused."""
        if self._rebuilding:
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
        if address is None or address[0] not in _NAMED_LISTS + ("materials",):
            return
        try:
            self.rename(address, item.text(0))
        except ModelError as exc:
            self.error_occurred.emit(str(exc))
        self.rebuild()
