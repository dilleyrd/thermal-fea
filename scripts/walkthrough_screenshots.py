"""Screenshots of the GUI walkthrough (docs/gui-walkthrough.md), rendered offscreen.

Builds the real application (``thermalfea.gui.app.build_application``) without a screen,
follows the steps of the walkthrough for V-10 (NAFEMS T4, steady) and V-17 (slab cooled by
convection, transient) through the same entry points a user action reaches (menu actions,
tree actions, panel widgets, clicks in the view), and saves a PNG of the window (or of a
panel, dialog, menu or chart) at each step. It also prints the model tree, the dock title,
the panel texts, the status messages and the numbers of each step, so that the text of the
walkthrough can be checked against the real window.

Usage (project virtual environment)::

    .venv\\Scripts\\python.exe scripts\\walkthrough_screenshots.py [OUTPUT_FOLDER [v10|v17]]

The default output folder is ``docs/img/gui-walkthrough``. Nothing else on disk is touched:
the model files and the results are written under a temporary folder. Where the window does
not do what ``docs/gui-conventions.md`` says, a line starting with ``NOTE:`` is printed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# readable text without a screen: set before Qt is imported
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np  # noqa: E402
from matplotlib.backend_bases import MouseEvent  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDockWidget,
    QLabel,
    QPushButton,
    QScrollArea,
    QTreeWidgetItem,
    QWidget,
)

from thermalfea.gui.app import AppContext, build_application  # noqa: E402
from thermalfea.gui.history_tools import HistoryPanel  # noqa: E402
from thermalfea.gui.path_tools import PathPanel  # noqa: E402
from thermalfea.gui.tree_issues import TreeIssueController  # noqa: E402
from thermalfea.model.validate import errors  # noqa: E402
from thermalfea.post.results import Results  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "img" / "gui-walkthrough"
WINDOW_SIZE = (1400, 960)
WAIT = 90000  # ms; every wait is bounded

# V-10 (docs/verification.md)
W, HGT, YP = 0.6, 1.0, 0.2
BASE_K, AMBIENT_K, H_T4, K_T4 = 373.15, 273.15, 750.0, 52.0
# V-17
SLAB_L, SLAB_T = 0.05, 0.005
EXACT_17 = {39.0: (397.2600, 379.0147), 195.0: (369.8383, 355.4589)}


class Walk:
    """The application, a folder for the PNGs, and the helpers every step uses."""

    def __init__(self, out: Path, work: Path, name: str) -> None:
        self.out = out
        self.work = work
        self.ctx: AppContext = build_application(
            QSettings(str(work / f"{name}.ini"), QSettings.Format.IniFormat), install_hook=False
        )
        ctx = self.ctx
        ctx.solve.show_progress = False  # the dialog is created; it is grabbed by hand
        ctx.files.ask_unsaved = lambda _parent, _name: "discard"  # never a modal question
        ctx.materials.user_path = work / "user-materials.json"  # not the real user library
        self.errors: list[tuple[str, str]] = []
        ctx.window.error_dialog = lambda title, message: self.errors.append((title, message))
        self.notes: list[str] = []  # places where the window did not do what the text says
        window = ctx.window
        window.resize(*WINDOW_SIZE)
        window.show()
        self.settle()
        self.layout_docks()
        issues = window.findChildren(TreeIssueController)
        self.issues = issues[0] if issues else None

    # ------------------------------------------------------------------ plumbing
    def layout_docks(self, tree: int = 400, props: int = 400, bottom: int = 110) -> None:
        """A taller tree and a slimmer bottom dock, so that the panels have room."""
        window = self.ctx.window
        window.resizeDocks(
            [window.model_dock, window.properties_dock], [tree, props], Qt.Orientation.Vertical
        )
        window.resizeDocks([window.messages_dock], [bottom], Qt.Orientation.Vertical)
        window.resizeDocks([window.model_dock], [500], Qt.Orientation.Horizontal)
        self.settle()

    def settle(self, ms: int = 60) -> None:
        """Let Qt process events and the viewport draw."""
        QApplication.processEvents()
        QTest.qWait(ms)
        self.ctx.view.canvas.draw()
        QApplication.processEvents()

    def wait_until(self, condition: Any, what: str) -> None:
        waited = 0
        while not condition() and waited < WAIT:
            QTest.qWait(20)
            waited += 20
        if not condition():
            raise RuntimeError(f"timed out waiting for {what}")

    def note(self, text: str) -> None:
        print("NOTE:", text)
        self.notes.append(text)

    def shot(
        self, name: str, widget: QWidget | None = None, tree_top: bool = False,
        tree_bottom: bool = False,
    ) -> None:
        """Save a PNG of ``widget`` (default: the whole window)."""
        if self.issues is not None:
            self.issues.refresh()  # the marks in the tree wait for a pause; show them now
        if tree_top:
            self.ctx.tree.scrollToTop()
        if tree_bottom:
            self.ctx.tree.scrollToBottom()
        self.settle()
        target = widget if widget is not None else self.ctx.window
        pixmap = target.grab()
        path = self.out / name
        if not pixmap.save(str(path)):
            raise RuntimeError(f"cannot write {path}")
        print(f"saved {name}  {pixmap.width()}x{pixmap.height()}")

    def trigger(self, action_id: str) -> None:
        action = self.ctx.window.actions[action_id]
        if not action.isEnabled():
            raise RuntimeError(f"{action_id} is disabled")
        action.trigger()
        self.settle()

    def tree_action(self, section: str, data: tuple) -> None:
        actions = self.ctx.tree.actions_for(self.ctx.tree.section_item(section))
        next(a for a in actions if a.data() == data).trigger()
        self.settle()

    def panel(self) -> Any:
        """The panel now shown in Properties (a result item's panel included)."""
        props = self.ctx.properties
        return props.panel if props.panel is not None else props.result_panel

    def open_panel(self, address: tuple) -> Any:
        if not self.ctx.tree.select_address(address):
            raise RuntimeError(f"no tree item {address}")
        self.settle()
        panel = self.panel()
        if panel is None:
            raise RuntimeError(f"no panel for {address}")
        return panel

    def panel_shot(self, name: str, address: tuple | None = None) -> None:
        """Save the whole panel (not only the part the scroll area shows)."""
        panel = self.open_panel(address) if address is not None else self.panel()
        panel.adjustSize()
        self.shot(name, panel)

    def scroll_to(self, widget: QWidget) -> None:
        """Scroll the Properties dock so that ``widget`` is visible."""
        parent = widget.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget)
        self.settle()

    @staticmethod
    def enter(editor: Any, text: str) -> None:
        editor.setText(text)
        editor.editingFinished.emit()

    def set_function(self, address: tuple, name: str, text: str) -> None:
        panel = self.open_panel(address)
        editor = panel.editors[name]
        if editor.mode != "constant":
            editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("constant"))
        self.enter(editor.value_edit, text)
        if panel.error_text() or editor.error_text():
            raise RuntimeError(f"{address} {name}: {panel.error_text()} {editor.error_text()}")
        self.settle()

    def set_number(self, address: tuple, name: str, text: str) -> None:
        panel = self.open_panel(address)
        self.enter(panel.editors[name], text)
        if panel.error_text() or panel.editors[name].error_text():
            raise RuntimeError(f"{address} {name}: {panel.error_text()}")
        self.settle()

    def choose(self, address: tuple, name: str, text: str) -> None:
        """Choose a dropdown entry by its stored value, else by its shown text."""
        combo = self.open_panel(address).editors[name]
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index < 0:
            raise RuntimeError(f"{name}: no entry {text!r}")
        combo.setCurrentIndex(index)
        combo.activated.emit(index)
        self.settle()

    def click(self, x: float, y: float, ctrl: bool = False) -> None:
        """Press and release the left button at the data position (x, y) [m]."""
        view = self.ctx.view
        for kind in ("button_press_event", "button_release_event"):
            px, py = view.axes.transData.transform((x, y)) + 1e-6
            MouseEvent(
                kind, view.canvas, px, py, button=1, modifiers=["ctrl"] if ctrl else None
            )._process()
        self.settle()

    def key(self, key: Qt.Key, widget: QWidget | None = None) -> None:
        QTest.keyClick(widget if widget is not None else self.ctx.window, key)
        self.settle()

    def rebuilt(self, action: Any) -> None:
        """Run ``action`` and wait for the geometry build it starts."""
        done: list[Any] = []
        self.ctx.geometry.rebuilt.connect(lambda ok: done.append(ok))
        action()
        self.wait_until(lambda: bool(done), "the geometry build")
        if done[-1] is not True:
            raise RuntimeError(f"geometry build failed: {self.ctx.geometry.last_error}")
        self.settle()

    def rectangle(self, x: float, y: float, width: float, height: float) -> Any:
        """Geometry > Rectangle...: fill the dialog; returns it (not yet accepted)."""
        self.trigger("geometry.rectangle")
        dialog = self.ctx.geometry.active_dialog
        for key, value in (("x", x), ("y", y), ("width", width), ("height", height)):
            dialog.editors[key].setText(str(value))
        return dialog

    def accept_rectangle(self, dialog: Any) -> None:
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        self.rebuilt(ok.click)

    def new_selection(
        self, panel: Any, field: str, points: list[tuple[float, float]], name: str,
        stop_before_create: str | None = None,
    ) -> tuple[int, list[int]]:
        """The pick icon, click the entities, type the name, "Create and use".

        With ``stop_before_create`` the PNG of that name is saved just before the button is
        pressed (the strip shows the instruction, the count and the typed name).
        """
        editor = panel.editors[field]
        self.ctx.view.canvas.draw()
        editor.new_button.click()
        self.settle()
        if editor.picking != "new" or editor.name_edit.text() != "":
            raise RuntimeError("the pick did not start with an empty name box")
        self.check_toolbar(editor.spec.selection_dims)
        for index, (x, y) in enumerate(points):
            self.click(x, y, ctrl=index > 0)
        dim, tags = editor.picked()
        editor.name_edit.setText(name)
        self.settle()
        if stop_before_create:
            self.shot(stop_before_create)
        if not editor.strip.confirm_button.isEnabled():
            raise RuntimeError(f"'Create and use' is disabled for {name!r}")
        editor.strip.confirm_button.click()
        self.settle()
        if editor.picking is not None:
            raise RuntimeError("the pick did not end")
        if self.toolbar_mode() != "none":
            self.note(f"the toolbar did not switch back after the pick: {self.toolbar_mode()!r}")
        return dim, tags

    def toolbar_mode(self) -> str:
        return str(getattr(self.ctx.window, "selection_mode", "?"))

    def check_toolbar(self, dims: tuple[int, ...] | None) -> None:
        """Conventions C2: the toolbar switches by itself to the entity the pick needs."""
        want = "curve" if dims is None or 1 in dims else {0: "point", 2: "surface"}[dims[0]]
        if self.toolbar_mode() != want:
            self.note(f"toolbar is {self.toolbar_mode()!r} after a pick started, want {want!r}")

    # -------------------------------------------------------------------- printing
    def tree_lines(self) -> list[str]:
        """The model tree as ``indent name | summary`` lines (warning marks included)."""
        lines: list[str] = []

        def walk(item: QTreeWidgetItem, depth: int) -> None:
            marked = item.data(0, Qt.ItemDataRole.UserRole + 1) is not None  # M11.78
            mark = " [!]" if marked else ""
            lines.append(f"{'  ' * depth}{item.text(0)}{mark}".ljust(34) + f"| {item.text(1)}")
            if marked:
                lines.append("      warning: " + item.toolTip(0).replace("\n", " / "))
            for i in range(item.childCount()):
                walk(item.child(i), depth + 1)

        tree = self.ctx.tree
        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i), 0)
        return lines

    def print_tree(self, label: str) -> None:
        if self.issues is not None:
            self.issues.refresh()
        print(f"--- tree: {label}")
        print(f"Model dock title: {self.ctx.window.model_dock.windowTitle()}")
        for line in self.tree_lines():
            print(line)
        print("---")

    def print_panel(self, label: str, panel: Any = None) -> None:
        """Print the visible labels and buttons of the Properties panel (or of ``panel``)."""
        panel = panel if panel is not None else self.panel()
        print(f"--- panel: {label}")
        if panel is None:
            print("(none)")
            return
        for child in panel.findChildren(QWidget):
            if not child.isVisibleTo(panel):
                continue
            if isinstance(child, QLabel) and child.text().strip():
                print("label:", child.text().replace("\n", " / "))
            elif isinstance(child, QPushButton) and child.text().strip():
                print("button:", child.text())
        print("---")

    def status(self) -> str:
        return self.ctx.window.statusBar().currentMessage()

    def close(self) -> None:
        for window in list(self.ctx.charts.windows):
            window.close()
        if not self.ctx.shutdown(5000):
            print("WARNING: a thread did not stop in time")
        self.ctx.window.close()


