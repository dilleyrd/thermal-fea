"""M11.50: the summary column of the model tree and the Model dock title."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.core.units import UnitSettings
from thermalfea.gui import tree_summary as ts
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.tree import ModelTree
from thermalfea.materials.material import Material
from thermalfea.model import geometry_ops as ops
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.model import InitialCondition


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    g = api.Geometry(model)
    g.rectangle(0.0, 0.0, 0.6, 0.2, id="plate")
    built = api.build(model)
    api.select_curves(model, built, "cooled", lambda fp: abs(fp.center[1]) < 1e-9)
    api.select_surfaces(model, built, "body", lambda fp: True)
    api.assign_region(model, "body", "Copper (pure)")
    model.bcs.append(Convection("cool", "cooled", h=Constant(750.0), T_inf=Constant(273.15)))
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


def summary(tree: ModelTree, address=None, section: str | None = None) -> str:
    item = tree.item_for(address) if address is not None else tree.section_item(section)
    return item.text(1)


def test_two_columns_and_column_zero_text_is_unchanged(tree) -> None:
    assert tree.columnCount() == 2
    assert tree.section_item("loads").child(0).text(0) == "cool"
    assert tree.section_item("geometry").text(0) == "Geometry"


def test_geometry_step_summaries() -> None:
    u = UnitSettings()
    assert ts.geometry_summary(ops.Rectangle("r", 0, 0, 0.6, 0.2), u) == "rectangle 0.6 × 0.2 m"
    assert ts.geometry_summary(ops.Circle("c", 0, 0, 0.05), u) == "circle r 0.05 m"
    poly = ops.Polygon("p", [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 2)])
    assert ts.geometry_summary(poly, u) == "polygon 5 vertices"
    assert ts.geometry_summary(ops.Boolean("b", "cut", ["a"], ["c"]), u) == "boolean cut"
    t = ops.Transform("t", "translate", ["a"], {"dx": 1.0, "dy": 0.0})
    assert ts.geometry_summary(t, u) == "transform translate"
    assert ts.geometry_summary(ops.ImportFile("i", "C:/x/file.dxf", "dxf"), u) == "import file.dxf"
    mm = UnitSettings.preset("SI (mm)")
    assert ts.geometry_summary(ops.Rectangle("r", 0, 0, 0.6, 0.2), mm) == ("rectangle 600 × 200 mm")


def test_tree_geometry_section_and_step(tree) -> None:
    assert summary(tree, section="geometry") == "1 steps"
    assert summary(tree, ("geometry", 0)) == "rectangle 0.6 × 0.2 m"


def test_load_summary_uses_the_form_and_the_selection(tree, doc) -> None:
    text = summary(tree, ("bcs", 0))
    assert text.startswith("Convection · ")
    assert "h 750 W/(m^2 K)" in text
    assert text.endswith("→ cooled")
    assert "cool" not in text.split("→")[0]  # the object's own name is not shown
    assert summary(tree, section="loads") == "1"


def test_suppressed_load_and_registered_form(tree, doc) -> None:
    doc.edit("add", lambda m: m.bcs.append(FixedTemperature("fix", "cooled", T=Constant(300.0))))
    doc.edit("suppress", lambda m: setattr(m.bcs[1], "active", False))
    text = summary(tree, ("bcs", 1))
    assert text.startswith("Fixed Temperature")
    assert text.endswith("→ cooled · suppressed")
    assert summary(tree, section="loads") == "2"


def test_mesh_summary_states(tree, doc) -> None:
    assert summary(tree, section="mesh").endswith("not meshed")
    mesh = api.mesh(doc.model, doc.built)
    doc.set_mesh(mesh)
    text = summary(tree, section="mesh")
    assert f"{mesh.n_nodes:,}".replace(",", " ") + " nodes" in text
    assert text.endswith("current")
    doc.edit("size", lambda m: setattr(m.mesh_settings, "global_size", 0.05))
    assert summary(tree, section="mesh").endswith("out of date")


def test_initial_condition_and_analysis_summaries(tree, doc) -> None:
    doc.edit(
        "ic",
        lambda m: setattr(m, "initial_condition", InitialCondition("uniform", Constant(293.15))),
    )
    assert summary(tree, section="initial") == "uniform 293.1 K"
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC")))
    assert summary(tree, section="initial") == "uniform 20 °C"
    doc.edit(
        "ic", lambda m: setattr(m, "initial_condition", InitialCondition("per_region", None, {}))
    )
    assert summary(tree, section="initial") == "per region"
    assert summary(tree, section="analysis") == "steady"
    doc.edit(
        "tr",
        lambda m: (
            setattr(m.solution, "kind", "transient"),
            setattr(m.solution, "end_time", 195.0),
        ),
    )
    assert summary(tree, section="analysis") == "transient 0–195 s"


def test_expression_and_results_initial_summaries(doc) -> None:
    model = doc.model
    model.initial_condition = InitialCondition("expression", Expression("300 + x"))
    assert ts.initial_summary(model) == "expression"
    model.initial_condition = InitialCondition("from_results", None, None, "r.h5")
    assert ts.initial_summary(model) == "from results"


def test_material_summaries(doc) -> None:
    u = UnitSettings()
    assert ts.material_summary(Material("m", k=52.0, rho=1.0, cp=1.0), u) == "k 52 W/(m K)"
    table = Table([300.0, 400.0], [50.0, 60.0], "T")
    assert ts.material_summary(Material("m", k=table, rho=1.0, cp=1.0), u) == "k table(T)"


def test_regions_and_materials_nodes(tree, doc) -> None:
    assert summary(tree, section="materials") == str(len(doc.model.materials))
    assert summary(tree, section="regions") == "1"
    assert summary(tree, ("regions", 0)) == "Copper (pure) · t 1 m"
    assert summary(tree, section="contacts") == "0"
    assert summary(tree, section="solution") == ""


def test_provider_summary_mechanism(tree) -> None:
    class Provider(QObject):
        objects_changed = Signal()

        def tree_items(self):
            return [("Plot 1", ("view", 0), False), ("Plot 2", ("view", 1), False)]

        def owns(self, address) -> bool:
            return address[0] == "view"

        def tree_summary(self, address) -> str:
            return f"summary {address[1]}"

    class Plain(Provider):
        def tree_items(self):
            return [("Other", ("other", 0), False)]

        def owns(self, address) -> bool:
            return address[0] == "other"

        tree_summary = None  # type: ignore[assignment]

    tree.add_provider(Provider())
    tree.add_provider(Plain())
    assert summary(tree, ("view", 1)) == "summary 1"
    assert summary(tree, ("other", 0)) == ""


def test_summary_refreshes_on_each_signal(tree, doc, qtbot) -> None:
    item = tree.item_for(("bcs", 0))
    item.setText(1, "stale")
    doc.stale_changed.emit()
    assert tree.item_for(("bcs", 0)).text(1).startswith("Convection")
    for signal in (doc.geometry_built, doc.mesh_changed, doc.results_changed):
        tree.item_for(("bcs", 0)).setText(1, "stale")
        signal.emit()
        assert tree.item_for(("bcs", 0)).text(1).startswith("Convection")
    mesh_item = tree.section_item("mesh")
    mesh_item.setText(1, "stale")
    doc.set_mesh(api.mesh(doc.model, doc.built))
    assert mesh_item.text(1) != "stale" and mesh_item.text(1).endswith("current")


def test_summary_follows_a_model_edit_and_undo(tree, doc) -> None:
    doc.edit("h", lambda m: setattr(m.bcs[0], "h", Constant(10.0)))
    assert "h 10 W/(m^2 K)" in summary(tree, ("bcs", 0))
    doc.undo_stack.undo()
    assert "h 750 W/(m^2 K)" in summary(tree, ("bcs", 0))


def test_column_one_is_not_editable_and_rename_edits_column_zero(tree, doc) -> None:
    item = tree.item_for(("bcs", 0))
    index = tree.indexFromItem(item, 1)
    assert tree.edit(index, tree.EditTrigger.AllEditTriggers, None) is False
    tree.begin_rename(("bcs", 0))
    item.setText(0, "renamed")
    assert doc.model.bcs[0].name == "renamed"
    count = doc.undo_stack.count()
    tree.item_for(("bcs", 0)).setText(1, "typed by hand")  # ignored by the rename handler
    assert doc.model.bcs[0].name == "renamed"
    assert doc.undo_stack.count() == count


def test_view_toggle_hides_the_column(window, doc) -> None:
    tree, _ = attach_tree(window, doc)
    action = window.actions[ts.ACTION_ID]
    assert action.isCheckable() and action.isChecked()
    assert action in window.menus["view"].actions()
    assert not tree.isColumnHidden(1)
    action.setChecked(False)
    assert tree.isColumnHidden(1)
    action.setChecked(True)
    assert not tree.isColumnHidden(1)


def test_dock_title(window, doc) -> None:
    attach_tree(window, doc)
    assert window.model_dock.windowTitle() == "Model — plate · planar · t 1 m · K"
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC")))
    assert window.model_dock.windowTitle().endswith("· °C")
    doc.edit("thick", lambda m: m.regions.append(_region(m, 2.0)))
    assert "t " not in window.model_dock.windowTitle()
    doc.edit("axi", lambda m: setattr(m, "analysis", "axisymmetric"))
    assert window.model_dock.windowTitle() == "Model — plate · axisymmetric · °C"


def _region(model: Any, thickness: float):
    from thermalfea.model.model import RegionAssignment

    return RegionAssignment(selection="body", material="Copper (pure)", thickness=thickness)


def test_controller_skips_a_window_without_a_dock(doc, tree) -> None:
    fake = SimpleNamespace()
    controller = ts.TreeSummaryController(fake, doc, tree)  # type: ignore[arg-type]
    controller.update_title()
