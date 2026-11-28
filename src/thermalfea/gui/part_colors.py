"""Color the parts of the viewport by part or by material (M11.62).

:class:`PartColorController` adds the View-menu submenu "Color by" with three exclusive
checkable actions (``view.color_by.part`` default, ``view.color_by.material``,
``view.color_by.none``) and keeps :meth:`~thermalfea.gui.scene.SceneView.set_entity_colors`
equal to the model: every region (part) that resolves in the current build fills its surfaces
with the color of its part or of its material. Without a build, or in mode "None", the view's
colors and legend are cleared.

:func:`color_of_part` and :func:`color_of_material` give the same colors to other widgets
(the model tree swatches).
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QActionGroup

from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import SceneView, kind_color
from thermalfea.model.model import Model
from thermalfea.model.selections import resolve
from thermalfea.model.vocabulary import role_dim

PART_ACTION_ID = "view.color_by.part"
MATERIAL_ACTION_ID = "view.color_by.material"
NONE_ACTION_ID = "view.color_by.none"
MODES = ("part", "material", "none")


def color_of_part(index: int) -> str:
    """The color of the ``index``-th region (part); cycles through the categorical palette."""
    return kind_color(index)


def color_of_material(name: str, model: Model) -> str:
    """The color of material ``name``: its position in ``model.materials`` picks it.

    A name that is not in the model takes the color after the last material.
    """
    names = list(model.materials)
    index = names.index(name) if name in names else len(names)
    return kind_color(index)


def region_label(region: object) -> str:
    """The legend label of a region: its name if it has one, else its selection."""
    return str(getattr(region, "name", "") or getattr(region, "selection", ""))


def part_colors(
    document: Document, mode: str
) -> tuple[int, dict[int, str], list[tuple[str, str]]]:
    """``(dim, {tag: color}, [(label, color)])`` for ``mode``; empty for "none" / no build."""
    model = document.model
    dim = role_dim("part", model)
    built = document.built
    if mode == "none" or built is None or dim is None:
        return (dim if dim is not None else 0), {}, []
    colors: dict[int, str] = {}
    legend: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, region in enumerate(model.regions):
        sel = model.selections.get(region.selection)
        if sel is None or sel.dim != dim:
            continue
        try:
            tags = resolve(sel, built)
        except ThermalFEAError:
            continue  # a stale selection has nothing to color
        if not tags:
            continue
        if mode == "material":
            color, label = color_of_material(region.material, model), str(region.material)
        else:
            color, label = color_of_part(i), region_label(region)
        for tag in tags:
            colors[int(tag)] = color
        if label not in seen:
            seen.add(label)
            legend.append((label, color))
    return dim, colors, legend


class PartColorController(QObject):
    """The "Color by" submenu and the entity colors of the viewport.

    Parameters
    ----------
    window : MainWindow
        Its View menu receives the submenu; the actions go into ``window.actions``.
    document : Document
    view : SceneView
        Receives ``set_entity_colors``.
    """

    def __init__(self, window: MainWindow, document: Document, view: SceneView) -> None:
        super().__init__(window)
        self.document = document
        self.view = view
        self.menu = window.menus["view"].addMenu("&Color by")
        group = QActionGroup(window)
        group.setExclusive(True)
        self.actions: dict[str, QAction] = {}
        specs = (
            ("part", "&Part", PART_ACTION_ID),
            ("material", "&Material", MATERIAL_ACTION_ID),
            ("none", "&None", NONE_ACTION_ID),
        )
        for mode, title, key in specs:
            action = QAction(title, window)
            action.setCheckable(True)
            action.setChecked(mode == "part")
            group.addAction(action)
            self.menu.addAction(action)
            window.actions[key] = action
            self.actions[mode] = action
            action.toggled.connect(lambda checked: checked and self.update())
        document.model_changed.connect(self.update)
        document.geometry_built.connect(self.update)
        self.update()

    @property
    def mode(self) -> str:
        """The chosen mode: ``"part"``, ``"material"`` or ``"none"``."""
        for mode, action in self.actions.items():
            if action.isChecked():
                return mode
        return "none"  # pragma: no cover - the group is exclusive

    def update(self) -> None:
        """Send the colors and the legend of the current mode to the view."""
        dim, colors, legend = part_colors(self.document, self.mode)
        self.view.set_entity_colors(dim, colors, legend)


def attach_part_colors(
    window: MainWindow, document: Document, view: SceneView
) -> PartColorController:
    """Install the "Color by" submenu and the part colors."""
    return PartColorController(window, document, view)