# ------------------------------------------------------------------------ shared steps


def generate_mesh(walk: Walk) -> None:
    ctx = walk.ctx
    panel = walk.open_panel(("mesh_settings",))
    done: list[Any] = []
    ctx.mesh.meshed.connect(lambda ok: done.append(ok))
    panel.generate_button.click()
    walk.wait_until(lambda: bool(done), "the mesh")
    if done[-1] is not True:
        raise RuntimeError(f"meshing failed: {walk.errors}")
    walk.settle()


def solve(walk: Walk) -> None:
    ctx = walk.ctx
    walk.trigger("solve.validate")
    print("validate:", walk.status(), "|", [i.message for i in ctx.solve.last_issues])
    if errors(ctx.solve.last_issues):
        raise RuntimeError(f"validation errors: {ctx.solve.last_issues}")
    done: list[str] = []
    ctx.solve.solve_finished.connect(lambda outcome: done.append(outcome))
    walk.trigger("solve.run")
    walk.wait_until(lambda: bool(done), "the solve")
    if done[-1] != "finished":
        raise RuntimeError(f"solve ended {done[-1]}: {ctx.solve.message}")
    walk.settle(200)
    print("solve message:", ctx.solve.message)


def menu_shot(walk: Walk, name: str, key: str) -> None:
    """Save a PNG of a menu of the menu bar."""
    menu = walk.ctx.window.menus[key]
    menu.adjustSize()
    walk.shot(name, menu)


