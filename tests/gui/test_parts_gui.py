"""M11.56 and M11.63 in the window: named parts, renaming geometry steps, marked items."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFont

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.region import RegionPanel
from thermalfea.model.model import part_name


@pytest.fixture
def doc(qtbot) -> Document:
    """A plate with a hole (a cut of two operations) and one unnamed (older) part."""
    model = api.new_model(name="plate")
    geo = api.Geometry(model)
    r = geo.rectangle(0.0, 0.0, 1.0, 0.5, id="outline")
    c = geo.circle(0.5, 0.25, 0.1, id="bore")
    geo.cut([r], [c], id="plate")
    built = api.build(model)
    api.select_surfaces(model, built, "body", where=lambda s: True)
    api.assign_region(model, "body", material="Copper (pure)")
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def shell(qtbot, window, doc):
    tree, controller = attach_tree(window, doc)
    return tree, controller


def test_add_part_names_each_part(shell, doc) -> None:
    tree, _ = shell
    assert tree.section_item("regions").text(0) == "Parts"
    tree.add_region()
    tree.add_region()
    assert [r.name for r in doc.model.regions] == ["", "Part 1", "Part 2"]
    assert [tree.item_for(("regions", i)).text(0) for i in range(3)] == ["body", "Part 1", "Part 2"]


def test_rename_a_part_inline_and_refuse_a_used_name(shell, doc) -> None:
    tree, _ = shell
    tree.add_region()
    count = doc.undo_stack.count()
    assert tree.rename(("regions", 1), "Fin")
    assert doc.model.regions[1].name == "Fin" and doc.undo_stack.count() == count + 1
    with pytest.raises(ModelError, match="already used"):
        tree.rename(("regions", 1), "body")  # the older part is shown as "body"
    assert doc.model.regions[1].name == "Fin" and doc.undo_stack.count() == count + 1
    doc.undo_stack.undo()
    assert doc.model.regions[1].name == "Part 1"


def test_the_part_panel_name_and_a_changed_selection(shell, doc) -> None:
    tree, controller = shell
    controller.show_object(("regions", 0))
    panel = controller.panel
    assert isinstance(panel, RegionPanel)
    tree.add_region()
    controller.show_object(("regions", 0))
    panel = controller.panel
    assert not panel.apply("name", "Part 1")  # used by the other part: refused
    assert doc.model.regions[0].name == ""
    # an unnamed part keeps the name it was shown with when its selection changes
    doc.model.selections["other"] = doc.model.selections["body"]
    assert panel.apply("selection", "other")
    assert doc.model.regions[0].selection == "other" and part_name(doc.model.regions[0]) == "body"


def test_rename_a_geometry_step_in_the_tree(shell, doc) -> None:
    tree, _ = shell
    data = [a.data() for a in tree.actions_for(tree.item_for(("geometry", 0)))]
    assert ("rename", ("geometry", 0)) in data
    count = doc.undo_stack.count()
    assert tree.rename(("geometry", 0), "frame")
    ops = {op.id: op for op in doc.model.geometry}
    assert "outline" not in ops and ops["plate"].objects == ["frame"]
    assert doc.undo_stack.count() == count + 1
    assert tree.item_for(("geometry", 0)).text(0) == "frame"
    with pytest.raises(ModelError, match="already used"):
        tree.rename(("geometry", 0), "bore")
    doc.undo_stack.undo()
    assert doc.model.geometry[0].id == "outline" and doc.model.geometry[2].objects == ["outline"]


def test_mark_addresses_bolds_the_items(shell) -> None:
    tree, _ = shell

    def bold(address) -> bool:
        return QFont(tree.item_for(address).font(0)).bold()

    tree.mark_addresses([("regions", 0), ("selections", "body")])
    assert bold(("regions", 0)) and bold(("selections", "body"))
    assert not bold(("geometry", 0))
    tree.mark_addresses([])
    assert not bold(("regions", 0))
