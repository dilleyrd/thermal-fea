"""M2.6 — selection resolution (Data §5) and the API selection helpers."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.geometry.builder import build
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model
from thermalfea.model.selections import (
    Fingerprint,
    Selection,
    StaleSelectionError,
    fingerprint_matches,
    refresh,
    resolve,
)


def plate() -> Model:
    return Model(geometry=[g.Rectangle("plate", 0.0, 0.0, 0.6, 1.0)])


def select_all(model: Model, built) -> None:
    api.select_curves(model, built, name="bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_curves(model, built, name="sides", where=lambda c: abs(c.center[1] - 0.5) < 1e-9)
    api.select_surfaces(model, built, name="all", where=lambda s: True)
    api.select_points(model, built, name="origin", where=lambda p: max(map(abs, p.center)) < 1e-9)


def test_select_helpers() -> None:
    model = plate()
    built = build(model)
    select_all(model, built)
    assert set(model.selections) == {"bottom", "sides", "all", "origin"}
    bottom = model.selections["bottom"]
    assert (bottom.dim, len(bottom.tags)) == (1, 1)
    assert bottom.fingerprints == [built.curves[bottom.tags[0]]]
    assert bottom.fingerprints[0].measure == pytest.approx(0.6)
    assert len(model.selections["sides"].tags) == 2
    assert model.selections["all"].dim == 2
    assert model.selections["origin"].dim == 0
    by_tag = api.select_curves(model, built, name="picked", tags=bottom.tags)
    assert by_tag.fingerprints == bottom.fingerprints
    assert model.selections["picked"] is by_tag
    for name, sel in model.selections.items():
        assert resolve(sel, built) == sel.tags, name
    with pytest.raises(ModelError, match="matches nothing"):
        api.select_curves(model, built, name="none", where=lambda c: False)
    with pytest.raises(ModelError, match="no entity with tag"):
        api.select_curves(model, built, name="bad", tags=[999])
    with pytest.raises(ModelError, match="exactly one"):
        api.select_curves(model, built, name="bad")
    with pytest.raises(ModelError, match="exactly one"):
        api.select_curves(model, built, name="bad", where=lambda c: True, tags=[1])
    assert "none" not in model.selections and "bad" not in model.selections


def test_selection_survives_adding_an_unrelated_shape() -> None:
    model = plate()
    built = build(model)
    select_all(model, built)
    before = {name: list(sel.fingerprints) for name, sel in model.selections.items()}

    # new shapes placed *before* the plate change its tags; one far away changes L
    model.geometry[:0] = [g.Circle("c1", 5.0, 5.0, 0.3), g.Rectangle("r2", -4.0, 2.0, 1.0, 1.0)]
    model.geometry.append(g.Circle("far", 40.0, -30.0, 2.0))
    rebuilt = build(model)
    assert rebuilt.diagonal > 10 * built.diagonal

    old_tags = {name: list(sel.tags) for name, sel in model.selections.items()}
    assert refresh(model.selections, rebuilt) == {}
    assert any(model.selections[n].tags != old_tags[n] for n in old_tags)  # tags did move
    for name, sel in model.selections.items():
        assert sel.fingerprints == before[name]
        entities = rebuilt.entities(sel.dim)
        for tag, fp in zip(sel.tags, sel.fingerprints, strict=True):
            assert fingerprint_matches(fp, entities[tag], rebuilt.diagonal), name
    (bottom,) = model.selections["bottom"].tags
    assert rebuilt.curves[bottom].center == pytest.approx((0.3, 0.0, 0.0), abs=1e-12)


def test_selection_becomes_stale_when_its_curve_is_cut_in_two() -> None:
    model = plate()
    built = build(model)
    select_all(model, built)
    # a second region on the right half splits the bottom and top curves at x = 0.3
    model.geometry.append(g.Rectangle("inset", 0.3, 0.0, 0.3, 1.0))
    rebuilt = build(model)
    assert len(rebuilt.surfaces) == 2

    with pytest.raises(StaleSelectionError) as info:
        resolve(model.selections["bottom"], rebuilt)
    message = str(info.value)
    assert "'bottom'" in message and "stale" in message and "curve" in message
    assert "select it again" in message
    assert isinstance(info.value, ModelError)

    old_bottom_tags = list(model.selections["bottom"].tags)
    stale = refresh(model.selections, rebuilt)
    assert set(stale) == {"bottom", "all"}  # the surface was split too
    assert "'all'" in stale["all"] and "surface" in stale["all"]
    assert model.selections["bottom"].tags == old_bottom_tags  # stale ones are left alone
    # the two side curves and the corner point are untouched and still resolve
    assert len(resolve(model.selections["sides"], rebuilt)) == 2
    assert len(resolve(model.selections["origin"], rebuilt)) == 1


def test_selection_is_stale_after_a_move_or_resize() -> None:
    model = plate()
    built = build(model)
    select_all(model, built)
    moved = build(Model(geometry=[g.Rectangle("plate", 0.0, 0.001, 0.6, 1.0)]))
    with pytest.raises(StaleSelectionError, match="'bottom'"):
        resolve(model.selections["bottom"], moved)
    resized = build(Model(geometry=[g.Rectangle("plate", -0.001, 0.0, 0.602, 1.0)]))
    with pytest.raises(StaleSelectionError, match="'bottom'"):  # same centre, longer curve
        resolve(model.selections["bottom"], resized)


def test_tolerances() -> None:
    fp = Fingerprint(1, (1.0, 2.0, 0.0), 3.0, (0, 0, 0, 1, 1, 0))
    length = 10.0

    def other(dx: float = 0.0, scale: float = 1.0, dim: int = 1) -> Fingerprint:
        return Fingerprint(dim, (1.0 + dx, 2.0, 0.0), 3.0 * scale, (0, 0, 0, 1, 1, 0))

    assert fingerprint_matches(fp, other(), length)
    assert fingerprint_matches(fp, other(dx=0.9e-5), length)  # within 1e-6 * L
    assert not fingerprint_matches(fp, other(dx=1.1e-5), length)
    assert fingerprint_matches(fp, other(scale=1 + 0.9e-6), length)
    assert not fingerprint_matches(fp, other(scale=1 + 1.1e-6), length)
    assert not fingerprint_matches(fp, other(dim=2), length)
    point = Fingerprint(0, (1.0, 2.0, 0.0), 0.0, (1, 2, 0, 1, 2, 0))
    assert fingerprint_matches(point, Fingerprint(0, (1.0, 2.0, 0.0), 0.0, (1, 2, 0, 1, 2, 0)), 1.0)


def test_empty_selection_resolves_to_nothing() -> None:
    built = build(plate())
    assert resolve(Selection("empty", 1), built) == []
