"""M11.51: Contacts, Flow and Enclosures fold into one dimmed node while all are empty."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QTreeWidgetItem

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.tree import FOLDED_TITLE, ModelTree
from thermalfea.model import bcs
from thermalfea.model.bcs import Contact, FlowNetwork

#: The top-level titles of a model with every section shown (order of SECTIONS).
EXPANDED_TITLES = [
    "Geometry", "Materials", "Regions", "Selections", "Mesh", "Initial Condition",
    "Loads & Boundary Conditions", "Contacts", "Flow", "Enclosures", "Analysis Settings",
    "Solution",
]  # fmt: skip
#: The top-level titles of an empty model.
FOLDED_TITLES = [
    "Geometry", "Materials", "Regions", "Selections", "Mesh", "Initial Condition",
    "Loads & Boundary Conditions", FOLDED_TITLE, "Analysis Settings", "Solution",
]  # fmt: skip


@pytest.fixture
def doc(qtbot) -> Document:
    return Document(api.new_model(name="plate"))


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


def top_titles(tree: ModelTree) -> list[str]:
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def folded_item(tree: ModelTree) -> QTreeWidgetItem:
    return tree.section_item("folded")


def folded_action(tree: ModelTree, text: str):
    actions = tree.actions_for(folded_item(tree))
    return next(a for a in actions if a.text() == text)


def a_stream() -> bcs.Stream:
    return bcs.Stream(
        name="s1", fluid="Water", mode="in_plane", walls=[], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=Constant(300.0),
    )  # fmt: skip


def test_empty_model_folds_three_sections_into_one_dimmed_node(tree, doc) -> None:
    assert top_titles(tree) == FOLDED_TITLES
    for absent in ("Contacts", "Flow", "Enclosures"):
        assert absent not in top_titles(tree)
    item = folded_item(tree)
    assert item.text(0) == "Contacts · Flow · Enclosures"
    assert item.childCount() == 0
    assert tree.address_of(item) is None
    assert tree.ref_of(item).section == "folded"
    assert item.font(0).italic()
    dim = tree.palette().brush(QPalette.ColorRole.PlaceholderText).color()
    assert item.foreground(0).color() == dim
    # the folded node sits where Contacts would be
    assert tree.indexOfTopLevelItem(item) == 7
    # the sections that are shown when unfolded do not exist in the tree
    assert tree._find_section("contacts") is None
    assert tree._find_section("flow") is None
    assert tree._find_section("enclosures") is None


def test_adding_a_contact_unfolds_in_the_original_order(tree, doc) -> None:
    folded_action(tree, "Add contact").trigger()
    assert [c.name for c in doc.model.contacts] == ["Contact 1"]
    assert top_titles(tree) == EXPANDED_TITLES
    assert tree._find_section("folded") is None
    contacts = tree.section_item("contacts")
    assert [contacts.child(i).text(0) for i in range(contacts.childCount())] == ["Contact 1"]
    assert tree.address_of(tree.currentItem()) == ("contacts", 0)
    flow = tree.section_item("flow")
    assert [flow.child(i).text(0) for i in range(flow.childCount())] == ["Streams", "Network"]


def test_folded_menu_offers_three_actions(tree) -> None:
    texts = [a.text() for a in tree.actions_for(folded_item(tree))]
    assert texts == ["Add contact", "Add stream", "Create network"]
    menu = tree.build_menu(folded_item(tree))
    assert [a.text() for a in menu.actions()] == ["Add contact", "Add stream", "Create network"]


def test_add_contact_from_the_folded_menu(tree, doc) -> None:
    folded_action(tree, "Add contact").trigger()
    assert len(doc.model.contacts) == 1
    assert isinstance(doc.model.contacts[0], Contact)
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.undoText() == "Add contact"


def test_add_stream_from_the_folded_menu(tree, doc) -> None:
    # without a stream the new stream is asked for in a dialog, as in the streams section
    folded_action(tree, "Add stream").trigger()
    dialog = tree.stream_dialog
    assert not dialog.isHidden()
    assert doc.model.streams == []
    assert top_titles(tree) == FOLDED_TITLES  # nothing added yet, still folded
    dialog.stream_requested.emit(a_stream())
    assert [s.name for s in doc.model.streams] == ["Stream 1"]
    assert top_titles(tree) == EXPANDED_TITLES
    flow = tree.section_item("flow")
    streams = flow.child(0)
    assert streams.text(0) == "Streams" and streams.childCount() == 1
    assert doc.undo_stack.undoText() == "Add stream"


def test_create_network_from_the_folded_menu(tree, doc) -> None:
    folded_action(tree, "Create network").trigger()
    assert isinstance(doc.model.network, FlowNetwork)
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.undoText() == "Create network"
    assert top_titles(tree) == EXPANDED_TITLES
    flow = tree.section_item("flow")
    assert [flow.child(i).text(0) for i in range(flow.childCount())] == ["Streams", "Network"]
    assert tree.address_of(flow.child(1)) == ("network",)


def test_undo_back_to_empty_folds_again(tree, doc) -> None:
    folded_action(tree, "Add contact").trigger()
    assert top_titles(tree) == EXPANDED_TITLES
    doc.undo_stack.undo()
    assert doc.model.contacts == []
    assert top_titles(tree) == FOLDED_TITLES
    assert folded_item(tree).text(0) == FOLDED_TITLE


def test_one_non_empty_section_unfolds_all_three(tree, doc) -> None:
    # a network alone is enough to show the three sections
    doc.edit("Create network", lambda m: setattr(m, "network", FlowNetwork()))
    assert top_titles(tree) == EXPANDED_TITLES
    doc.undo_stack.undo()
    assert top_titles(tree) == FOLDED_TITLES


def test_folded_node_summary_is_none(tree) -> None:
    tree.refresh_summaries()
    assert tree.topLevelItem(7).text(1) == "none"
    assert folded_item(tree).text(1) == "none"