# ------------------------------------------------------------------------------- V-10


def v10(out: Path, work: Path) -> None:
    walk = Walk(out, work, "v10")
    try:
        _v10_steps(walk)
        print("V-10 notes:", walk.notes or "none")
        print("V-10 error dialogs:", walk.errors or "none")
    finally:
        walk.close()


def _v10_steps(walk: Walk) -> None:
    ctx = walk.ctx
    window = ctx.window

    # 0. a new model
    walk.print_tree("new model")
    walk.shot("g01_start.png")
    menu_shot(walk, "g25_view_menu.png", "view")

    # 1.1 geometry: two rectangles
    dialog = walk.rectangle(0.0, 0.0, W, YP)
    walk.shot("g02_rectangle_dialog.png", dialog)
    walk.accept_rectangle(dialog)
    dialog = walk.rectangle(0.0, YP, W, HGT - YP)
    walk.accept_rectangle(dialog)
    print("status after the rebuild:", walk.status())
    print("y limits before Fit view:", ctx.view.axes.get_ylim(), "(the plate is 0 to 1)")
    walk.trigger("view.fit")
    walk.shot("g03_v10_geometry.png")
    walk.print_tree("two rectangles")

    ctx.tree.rename(("geometry", 0), "lower strip")
    ctx.tree.rename(("geometry", 1), "upper strip")
    walk.settle()
    walk.wait_until(lambda: not ctx.document.geometry_stale, "the rebuild after the rename")
    ctx.tree.select_address(("geometry", 0))
    walk.shot("g04_v10_step_highlight.png")

    # 1.2 loads
    boxes = {
        "bottom": [(0.3, 0.0)],
        "cooled": [(W, 0.1), (W, 0.6), (0.3, HGT)],
        "left": [(0.0, 0.1), (0.0, 0.6)],
    }
    walk.tree_action("loads", ("add_bc", "fixed_temperature"))
    print("status after Add Fixed Temperature:", walk.status())
    walk.print_panel("new Fixed Temperature 1")
    walk.shot("g05a_v10_new_load.png")
    walk.new_selection(
        ctx.properties.panel, "selection", boxes["bottom"], "base",
        stop_before_create="g05_v10_pick_base.png",
    )
    walk.set_function(("bcs", 0), "T", str(BASE_K))
    walk.print_panel("Fixed Temperature 1")

    walk.tree_action("loads", ("add_bc", "convection"))
    walk.new_selection(ctx.properties.panel, "selection", boxes["cooled"], "cooled")
    walk.set_function(("bcs", 1), "h", str(H_T4))
    walk.set_function(("bcs", 1), "T_inf", str(AMBIENT_K))
    walk.open_panel(("bcs", 1))
    walk.shot("g06_v10_convection.png")
    walk.print_panel("Convection 1")

    walk.tree_action("loads", ("add_bc", "adiabatic"))
    walk.new_selection(ctx.properties.panel, "selection", boxes["left"], "left side")

    # a used name is refused (shown once, in the strip, and nothing is stored)
    walk.tree_action("loads", ("add_bc", "adiabatic"))
    editor = ctx.properties.panel.editors["selection"]
    editor.new_button.click()
    walk.click(0.3, 0.0)
    editor.name_edit.setText("base")
    walk.settle()
    print("refused name message:", editor.name_error.text(),
          "| 'Create and use' enabled:", editor.strip.confirm_button.isEnabled(),
          "| panel error:", ctx.properties.panel.error_text() or "(none)")
    walk.shot("g07_v10_name_refused.png")
    walk.key(Qt.Key.Key_Escape, editor.name_edit)  # Esc cancels the pick
    print("after Esc: picking =", editor.picking, "| toolbar:", walk.toolbar_mode())
    if editor.picking is not None:
        walk.note("Esc in the Name box did not cancel the pick")
        editor.strip.cancel_button.click()
    window.actions["edit.undo"].trigger()  # takes the extra Adiabatic condition away
    walk.settle()
    print("loads after the undo:", len(ctx.document.model.bcs))
    ctx.tree.select_address(("bcs", 2))
    walk.shot("g08_v10_loads.png", tree_top=True)

    # a changed dropdown waits for the check mark; leaving the panel drops it
    panel = walk.open_panel(("bcs", 2))
    editor = panel.editors["selection"]
    index = editor.combo.findData("base")
    editor.combo.setCurrentIndex(index)
    editor.combo.activated.emit(index)
    walk.settle()
    walk.shot("g08a_v10_selection_pending.png")
    print("pending text:", editor.pending_label.text())
    walk.open_panel(("bcs", 0))  # leave the panel with the change pending
    print("status after leaving with a pending change:", walk.status())
    print("load 3 still uses:", ctx.document.model.bcs[2].selection)
    # the edit icon: the entities of the stored selection
    editor = walk.open_panel(("bcs", 2)).editors["selection"]
    editor.edit_button.click()
    walk.settle()
    walk.shot("g08b_v10_edit_strip.png")
    editor.strip.cancel_button.click()
    walk.settle()

    # 1.3 material and part
    walk.tree_action("materials", ("add_material", None))
    material = next(iter(ctx.document.model.materials))
    print("new material:", material, ctx.document.model.materials[material].k)
    walk.print_panel("new Material 1")
    walk.print_tree("V-10 with the new material (k not set)")
    walk.set_function(("materials", material), "k", str(K_T4))
    walk.shot("g09_v10_material.png")

    walk.tree_action("regions", ("add_region", None))
    walk.print_panel("new part")
    print("new part's material before any choice:", ctx.document.model.regions[0].material)
    walk.new_selection(ctx.properties.panel, "selection", [(0.3, 0.1), (0.3, 0.6)], "plate")
    walk.choose(("regions", 0), "material", material)
    ctx.tree.rename(("regions", 0), "Plate")
    walk.settle()
    walk.open_panel(("regions", 0))
    walk.shot("g10_v10_part.png")
    walk.print_panel("Part Plate")
    names_action = next(a for a in window.menus["view"].actions() if a.text() == "Part &names")
    names_action.trigger()  # View > Part names
    walk.settle()
    walk.shot("g10a_v10_part_names.png")
    names_action.trigger()
    walk.settle()
    print("View menu:", [a.text() for a in window.menus["view"].actions()])
    print("Results menu:", [a.text() for a in window.menus["results"].actions()])

    # 1.4 mesh
    walk.set_number(("mesh_settings",), "global_size", "0.025")
    panel = walk.open_panel(("mesh_settings",))
    more = panel.sections["Element type"].more
    more.set_open(True)
    walk.settle()
    print("Element type > More shows:", [
        w.text() for w in more.body.findChildren(QLabel) if w.isVisibleTo(more.body)
    ])
    more.set_open(False)
    walk.panel_shot("g11a_v10_mesh_panel.png", ("mesh_settings",))
    generate_mesh(walk)
    print("mesh status:", walk.status())
    walk.open_panel(("mesh_settings",))
    walk.shot("g12_v10_mesh.png")
    walk.print_panel("Mesh")

    # the Selections panel
    walk.open_panel(("selections", "cooled"))
    walk.shot("g11_v10_selection.png")
    walk.print_panel("Selection cooled")
    # renaming in the panel: the load follows; one undo step brings the old name back
    panel = ctx.properties.panel
    panel.name_edit.setText("cooled sides")
    panel.name_edit.returnPressed.emit()
    walk.settle()
    print("load summary after the rename:", ctx.tree.item_for(("bcs", 1)).text(1))
    window.actions["edit.undo"].trigger()
    walk.settle()
    print("load summary after the undo:", ctx.tree.item_for(("bcs", 1)).text(1))
    # Add from viewport: the same pick strip; Esc cancels
    panel = walk.open_panel(("selections", "cooled"))
    panel.add_button.click()
    walk.settle()
    print("add strip | toolbar:", walk.toolbar_mode())
    walk.shot("g11b_v10_selection_add.png")
    walk.key(Qt.Key.Key_Escape, panel)
    print("after Esc: toolbar", walk.toolbar_mode(), "| picking:",
          getattr(panel, "picking", "?"))
    walk.print_panel("Selection cooled after Esc")

    walk.print_tree("V-10 before the solve")

    # 1.6 solve
    solve(walk)
    if ctx.solve.dialog is not None:
        ctx.solve.dialog.show()
        walk.shot("g13_v10_solving.png", ctx.solve.dialog)
        ctx.solve.dialog.close()
    walk.open_panel(("result", "Temperature 1"))
    walk.shot("g14_v10_result.png")
    walk.print_panel("Temperature 1")
    walk.print_tree("V-10 after the solve")

    # Results > Probe: the strip text
    walk.trigger("results.probe")
    print("probe strip texts:", [
        w.text() for w in window.findChildren(QLabel)
        if "Click" in w.text() and w.isVisible()
    ])
    walk.trigger("results.probe")
    print("toolbar after the probe is off:", walk.toolbar_mode())

    # 1.7 the number
    results = Results(ctx.document.results_path)
    nodes = results.mesh.nodes[:, :2]
    node = int(np.argmin(np.linalg.norm(nodes - [W, YP], axis=1)))
    print(f"mesh: {results.mesh.n_nodes} nodes, {results.mesh.n_elements} elements")
    print(f"T at (0.6, 0.2) = {float(results.temperature()[node]) - 273.15:.3f} degC")
    print("relative imbalance:", float(abs(results.energy_balance()["relative_imbalance"][-1])))
    for name in results.heat_flow_names:
        print("heat flow", name, float(results.heat_flow(name)[-1]))

    # 1.8 inspect (a tall tree, so that the bold items are all in view), then the messages
    ctx.tree.clearSelection()
    walk.layout_docks(tree=640, props=240)
    walk.trigger("select.curve")
    walk.click(0.3, 0.0)
    walk.shot("g16_v10_inspect.png", tree_top=True)
    print("inspect status:", walk.status())
    walk.trigger("select.none")
    walk.layout_docks(tree=400, props=300, bottom=300)
    for dock in window.findChildren(QDockWidget):
        if dock.windowTitle() == "Messages":
            dock.show()
            dock.raise_()
    walk.settle()
    walk.trigger("view.fit")
    walk.shot("g17_v10_messages.png")
    walk.layout_docks()
    walk.trigger("view.fit")

    # 1.9 out of date
    walk.set_function(("bcs", 1), "h", "800")
    walk.open_panel(("result", "Temperature 1"))
    walk.shot("g15_v10_out_of_date.png")
    walk.print_panel("Temperature 1, out of date")
    window.actions["edit.undo"].trigger()
    walk.settle()
    walk.print_tree("V-10 after the undo")

    # the results menu
    menu_shot(walk, "g26_results_menu.png", "results")


