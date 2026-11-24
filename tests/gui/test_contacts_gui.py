"""M10.1 GUI support: thermal contacts in the panel, the issue list, the viewport and a solve.

The model tree has no Contacts node yet (see the report of this change), so the contacts are
created with :meth:`ModelTree.add_contact` and shown with :meth:`PropertyController.show_object`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.functions import Constant, Expression
from thermalfea.gui.document import Document
from thermalfea.gui.issues import address_for_issue
from thermalfea.gui.load_symbols import CONTACT_KIND, LoadSymbolController
from thermalfea.gui.panels import PropertyController
from thermalfea.gui.property_panels.contact import TEMPERATURE_MESSAGE, ContactPanel
from thermalfea.gui.scene import LoadSymbol
from thermalfea.gui.tree import ModelTree
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Contact, FixedTemperature
from thermalfea.model.validate import validate

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
H_C = 2000.0  # W/(m^2 K), the conductance of V-35
TOL = 1e-9


class FakeView:
    """Records what the controller sends through the ``SceneView`` interface."""

    def __init__(self) -> None:
        self.symbols: list[LoadSymbol] = []
        self.highlights: list[tuple[int, list[int]]] = []

    def set_symbols(self, symbols: list[LoadSymbol]) -> None:
        self.symbols = list(symbols)

    def set_overlay(self, layer: str, items: list) -> None:
        pass

    def highlight(self, dim: int, tags: list[int]) -> None:
        self.highlights.append((dim, list(tags)))


def _two_layers(model) -> object:
    """Two 1 x 0.5 rectangles side by side with the V-35 selections; returns the build."""
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 1.0, 0.5)
    geo.rectangle(1.0, 0.0, 1.0, 0.5)
    built = api.build(model)
    api.select_curves(model, built, "interface", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_surfaces(model, built, "layer1", where=lambda s: s.center[0] < 1.0)
    api.select_surfaces(model, built, "layer2", where=lambda s: s.center[0] > 1.0)
    return built


@pytest.fixture
def doc(qtbot) -> Document:
    """A built two-layer model with a coarse mesh, no conditions and no contact."""
    model = api.new_model(name="contact")
    built = _two_layers(model)
    model.mesh_settings.global_size = 0.25
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


@pytest.fixture
def controller(window, doc, tree) -> PropertyController:
    return PropertyController(window, doc, tree)


def _contact(doc: Document, selection: str = "interface") -> None:
    doc.edit(
        "Add contact",
        lambda m: m.contacts.append(Contact("gap", selection, conductance=Constant(H_C))),
    )


# ------------------------------------------------------------------------ tree actions
def test_add_contact_is_one_undo_step_with_unique_names(doc, tree) -> None:
    count = doc.undo_stack.count()
    address = tree.add_contact()
    assert address == ("contacts", 0)
    assert doc.undo_stack.count() == count + 1
    contact = doc.model.contacts[0]
    assert contact.name == "Contact 1"
    assert contact.selection == ""
    assert contact.conductance == Constant(0.0)  # the neutral value, no physical number
    tree.add_contact()
    assert [c.name for c in doc.model.contacts] == ["Contact 1", "Contact 2"]


def test_add_contact_undo_restores_the_model(doc, tree) -> None:
    tree.add_contact()
    doc.undo_stack.undo()
    assert doc.model.contacts == []


# ------------------------------------------------------------------------------- panel
def test_panel_shows_selection_and_conductance(controller, tree, doc) -> None:
    tree.add_contact()
    controller.show_object(("contacts", 0))
    panel = controller.panel
    assert isinstance(panel, ContactPanel)
    assert {"selection", "conductance"} <= set(panel.editors)


def test_constant_conductance_is_one_undo_step(controller, tree, doc) -> None:
    tree.add_contact()
    controller.show_object(("contacts", 0))
    count = doc.undo_stack.count()
    assert controller.panel.apply("conductance", Constant(1500.0))
    assert doc.undo_stack.count() == count + 1
    assert doc.model.contacts[0].conductance.value == 1500.0


def test_temperature_dependent_conductance_is_refused(controller, tree, doc) -> None:
    tree.add_contact()
    controller.show_object(("contacts", 0))
    panel = controller.panel
    before = doc.model.contacts[0].conductance
    count = doc.undo_stack.count()
    assert not panel.apply("conductance", Expression("100 + T"))
    assert doc.undo_stack.count() == count
    assert doc.model.contacts[0].conductance == before
    assert panel.error_text("conductance") == TEMPERATURE_MESSAGE
    assert TEMPERATURE_MESSAGE in panel.error_label.text()


def test_time_dependent_conductance_is_accepted(controller, tree, doc) -> None:
    tree.add_contact()
    controller.show_object(("contacts", 0))
    assert controller.panel.apply("conductance", Expression("100 + 10*t"))
    conductance = doc.model.contacts[0].conductance
    assert conductance.depends_on_time and not conductance.depends_on_T
    assert controller.panel.error_text("conductance") == ""


def test_editing_a_contact_makes_only_the_results_stale(controller, tree, doc) -> None:
    doc.set_mesh(api.mesh(doc.model, doc.built))
    doc._clear_stale(False, False, False)  # a clean state to compare against
    tree.add_contact()
    controller.show_object(("contacts", 0))
    assert controller.panel.apply("selection", "interface")
    assert controller.panel.apply("conductance", Constant(1500.0))
    assert doc.results_stale
    assert not doc.mesh_stale
    assert not doc.geometry_stale


# ------------------------------------------------------------------------------ issues
def test_contact_on_a_non_interface_maps_to_the_contact(doc) -> None:
    _contact(doc, selection="bottom")  # a boundary curve borders one region only
    issues = [i for i in validate(doc.model, doc.built) if i.kind == "contact"]
    assert issues  # one per boundary curve of the selection
    assert {i.code for i in issues} == {"contact-not-interface"}
    assert all(address_for_issue(doc.model, i) == ("contacts", 0) for i in issues)


def test_contact_issue_selects_nothing_when_the_contact_is_gone(doc) -> None:
    _contact(doc, selection="bottom")
    issue = [i for i in validate(doc.model, doc.built) if i.kind == "contact"][0]
    doc.model.contacts.clear()
    assert address_for_issue(doc.model, issue) is None


# ----------------------------------------------------------------------------- symbols
def test_contact_on_an_interface_gets_a_symbol(qtbot, window, doc) -> None:
    _contact(doc, selection="interface")
    view = FakeView()
    LoadSymbolController(window, doc, view)
    symbols = [s for s in view.symbols if s.kind == CONTACT_KIND]
    assert len(symbols) == 1
    assert symbols[0].label == "gap"
    assert symbols[0].dim == 1
    assert symbols[0].tags
    assert symbols[0].color is not None


def test_contact_with_empty_selection_gets_no_symbol(qtbot, window, doc) -> None:
    _contact(doc, selection="")
    view = FakeView()
    LoadSymbolController(window, doc, view)
    assert [s for s in view.symbols if s.kind == CONTACT_KIND] == []


def test_selecting_a_contact_highlights_its_curves(qtbot, window, doc, tree) -> None:
    _contact(doc, selection="interface")
    view = FakeView()
    ctl = LoadSymbolController(window, doc, view, tree)
    ctl.highlight_address(("contacts", 0))
    expected = doc.model.selections["interface"].tags
    assert view.highlights[-1] == (1, list(expected))


# ----------------------------------------------------------------- end to end (V-35)
def _examples():
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    return importlib.import_module("common"), importlib.import_module("v11_two_layer_slab")


def test_gui_made_contact_gives_the_series_jump(qtbot, window) -> None:
    """The V-35 model made with the GUI helpers: its temperature jump is q / h_c (1e-9)."""
    common, v11 = _examples()
    L1, L2, K1, K2, T0, TL, N = v11.L1, v11.L2, v11.K1, v11.K2, v11.T0, v11.TL, v11.N
    model = api.new_model("planar", name="V-35 GUI")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, L1, v11.HEIGHT)
    geo.rectangle(L1, 0.0, L2, v11.HEIGHT)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, L1 + L2, v11.HEIGHT)
    api.select_surfaces(model, built, "layer1", where=lambda s: s.center[0] < L1)
    api.select_surfaces(model, built, "layer2", where=lambda s: s.center[0] > L1)
    api.select_curves(model, built, "interface", where=lambda c: abs(c.center[0] - L1) < 1e-9)
    model.materials["good"] = Material("good", K1, common.RHO, common.CP)
    model.materials["poor"] = Material("poor", K2, common.RHO, common.CP)
    api.assign_region(model, "layer1", material="good")
    api.assign_region(model, "layer2", material="poor")
    model.bcs += [FixedTemperature("hot", "left", T=T0), FixedTemperature("cold", "right", T=TL)]
    common.set_element_type(model, "Q4")
    settings = model.mesh_settings
    settings.global_size = L1 / N
    settings.curve_divisions = {"bottom": N, "top": N, "left": 1, "right": 1, "interface": 1}
    settings.structured_surfaces = ["all"]

    document = Document(model)
    document.set_built(built)
    tree = ModelTree(document)
    qtbot.addWidget(tree)
    controller = PropertyController(window, document, tree)
    address = tree.add_contact()
    controller.show_object(address)
    assert controller.panel.apply("selection", "interface")
    assert controller.panel.apply("conductance", Constant(H_C))

    model = document.model
    mesh = api.mesh(model, built)
    result = api.solve(model, mesh, built=built)

    r1, r2, rc = L1 / K1, L2 / K2, 1.0 / H_C
    q = (T0 - TL) / (r1 + rc + r2)
    mesh = result.mesh  # the opened mesh: two nodes per interface position
    T = result.temperature()
    x = mesh.nodes[:, 0]
    in_layer2 = np.zeros(mesh.n_nodes, dtype=bool)
    for block in mesh.blocks:
        centre = mesh.nodes[block.conn][:, :, 0].mean(axis=1)
        in_layer2[block.conn[centre > L1]] = True
    on_interface = np.isclose(x, L1)
    side_a, side_b = on_interface & ~in_layer2, on_interface & in_layer2
    jump = float(T[side_a].mean() - T[side_b].mean())
    assert abs(jump - q / H_C) / (q / H_C) <= TOL


# ------------------------------------------------- through the tree node (added in review)


def _tree_and_document(window):
    from thermalfea import api
    from thermalfea.gui.document import Document
    from thermalfea.gui.panels import attach_tree

    document = Document(api.new_model(name="contacts"), parent=window)
    tree, properties = attach_tree(window, document, None)
    return tree, properties, document


def test_contacts_node_actions_and_panel(window) -> None:
    from thermalfea.gui.property_panels.contact import ContactPanel

    tree, properties, document = _tree_and_document(window)
    # an empty model folds Contacts, Flow and Enclosures into one line (M11.51), which
    # offers Add contact; once a contact exists the Contacts section is back
    node = tree.section_item("folded")
    (add,) = [a for a in tree.actions_for(node) if a.data() == ("add_contact", None)]
    add.trigger()
    node = tree.section_item("contacts")
    assert node.text(0) == "Contacts"
    (add,) = [a for a in tree.actions_for(node) if a.data() == ("add_contact", None)]
    add.trigger()
    assert [c.name for c in document.model.contacts] == ["Contact 1", "Contact 2"]
    node = tree.section_item("contacts")  # the tree is rebuilt after every edit
    assert [node.child(i).text(0) for i in range(node.childCount())] == ["Contact 1", "Contact 2"]
    assert document.undo_stack.count() == 2
    # selecting an item opens the contact panel
    properties.show_object(("contacts", 0))
    assert isinstance(properties.panel, ContactPanel)
    # rename, duplicate and delete through the generic actions of the item
    item = node.child(0)
    kinds = {a.data()[0] for a in tree.actions_for(item)}
    assert {"rename", "duplicate", "delete"} <= kinds
    tree.rename(("contacts", 0), "Gap")
    tree.duplicate(("contacts", 0))
    assert [c.name for c in document.model.contacts] == ["Gap", "Gap 2", "Contact 2"]
    tree.delete(("contacts", 1))
    assert [c.name for c in document.model.contacts] == ["Gap", "Contact 2"]
    for _ in range(document.undo_stack.count()):
        document.undo_stack.undo()
    assert document.model.contacts == []
