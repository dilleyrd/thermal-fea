"""M11.75: saved result items (Data §3a; held items 17 and 3; conventions C3, C4).

Contours and vector plots are ``Model.result_items``: saved in the model file, every change
one undo step, never making results stale; they store the time shown (``None`` = last) and a
manual range in SI; the eye toggle hides the field and keeps the settings; slider drags and
an animation store one undo step; the default contour is shown, not stored, until changed.
"""

# ruff: noqa: F811  (fixtures imported from test_results_display)
from __future__ import annotations

import pytest
from tests.gui.test_results_display import (  # noqa: F401
    steady,
    steady_case,
    transient,
    transient_case,
)

from thermalfea.core.units import UnitSettings
from thermalfea.gui.document import classify_change
from thermalfea.gui.results_tools import DEFAULT_CONTOUR, ContourObject
from thermalfea.model.compare import model_changes
from thermalfea.model.result_items import ContourItem, VectorItem
from thermalfea.model.serialize import from_json, to_json


def test_the_default_contour_is_stored_by_its_first_change(steady) -> None:
    doc, ctrl = steady.doc, steady.ctrl
    assert doc.model.result_items == [] and ctrl.shown == DEFAULT_CONTOUR
    assert not doc.modified
    ctrl.update(DEFAULT_CONTOUR, banded=False)
    (item,) = doc.model.result_items
    assert isinstance(item, ContourItem) and item.name == DEFAULT_CONTOUR and not item.banded
    assert doc.modified


def test_items_are_saved_and_come_back(steady) -> None:
    doc, ctrl = steady.doc, steady.ctrl
    ctrl.add_contour("qmag")
    ctrl.update(ctrl.shown, range_mode="manual", vmin=10.0, vmax=20.0, levels=7)
    ctrl.add_vectors()
    ctrl.update(ctrl.shown, density=12, show_mesh=True)
    saved = to_json(doc.model)
    names = [o.name for o in ctrl.objects]
    reopened = from_json(saved)
    assert [i.name for i in reopened.result_items] == names
    vectors = reopened.result_items[-1]
    assert isinstance(vectors, VectorItem) and vectors.density == 12 and vectors.show_mesh
    path = doc.results_path
    doc.set_model(reopened)
    doc.set_results(path)
    assert [o.name for o in ctrl.objects] == names
    contour = ctrl.get(names[1])
    assert isinstance(contour, ContourObject)
    assert (contour.range_mode, contour.levels) == ("manual", 7)
    assert (contour.vmin, contour.vmax) == pytest.approx((10.0, 20.0))


def test_the_time_is_stored_and_the_last_step_is_none(transient) -> None:
    doc, ctrl = transient.doc, transient.ctrl
    name = ctrl.shown
    ctrl.update(name, step=2)
    (item,) = doc.model.result_items
    assert item.time == pytest.approx(ctrl.time_of(2))
    ctrl.update(name, step=ctrl.n_steps - 1)
    assert doc.model.result_items[0].time is None  # the last step, whatever a new solve stores
    target = 0.5 * (ctrl.time_of(1) + ctrl.time_of(2)) + 1e-9
    doc.edit("time", lambda m: setattr(m.result_items[0], "time", target))
    assert ctrl.get(name).step == ctrl.step_for_time(target)


def test_a_manual_range_is_stored_in_si(steady) -> None:
    doc, ctrl = steady.doc, steady.ctrl
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC")))
    name = ctrl.shown
    ctrl.update(name, range_mode="manual", vmin=20.0, vmax=80.0)  # typed in degC
    item = doc.model.result_items[0]
    assert (item.vmin, item.vmax) == pytest.approx((293.15, 353.15))
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings()))
    obj = ctrl.get(name)
    assert (obj.vmin, obj.vmax) == pytest.approx((293.15, 353.15))  # shown in K now


def test_the_eye_toggle_hides_the_field_and_keeps_the_settings(steady) -> None:
    doc, ctrl, view = steady.doc, steady.ctrl, steady.view
    name = ctrl.shown
    ctrl.update(name, levels=5)
    assert view.last is not None
    assert ctrl.set_visible(name, False)
    assert view.last is None and doc.model.result_items[0].visible is False
    assert doc.model.result_items[0].levels == 5
    assert ctrl.set_visible(name, True)
    assert view.last is not None
    doc.undo_stack.undo()
    assert view.last is None  # undoable like any change


def test_a_slider_drag_is_one_undo_step(transient) -> None:
    doc, ctrl = transient.doc, transient.ctrl
    name = ctrl.shown
    ctrl.update(name, levels=5)  # stores the default contour (another kind of change)
    count = doc.undo_stack.count()
    last = ctrl.n_steps - 1
    for step in (1, 2, 3):
        ctrl.update(name, step=step)
    assert doc.undo_stack.count() == count + 1  # the drag merged into one step
    assert ctrl.get(name).step == 3
    doc.undo_stack.undo()
    assert ctrl.get(name).step == last and ctrl.get(name).levels == 5


def test_an_animation_stores_one_step_when_it_stops(transient) -> None:
    doc, ctrl = transient.doc, transient.ctrl
    name = ctrl.shown
    ctrl.update(name, levels=5)  # stores the default contour, on its last step
    count = doc.undo_stack.count()
    ctrl.update(name, step=1)  # one undo step
    assert ctrl.play()
    ctrl.tick()
    assert ctrl.get(name).step == 2  # shown ...
    assert doc.model.result_items[0].time == pytest.approx(ctrl.time_of(1))  # ... not stored
    while ctrl.playing:
        ctrl.tick()
    assert ctrl.get(name).step == ctrl.n_steps - 1
    assert doc.model.result_items[0].time is None  # stored when it stopped
    assert doc.undo_stack.count() == count + 1  # the frames were no undo steps (merged)
    doc.undo_stack.undo()
    assert ctrl.get(name).step == ctrl.n_steps - 1 and ctrl.get(name).levels == 5


def test_result_items_never_make_results_stale() -> None:
    before = {"geometry": [], "selections": {}, "result_items": []}
    after = {"geometry": [], "selections": {}, "result_items": [{"name": "x", "type": "contour"}]}
    assert classify_change(before, after) == "none"
    from thermalfea import api

    old, new = api.new_model(), api.new_model()
    new.result_items.append(ContourItem("x"))
    assert model_changes(to_json(old), new) == []
