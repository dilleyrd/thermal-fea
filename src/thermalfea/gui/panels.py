"""Connects the model tree to the property dock (Plan M8.4).

:class:`PropertyController` shows the :class:`~thermalfea.gui.property_panels.form.FormPanel`
of the object selected in the :class:`~thermalfea.gui.tree.ModelTree`. The form of an
object is ``form_for(type(object))``, so any registered class has a panel; a class that
needs more than its form registers a panel class with :func:`register_panel`.
:func:`attach_tree` installs tree and controller in a main window.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FormSpec, form_for
from thermalfea.gui.addressing import Address, exists, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.pick import manager_for
from thermalfea.gui.property_panels.contact import ContactPanel
from thermalfea.gui.property_panels.correlation import CorrelationPanel
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.material import MaterialPanel
from thermalfea.gui.property_panels.mesh import MeshPanel
from thermalfea.gui.property_panels.network import NETWORK_ADDRESS, NetworkPanel
from thermalfea.gui.property_panels.region import RegionPanel
from thermalfea.gui.property_panels.results import RESULT_ADDRESS, ResultPanel
from thermalfea.gui.property_panels.selection_editor import SelectionEditor
from thermalfea.gui.property_panels.selection_panel import SelectionPanel
from thermalfea.gui.property_panels.solution import SolutionPanel
from thermalfea.gui.property_panels.stream import StreamPanel
from thermalfea.gui.scene import SceneView
from thermalfea.gui.tree import ModelTree
from thermalfea.gui.tree_summary import TreeSummaryController
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Contact, CorrelationConvection, Stream
from thermalfea.model.model import RegionAssignment
from thermalfea.model.selections import Selection
from thermalfea.model.settings import MeshSettings, SolutionSettings

PLACEHOLDER_TEXT = "Select an object in the model tree to edit its properties."

#: ``factory(controller, spec, address) -> FormPanel``: builds the panel of one class.
PanelFactory = Callable[["PropertyController", FormSpec, Address], FormPanel]

_PANELS: dict[type, PanelFactory] = {}


def register_panel(cls: type, factory: PanelFactory) -> None:
    """Show a specialised panel for objects of ``cls`` (and its subclasses).

    Classes without an entry get a plain :class:`FormPanel` generated from their form.

    Parameters
    ----------
    cls : type
        The model class (for example a boundary condition).
    factory : callable
        ``factory(controller, spec, address)`` returns the panel; ``controller`` gives
        access to ``document``, ``view`` and ``generate_mesh``.
    """
    _PANELS[cls] = factory


def panel_factory(cls: type) -> PanelFactory:
    """Return the registered factory for ``cls`` (nearest base class), or the plain form."""
    for base in cls.__mro__:
        if base in _PANELS:
            return _PANELS[base]
    return _plain_panel


def _plain_panel(controller: PropertyController, spec: FormSpec, address: Address) -> FormPanel:
    return FormPanel(spec, controller.document, address, controller.view)


def _type_at(model: Any, address: Address) -> type | None:
    """Class of the object at ``address``, ``None`` where there is no object."""
    try:
        return type(resolve(model, address))
    except ModelError:
        return None


class PropertyController:
    """Shows the form of the selected object in the property dock.

    Parameters
    ----------
    window : MainWindow
        Its property dock receives the panel.
    document : Document
    tree : ModelTree
    view : SceneView, optional
        Passed to the forms for picking selections.

    Attributes
    ----------
    panel : FormPanel or None
        The form currently shown.
    current_address : tuple or None
        Address of the object the panel edits.
    """

    def __init__(
        self,
        window: MainWindow,
        document: Document,
        tree: ModelTree,
        view: SceneView | None = None,
    ) -> None:
        self.window = window
        self.document = document
        self.tree = tree
        self.view = view
        self.panel: FormPanel | None = None
        self.current_address: Address | None = None
        #: ``generate() -> bool`` of the mesh controller, given to the mesh panel (set by
        #: the application after :func:`~thermalfea.gui.mesh_tools.attach_mesh_tools`).
        self.generate_mesh: Callable[[], bool] | None = None
        #: The solve controller (validate, solve, can_solve, state_changed),
        #: given to the analysis-settings panel (set by the application after
        #: ``attach_solve``).
        self.solve_controller: Any = None
        #: The result-display controller (set by ``attach_results``); the objects under the
        #: Solution node have addresses ``("result", name)`` and get a ``ResultPanel``.
        self.results_controller: Any = None
        #: The result panel currently shown, if any.
        self.result_panel: QWidget | None = None
        self._installed: QWidget | None = None
        self._object_type: type | None = None
        tree.object_selected.connect(self.show_object)
        document.model_changed.connect(self._on_model_changed)

    def show_object(self, address: Address) -> None:
        """Show the form of the object at ``address`` (a placeholder if there is none)."""
        model = self.document.model
        results = self.results_controller
        if address and address[0] == RESULT_ADDRESS and results is not None:
            self._show_result(address)
            return
        if address == NETWORK_ADDRESS:  # shown also without a network ("Create network")
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(NetworkPanel(self.document))
            self._install(scroll, None, NETWORK_ADDRESS)
            return
        if not address or address[0] == "section" or not exists(model, address):
            self._install(self._placeholder(), None, None)
            return
        obj = resolve(model, address)
        if not hasattr(obj, "__dataclass_fields__"):
            self._install(self._placeholder(), None, None)
            return
        spec = None if isinstance(obj, Selection) else form_for(type(obj))  # no form: own panel
        panel = panel_factory(type(obj))(self, spec, address)  # type: ignore[arg-type]
        for editor in panel.findChildren(SelectionEditor):
            editor.mode_sync = self._sync_toolbar
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self._install(scroll, panel, address)

    def _show_result(self, address: Address) -> None:
        """Show the panel of a result object and make it the displayed one."""
        results = self.results_controller
        name = address[1] if len(address) > 1 else None
        if results.get(name) is None:
            self._install(self._placeholder(), None, None)
            return
        results.show(name)
        panel = ResultPanel(results, name)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self._install(scroll, None, None)
        self.result_panel = panel

    def _placeholder(self) -> QWidget:
        label = QLabel(PLACEHOLDER_TEXT)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def _sync_toolbar(self, mode: str) -> None:
        """Check the toolbar action of ``mode`` (without emitting it: the view is set already)."""
        action = self.window.actions.get(f"select.{mode}")
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _install(self, widget: QWidget, panel: FormPanel | None, address: Address | None) -> None:
        previous = self._installed
        if previous is not None and previous is not widget:
            # a panel that is being replaced must not keep picking into the viewport
            for editor in previous.findChildren(SelectionEditor):
                if editor.pick_button.isChecked():
                    editor.set_picking(False)
            if self.view is not None:  # nor keep a pick of the pick manager (C2)
                manager = manager_for(self.view)
                owner = manager.active.owner if manager.active is not None else None
                if isinstance(owner, QWidget) and (
                    owner is previous or previous.isAncestorOf(owner)
                ):
                    manager.cancel_active()
            # the quality coloring belongs to the mesh panel; a new panel starts unchecked
            for mesh_panel in previous.findChildren(MeshPanel):
                mesh_panel.color_box.setChecked(False)
        self.window.set_property_panel(widget)
        self._installed = widget
        self.result_panel = None
        self.panel = panel
        self.current_address = address
        self._object_type = _type_at(self.document.model, address) if address else None
        if previous is not None and previous is not widget:
            previous.deleteLater()

    def _on_model_changed(self) -> None:
        address = self.current_address
        if address is None or self.panel is None:
            return
        model = self.document.model
        if not exists(model, address) or type(resolve(model, address)) is not self._object_type:
            self.show_object(("section", "none"))


register_panel(
    MeshSettings,
    lambda c, spec, address: MeshPanel(spec, c.document, address, c.view, generate=c.generate_mesh),
)
register_panel(
    SolutionSettings,
    lambda c, spec, address: SolutionPanel(
        spec, c.document, address, c.view, controller=c.solve_controller
    ),
)
register_panel(
    RegionAssignment, lambda c, spec, address: RegionPanel(spec, c.document, address, c.view)
)
register_panel(Material, lambda c, spec, address: MaterialPanel(spec, c.document, address, c.view))
register_panel(
    CorrelationConvection,
    lambda c, spec, address: CorrelationPanel(spec, c.document, address, c.view),
)
register_panel(Stream, lambda c, spec, address: StreamPanel(spec, c.document, address, c.view))
register_panel(Selection, lambda c, spec, address: SelectionPanel(c, address))  # type: ignore[arg-type,return-value]
register_panel(Contact, lambda c, spec, address: ContactPanel(spec, c.document, address, c.view))


def attach_tree(
    window: MainWindow, document: Document, view: SceneView | None = None
) -> tuple[ModelTree, PropertyController]:
    """Install the model tree and the property controller in a main window.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView, optional
        The viewport (from :func:`~thermalfea.gui.viewport_mpl.attach_viewport`).

    Returns
    -------
    ModelTree
    PropertyController
    """
    tree = ModelTree(document)
    window.set_tree(tree)
    tree.error_occurred.connect(lambda text: window.show_error("Model tree", text))
    controller = PropertyController(window, document, tree, view)
    tree.property_controller = controller  # type: ignore[attr-defined]
    tree.summary_controller = TreeSummaryController(window, document, tree)  # type: ignore[attr-defined]
    return tree, controller
