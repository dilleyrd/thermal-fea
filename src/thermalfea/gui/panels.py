"""Connects the model tree to the property dock (Plan M8.4).

:class:`PropertyController` shows the :class:`~thermalfea.gui.property_panels.form.FormPanel`
of the object selected in the :class:`~thermalfea.gui.tree.ModelTree`. The form of an
object is ``form_for(type(object))``, so any registered class has a panel.
:func:`attach_tree` installs tree and controller in a main window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from thermalfea.core.forms import form_for
from thermalfea.gui.addressing import Address, exists, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.region import RegionPanel
from thermalfea.gui.scene import SceneView
from thermalfea.gui.tree import ModelTree
from thermalfea.model.model import RegionAssignment

PLACEHOLDER_TEXT = "Select an object in the model tree to edit its properties."


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
        self._installed: QWidget | None = None
        self._object_type: type | None = None
        tree.object_selected.connect(self.show_object)
        document.model_changed.connect(self._on_model_changed)

    def show_object(self, address: Address) -> None:
        """Show the form of the object at ``address`` (a placeholder if there is none)."""
        model = self.document.model
        if not address or address[0] == "section" or not exists(model, address):
            self._install(self._placeholder(), None, None)
            return
        obj = resolve(model, address)
        if not hasattr(obj, "__dataclass_fields__"):
            self._install(self._placeholder(), None, None)
            return
        panel_cls = RegionPanel if isinstance(obj, RegionAssignment) else FormPanel
        panel = panel_cls(form_for(type(obj)), self.document, address, self.view)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self._install(scroll, panel, address)

    def _placeholder(self) -> QWidget:
        label = QLabel(PLACEHOLDER_TEXT)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def _install(
        self, widget: QWidget, panel: FormPanel | None, address: Address | None
    ) -> None:
        previous = self._installed
        self.window.set_property_panel(widget)
        self._installed = widget
        self.panel = panel
        self.current_address = address
        self._object_type = type(resolve(self.document.model, address)) if address else None
        if previous is not None and previous is not widget:
            previous.deleteLater()

    def _on_model_changed(self) -> None:
        address = self.current_address
        if address is None or self.panel is None:
            return
        model = self.document.model
        if not exists(model, address) or type(resolve(model, address)) is not self._object_type:
            self.show_object(("section", "none"))


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
    return tree, controller
