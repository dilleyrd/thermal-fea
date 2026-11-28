"""Load and boundary-condition symbols in the viewport (Plan M8.8).

:class:`LoadSymbolController` listens to the document and keeps the viewport's symbol layer
equal to the active boundary conditions: one :class:`~thermalfea.gui.scene.LoadSymbol` per
active condition whose selection resolves to entities of the built geometry. The controller
is generic over the registry: it finds a condition's selection fields through the
``selection`` / ``selection_list`` fields of its form and names no condition class, so a
condition registered later is drawn without any change here.

``kind`` of a symbol is the registered tag of the condition class, its color the entry of
:data:`thermalfea.gui.scene.KIND_COLORS` at the tag's position in the registry (so a kind
keeps its color; the table cycles when there are more kinds than colors). The View menu
action ``view.load_symbols`` shows or hides the symbols. Selecting a load in the model tree
highlights its entities in the viewport.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea.core import registry
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import form_for
from thermalfea.gui.addressing import Address, exists, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import LoadSymbol, SceneView, kind_color
from thermalfea.model.bcs import BoundaryCondition, Contact
from thermalfea.model.selections import StaleSelectionError
from thermalfea.model.selections import resolve as resolve_selection

ACTION_ID = "view.load_symbols"
#: Symbol kind of the thermal contacts (their interface curves).
CONTACT_KIND = "contact"
CURVE_DIM = 1
_SURFACE_DIM = 2
_ITEM_ADDRESS = 2  # (section, key)
_SELECTION_KINDS = ("selection", "selection_list")
_GEOMETRY_DIMS = (0, 1, 2)


def selection_names(bc: BoundaryCondition) -> list[str]:
    """Names of the selections a condition refers to, found through its form fields.

    Parameters
    ----------
    bc : BoundaryCondition
        Any registered condition.

    Returns
    -------
    list of str
        In field order, without empty names and duplicates.
    """
    names: list[str] = []
    for spec in form_for(type(bc)).fields:
        if spec.kind not in _SELECTION_KINDS:
            continue
        value: Any = getattr(bc, spec.name, None)
        for name in [value] if isinstance(value, str) else list(value or []):
            if name and name not in names:
                names.append(str(name))
    return names


def kind_of(bc: BoundaryCondition) -> str:
    """The registered tag of a condition's class (the symbol ``kind``)."""
    return registry.tag_of(registry.BC_FAMILY, type(bc))


def color_of(kind: str) -> str:
    """The color of a kind: its position in the registry picks the table entry."""
    tags = registry.bc_tags()
    return kind_color(tags.index(kind) if kind in tags else len(tags))


def symbols_of(document: Document) -> list[LoadSymbol]:
    """The symbols of the document's active conditions and contacts.

    Empty without a built geometry. Each contact whose interface curves resolve gets one
    symbol of kind ``"contact"`` (its color is the next free entry after the condition
    kinds).
    """
    if document.built is None:
        return []
    out: list[LoadSymbol] = []
    for bc in document.model.bcs:
        if not bc.active:
            continue
        for dim, tags in entities_of(document, bc):
            kind = kind_of(bc)
            out.append(LoadSymbol(kind, bc.name, dim, tags, color_of(kind)))
    for contact in document.model.contacts:
        tags = dict(contact_entities(document, contact)).get(CURVE_DIM, [])
        if tags:
            color = color_of(CONTACT_KIND)
            out.append(LoadSymbol(CONTACT_KIND, contact.name, CURVE_DIM, tags, color))
    return out


def entities_of(document: Document, bc: BoundaryCondition) -> list[tuple[int, list[int]]]:
    """``(dim, tags)`` groups of the entities a condition's selections resolve to."""
    return _groups_of(document, selection_names(bc))


def contact_entities(document: Document, contact: Contact) -> list[tuple[int, list[int]]]:
    """``(dim, tags)`` groups of the entities of a contact's interface selection."""
    return _groups_of(document, [contact.selection] if contact.selection else [])


def _groups_of(document: Document, names: list[str]) -> list[tuple[int, list[int]]]:
    """``(dim, tags)`` groups of the built entities of the named selections."""
    groups: dict[int, list[int]] = {}
    for name in names:
        sel = document.model.selections.get(name)
        if sel is None or sel.dim not in _GEOMETRY_DIMS or not sel.tags:
            continue
        merged = groups.setdefault(int(sel.dim), [])
        merged.extend(int(t) for t in sel.tags if int(t) not in merged)
    return sorted(groups.items())


def region_surfaces(document: Document, address: Address) -> list[int]:
    """Surface tags of the region at ``("regions", i)`` or of every region using the material
    at ``("materials", name)``; empty without a built geometry or when nothing resolves."""
    model = document.model
    if document.built is None:
        return []
    if address[0] == "regions":
        regions = [resolve(model, address)]
    else:
        regions = [r for r in model.regions if r.material == address[1]]
    tags: list[int] = []
    for region in regions:
        for dim, found in _groups_of(document, [region.selection]):
            if dim == _SURFACE_DIM:
                tags.extend(t for t in found if t not in tags)
    return sorted(tags)