# ------------------------------------------------------------------------------ V-17


def v17(out: Path, work: Path) -> None:
    walk = Walk(out, work, "v17")
    try:
        _v17_steps(walk)
        print("V-17 notes:", walk.notes or "none")
        print("V-17 error dialogs:", walk.errors or "none")
    finally:
        walk.close()


def _v17_steps(walk: Walk) -> None:
    ctx = walk.ctx
    window = ctx.window
    L, T = SLAB_L, SLAB_T
    walk.print_tree("V-17 new model")

    dialog = walk.rectangle(0.0, 0.0, L, T)
    walk.accept_rectangle(dialog)
    walk.trigger("view.fit")

    walk.tree_action("loads", ("add_bc", "convection"))
    walk.new_selection(ctx.properties.panel, "selection", [(L, T / 2)], "cooled end")
    walk.set_function(("bcs", 0), "h", "500")
    walk.set_function(("bcs", 0), "T_inf", "300")
    walk.tree_action("loads", ("add_bc", "symmetry"))
    walk.new_selection(ctx.properties.panel, "selection", [(0.0, T / 2)], "symmetry plane")
    walk.tree_action("loads", ("add_bc", "adiabatic"))
    walk.new_selection(
        ctx.properties.panel, "selection", [(L / 2, 0.0), (L / 2, T)], "long sides"
    )

    walk.tree_action("materials", ("add_material", None))
    material = next(iter(ctx.document.model.materials))
    walk.set_function(("materials", material), "k", "50")
    walk.set_function(("materials", material), "rho", "7800")
    walk.set_function(("materials", material), "cp", "500")
    walk.tree_action("regions", ("add_region", None))
    walk.new_selection(ctx.properties.panel, "selection", [(L / 2, T / 2)], "slab")
    walk.choose(("regions", 0), "material", material)
    ctx.tree.rename(("regions", 0), "Slab")
    walk.settle()
    ctx.tree.select_address(("bcs", 0))
    walk.shot("g18_v17_model.png", tree_top=True)

    # View > Stretch: the strip is ten times longer than high
    walk.trigger("view.stretch.y10")
    walk.shot("g18a_v17_stretched.png", tree_top=True)
    walk.trigger("view.stretch.none")

    # 2.5 mesh: the value table and the structured mesh box
    walk.set_number(("mesh_settings",), "global_size", "0.005")
    panel = walk.open_panel(("mesh_settings",))
    table = panel.editors["curve_divisions"]
    for name, count in (("long sides", "40"), ("symmetry plane", "1"), ("cooled end", "1")):
        row = table.add_row()
        combo = table.row_widgets(row).combo
        combo.setCurrentIndex(combo.findData(name))
        combo.activated.emit(combo.currentIndex())
        if row == 0:
            walk.scroll_to(panel.sections["Structured mesh"])
            walk.shot("g19b_v17_division_row.png")
        edits = table.row_widgets(row).edits
        edits[0].setText(count)
        edits[0].returnPressed.emit()
        walk.settle()
    print("divisions:", ctx.document.model.mesh_settings.curve_divisions)
    structured = panel.editors["structured_surfaces"]
    structured.choose("slab")
    print("structured parts pending:", structured.has_pending(),
          "|", structured.pending_label.text())
    structured.update()
    walk.settle()
    print("structured parts:", ctx.document.model.mesh_settings.structured_surfaces)
    generate_mesh(walk)
    print("mesh status:", walk.status())
    panel = walk.open_panel(("mesh_settings",))
    walk.panel_shot("g19_v17_mesh.png")
    walk.print_panel("Mesh V-17")
    # a row with focus highlights its boundaries in the view
    edit = table.row_widgets(0).edits[0]
    window.activateWindow()
    edit.setFocus(Qt.FocusReason.TabFocusReason)
    walk.scroll_to(panel.sections["Structured mesh"])
    walk.shot("g19a_v17_row_highlight.png")

    # 2.6 transient settings
    panel = walk.open_panel(("solution",))
    print("Analysis type choices:", [panel.editors["kind"].itemText(i)
                                     for i in range(panel.editors["kind"].count())])
    walk.choose(("solution",), "kind", "Transient")
    walk.set_number(("solution",), "end_time", "195")
    walk.choose(("solution",), "output", "times")
    panel = walk.open_panel(("solution",))
    walk.enter(panel.editors["output_times"], "39, 195")
    walk.settle()
    print("output times stored:", ctx.document.model.solution.output_times)
    print("Output steps choices:", [panel.editors["output"].itemText(i)
                                    for i in range(panel.editors["output"].count())])
    ic = walk.open_panel(("initial_condition",))
    print("Initial Condition kind choices:", [ic.editors["kind"].itemText(i)
                                              for i in range(ic.editors["kind"].count())])
    panel = walk.open_panel(("solution",))
    print("solution editors:", sorted(panel.editors))
    walk.set_function(("initial_condition",), "value", "400")
    walk.panel_shot("g20b_v17_initial_condition.png", ("initial_condition",))
    walk.print_panel("Initial Condition")
    panel = walk.open_panel(("solution",))
    walk.panel_shot("g20_v17_settings.png")
    walk.print_panel("Analysis Settings, transient")
    print("section titles:", {k: s.title_text() for k, s in panel.sections.items()})
    for key in ("Integration", "Convergence"):
        panel.sections[key].set_open(True)
    more = panel.sections["Time stepping"].more
    if more is not None:
        more.set_open(True)
    walk.settle()
    walk.panel_shot("g20a_v17_settings_open.png")
    walk.print_panel("Analysis Settings, advanced open")
    print("Theta combo:", [panel.editors["theta"].itemText(i)
                           for i in range(panel.editors["theta"].count())])
    for key in ("Integration", "Convergence"):
        panel.sections[key].set_open(False)
    if more is not None:
        more.set_open(False)
    walk.print_tree("V-17 before the solve")
    walk.open_panel(("solution",))

    # 2.8 solve and compare
    solve(walk)
    if ctx.solve.dialog is not None:
        ctx.solve.dialog.show()
        walk.shot("g21_v17_solving.png", ctx.solve.dialog)
        ctx.solve.dialog.close()
    result = walk.open_panel(("result", "Temperature 1"))
    walk.shot("g22_v17_result.png", tree_bottom=True)
    walk.print_panel("Temperature 1, V-17")
    result.time_edit.setText("39")
    result.time_edit.editingFinished.emit()
    walk.settle()
    print("step spin after typing time 39:", result.step_spin.value())
    result.time_edit.setText("195")
    result.time_edit.editingFinished.emit()
    walk.settle()

    res = Results(ctx.document.results_path)
    nodes = res.mesh.nodes[:, :2]
    centre = int(np.argmin(np.linalg.norm(nodes - [0.0, 0.0], axis=1)))
    surface = int(np.argmin(np.linalg.norm(nodes - [L, 0.0], axis=1)))
    times = np.asarray(res.times)
    print(f"mesh: {res.mesh.n_nodes} nodes, {res.mesh.n_elements} elements; steps {times}")
    for t, (ec, es) in EXACT_17.items():
        k = int(np.argmin(abs(times - t)))
        temp = np.asarray(res.temperature(k))
        print(f"t = {times[k]:g}: centre {temp[centre]:.3f} (exact {ec}, rel "
              f"{abs(temp[centre] - ec) / ec:.1e}), surface {temp[surface]:.3f} (exact {es}, "
              f"rel {abs(temp[surface] - es) / es:.1e})")

    # Results > Nodal history...: a saved item whose panel picks the nodes
    ctx.charts.request_history()
    walk.settle()
    items = ctx.charts.history_items
    (item,) = items.items()
    (hpanel,) = [p for p in window.findChildren(HistoryPanel) if p.name == item.name]
    print("history item:", item.name, "| picking:", hpanel.picking,
          "| toolbar:", walk.toolbar_mode())
    walk.shot("g23b_v17_history_pick.png", tree_bottom=True)
    walk.click(0.0, 0.0)
    walk.click(L, 0.0, ctrl=True)
    print("history strip count:", hpanel.strip.count_label.text())
    hpanel.confirm_pick()
    walk.settle()
    print("history nodes:", items.nodes_of(items.get(item.name)), "| expect", centre, surface)
    walk.shot("g23a_v17_history_item.png", tree_bottom=True)
    walk.print_panel("Nodal history item", hpanel)
    # (the chart windows stay open until the end: closing one and then editing the model
    # raises "ChartWindow already deleted" in history_tools._on_changed, see the report)
    chart = items.plot(item.name)
    walk.settle(300)
    walk.shot("g23_v17_history.png", chart)
    energy = ctx.charts.plot_energy_balance()
    walk.settle(300)
    walk.shot("g24_v17_energy.png", energy)

    # Results > Path plot...: a saved item with the boxes Path and Plot
    path_name = ctx.charts.path_items.add()
    walk.settle()
    print("path item:", path_name)
    walk.shot("g27_v17_path_item.png", tree_bottom=True)
    (ppanel,) = [p for p in window.findChildren(PathPanel) if p.name == path_name]
    walk.print_panel("Path item", ppanel)
    walk.print_tree("V-17 after the solve and the items")

    # out of date: a later end time
    walk.set_number(("solution",), "end_time", "200")
    walk.open_panel(("result", "Temperature 1"))
    walk.print_panel("Temperature 1, V-17 out of date")
    print("viewport title:", ctx.view.axes.get_title())
    window.actions["edit.undo"].trigger()
    walk.settle()


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["walkthrough"])
    app.setFont(QFont("Segoe UI", 9))
    with tempfile.TemporaryDirectory(prefix="walkthrough-") as folder:
        work = Path(folder)
        only = argv[2] if len(argv) > 2 else "all"
        if only in ("all", "v10"):
            v10(out, work)
        if only in ("all", "v17"):
            v17(out, work)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
