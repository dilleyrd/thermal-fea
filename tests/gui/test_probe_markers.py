"""M11.46: probe clicks leave value markers on the viewport overlay layer "probe"."""

from __future__ import annotations

from typing import Any

import pytest

# fixtures (``steady``, ``transient``, ``steady_case``, ...) and helpers of the display tests
from tests.gui.test_results_display import (  # noqa: F401
    RecordingView,
    make_shell,
    steady,
    steady_case,
    transient,
    transient_case,
)

from thermalfea import api
from thermalfea.core.units import UnitSettings
from thermalfea.gui.results_tools import MAX_PROBES
from thermalfea.gui.scene import OverlayMarker


class OverlayRecorder(RecordingView):
    """A recording view that also keeps the overlay layers."""

    def __init__(self) -> None:
        super().__init__()
        self.layers: dict[str, list[Any]] = {}

    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: Any) -> None:
        self.layers[layer] = list(items)

    def probe_layer(self) -> list[Any]:
        return self.layers.get("probe", [])


def shell_with_overlay(window, case, tmp_path):
    model, path = case
    shell = make_shell(window, model, path, tmp_path, view=OverlayRecorder())
    shell.doc.set_results(shell.path)
    window.actions["results.probe"].setChecked(True)
    return shell


@pytest.fixture
def steady_o(window, steady_case, tmp_path):  # noqa: F811
    shell = shell_with_overlay(window, steady_case, tmp_path)
    yield shell
    shell.ctrl.pause()


@pytest.fixture
def transient_o(window, transient_case, tmp_path):  # noqa: F811
    shell = shell_with_overlay(window, transient_case, tmp_path)
    yield shell
    shell.ctrl.pause()


def test_click_leaves_a_marker_with_the_value(steady_o) -> None:
    ctrl, view = steady_o.ctrl, steady_o.view
    view.point_picked.emit(0.37, 0.19, 0.0)
    (marker,) = view.probe_layer()
    reading = ctrl.probes[-1]
    assert isinstance(marker, OverlayMarker)
    assert (marker.x, marker.y) == (0.37, 0.19)
    assert marker.text == f"{reading.value:.4g} {reading.unit}" and "°C" in marker.text
    view.point_picked.emit(0.6, 0.3, 0.0)
    assert [(m.x, m.y) for m in view.probe_layer()] == [(0.37, 0.19), (0.6, 0.3)]


def test_no_marker_outside_the_mesh(steady_o) -> None:
    view = steady_o.view
    view.point_picked.emit(10.0, 10.0, 0.0)
    assert view.probe_layer() == [] and not steady_o.ctrl.probes[-1].inside
    view.point_picked.emit(0.37, 0.19, 0.0)
    view.point_picked.emit(10.0, 10.0, 0.0)
    assert len(view.probe_layer()) == 1


def test_markers_follow_the_step(transient_o) -> None:
    ctrl, view = transient_o.ctrl, transient_o.view
    ctrl.update(ctrl.shown, step=0)
    view.point_picked.emit(0.05, 0.25, 0.0)  # near the hot edge, where it changes fast
    before = view.probe_layer()[0].text
    count = len(ctrl.probes)
    status = transient_o.window.statusBar().currentMessage()
    ctrl.update(ctrl.shown, step=ctrl.n_steps - 1)
    (marker,) = view.probe_layer()
    assert marker.text != before
    assert ctrl.probes[-1].step == 0  # the stored reading is history, not re-evaluated
    assert len(ctrl.probes) == count
    assert transient_o.window.statusBar().currentMessage() == status


def test_markers_follow_the_display_units(transient_o) -> None:
    view = transient_o.view
    view.point_picked.emit(0.5, 0.25, 0.0)
    assert view.probe_layer()[0].text.endswith(" K")
    kelvin = float(view.probe_layer()[0].text.split()[0])
    transient_o.doc.edit(
        "units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC"))
    )
    (marker,) = view.probe_layer()
    assert marker.text.endswith("°C")
    assert float(marker.text.split()[0]) == pytest.approx(kelvin - 273.15, abs=0.1)


def test_turning_the_probe_off_clears_the_markers(steady_o) -> None:
    ctrl, view, window = steady_o.ctrl, steady_o.view, steady_o.window
    view.point_picked.emit(0.37, 0.19, 0.0)
    assert view.probe_layer()
    window.actions["results.probe"].setChecked(False)
    assert view.probe_layer() == []
    window.actions["results.probe"].setChecked(True)
    view.point_picked.emit(0.37, 0.19, 0.0)
    ctrl.set_probe(False)
    assert view.probe_layer() == []
    # and the cleared markers do not come back when the display changes
    ctrl.update(ctrl.shown, field="qmag")
    assert view.probe_layer() == []


def test_new_results_clear_the_markers(steady_o) -> None:
    view = steady_o.view
    view.point_picked.emit(0.37, 0.19, 0.0)
    assert view.probe_layer()
    steady_o.doc.set_results(steady_o.path)
    assert view.probe_layer() == []


def test_a_new_model_clears_the_markers(steady_o) -> None:
    """New / Open replace the model (and turn the probe off): no old marker may stay."""
    view = steady_o.view
    view.point_picked.emit(0.37, 0.19, 0.0)
    assert view.probe_layer()
    steady_o.doc.set_model(api.new_model(name="another"))
    assert view.probe_layer() == []


def test_at_most_max_probes_markers(steady_o) -> None:
    view = steady_o.view
    for i in range(MAX_PROBES + 5):
        view.point_picked.emit(0.1 + 0.8 * i / (MAX_PROBES + 5), 0.25, 0.0)
    assert len(view.probe_layer()) == MAX_PROBES == len(steady_o.ctrl.probes)
    assert view.probe_layer()[0].x == pytest.approx(0.1 + 0.8 * 5 / (MAX_PROBES + 5))