class LoadSymbolController(QObject):
    """Keeps the viewport's load symbols equal to the model's active conditions.

    Parameters
    ----------
    window : MainWindow
        Its View menu receives the checkable action ``view.load_symbols``.
    document : Document
    view : SceneView
        Receives ``set_symbols`` and ``highlight``.
    tree : QWidget, optional
        The model tree (anything with an ``object_selected`` signal); selecting a load
        there highlights its entities.

    Attributes
    ----------
    action : QAction
        The checkable View menu entry (checked: symbols shown).
    symbols : list of LoadSymbol
        The symbols last sent to the view (empty while hidden).
    """

    def __init__(
        self,
        window: MainWindow,
        document: Document,
        view: SceneView,
        tree: Any = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.symbols: list[LoadSymbol] = []
        self.action = QAction("Load &symbols", window)
        self.action.setCheckable(True)
        self.action.setChecked(True)
        self.action.toggled.connect(lambda _checked: self.update())
        window.actions[ACTION_ID] = self.action
        window.menus["view"].addAction(self.action)
        document.model_changed.connect(self.update)
        document.geometry_built.connect(self.update)
        if tree is not None and hasattr(tree, "object_selected"):
            tree.object_selected.connect(self.highlight_address)
        self.update()

    def update(self) -> None:
        """Send the current symbols (none while hidden) to the view."""
        self.symbols = symbols_of(self.document) if self.action.isChecked() else []
        self.view.set_symbols(list(self.symbols))

    def _status(self, text: str) -> None:
        """Show ``text`` in the main window's status bar (when it has one)."""
        bar = getattr(self.window, "statusBar", None)
        if bar is not None:
            bar().showMessage(text, 5000)

    def _highlight_operation(self, address: Address) -> None:
        """Highlight what the geometry operation at ``address`` owns in the current build."""
        op = resolve(self.document.model, address)
        built = self.document.built
        if built is None or self.document.geometry_stale:
            self.view.highlight(1, [])
            self._status(f"{op.id}: the geometry is not built")
            return
        owned = built.op_entities.get(op.id, [])
        if not owned:
            self.view.highlight(1, [])
            self._status(
                f"{op.id}: nothing left in the geometry (used by a later operation or deleted)"
            )
            return
        dim = max(int(d) for d, _ in owned)
        self.view.highlight(dim, sorted(int(t) for d, t in owned if int(d) == dim))

    def _highlight_selection(self, name: str) -> None:
        """Highlight a named selection in the current build; clear it when it is not found."""
        selection = self.document.model.selections[name]
        built = self.document.built
        try:
            if built is None:
                raise StaleSelectionError(name)
            tags = resolve_selection(selection, built)
        except StaleSelectionError:
            self.view.highlight(1, [])
            self._status(f"{name}: not found in the current geometry")
            return
        self.view.highlight(selection.dim, sorted(int(t) for t in tags))

    def highlight_address(self, address: Address) -> None:
        """Highlight the entities of the load at ``address``; other objects clear it."""
        model = self.document.model
        if address and address[0] == "selections" and exists(model, address):
            self._highlight_selection(address[1])
            return
        if address and address[0] == "geometry" and exists(model, address):
            self._highlight_operation(address)
            return
        if (
            len(address) == _ITEM_ADDRESS
            and address[0] in ("regions", "materials")
            and exists(model, address)
        ):
            tags = region_surfaces(self.document, address)
            self.view.highlight(2, tags)
            return
        if not address or address[0] not in ("bcs", "contacts") or not exists(model, address):
            self.view.highlight(1, [])  # the previous load's highlight must not stay
            return
        try:
            obj = resolve(model, address)
        except ModelError:  # pragma: no cover - exists() just said it is there
            return
        if isinstance(obj, Contact):
            groups = contact_entities(self.document, obj)
        else:
            groups = entities_of(self.document, obj)
        if groups:
            dim, tags = groups[-1]  # the highest dimension of the condition
            self.view.highlight(dim, tags)
        else:
            self.view.highlight(1, [])


def attach_loads(window: MainWindow, document: Document, view: SceneView) -> LoadSymbolController:
    """Install the load symbols and the View-menu toggle in a main window.

    Parameters
    ----------
    window : MainWindow
        Its model tree (if installed) drives the highlight of the selected load.
    document : Document
    view : SceneView
        The viewport (from :func:`~thermalfea.gui.viewport_mpl.attach_viewport`).

    Returns
    -------
    LoadSymbolController
    """
    return LoadSymbolController(window, document, view, window.tree_widget)
