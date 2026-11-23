"""M8.4: Qt-free form metadata (FormSpec) and the BC registry."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Literal

import pytest

import thermalfea.model.bcs as bcs
from thermalfea.core import forms, registry
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, FormSpec, form_for
from thermalfea.core.functions import Constant, Function
from thermalfea.core.units import QUANTITIES, UnitSettings
from thermalfea.model.bc_forms import BC_FORMS


def test_every_builtin_bc_has_a_spec_with_real_fields() -> None:
    for tag in registry.bc_tags():
        cls = registry.bc_info(tag).cls
        if tag not in BC_FORMS:  # temporary classes of other tests are cleaned up
            continue
        spec = BC_FORMS[tag]
        names = {f.name for f in dataclasses.fields(cls)}
        assert spec.title and spec.category == "load"
        assert {f.name for f in spec.fields} <= names, tag
        for f in spec.fields:
            assert f.quantity is None or f.quantity in QUANTITIES
    assert set(BC_FORMS) == {
        "fixed_temperature", "heat_flux", "heat_flow", "heat_generation", "heat_power",
        "convection", "correlation_convection", "radiation_ambient", "symmetry", "adiabatic",
    }  # fmt: skip


def test_builtin_specs_cover_every_editable_field() -> None:
    """Everything but name/active is in the form (the tree renames and suppresses)."""
    for tag, spec in BC_FORMS.items():
        cls = registry.bc_info(tag).cls
        expected = {f.name for f in dataclasses.fields(cls)} - set(forms.EXCLUDED_FIELDS)
        assert {f.name for f in spec.fields} == expected, tag


def test_builtin_specs_are_registered_with_the_registry() -> None:
    assert registry.bc_info("convection").form is BC_FORMS["convection"]
    assert form_for(bcs.Convection).field("h").quantity == "htc"
    assert form_for(bcs.Convection).field("T_inf").quantity == "temperature"
    assert form_for(bcs.HeatFlux).field("q").quantity == "heat_flux"
    assert form_for(bcs.FixedTemperature).field("selection").selection_dims == (0, 1)


def test_form_for_derives_a_spec_for_an_unregistered_form() -> None:
    @dataclass
    class NewLoad(bcs.BoundaryCondition):
        strength: Function
        count: int = 3
        enabled: bool = False
        mode: Literal["a", "b"] = "a"
        side: Literal["l", "r"] | None = None
        scale: float | None = None
        tags: list[int] = field(default_factory=list)
        extra: dict[str, float] = field(default_factory=dict)
        label: str = field(default="x", metadata={"label": "Nice label", "tooltip": "tip"})

    spec = form_for(NewLoad)  # not registered at all: derived
    kinds = {f.name: f.kind for f in spec.fields}
    assert kinds == {
        "selection": "selection", "strength": "function", "count": "int", "enabled": "bool",
        "mode": "choice", "side": "choice", "scale": "float", "extra": "dict", "label": "str",
    }  # fmt: skip
    assert spec.title == "New Load"
    assert spec.category == "load"
    assert spec.field("side").choices == ("l", "r", None) and spec.field("side").optional
    assert spec.field("scale").optional
    assert spec.field("label").label == "Nice label" and spec.field("label").tooltip == "tip"


def test_registered_class_without_form_gets_a_derived_spec() -> None:
    @dataclass
    class TempLoad(bcs.BoundaryCondition):
        power: Function

    registry.register_bc("temp_form_load", TempLoad)
    try:
        assert registry.bc_info("temp_form_load").form is None
        spec = form_for(TempLoad)
        assert [f.name for f in spec.fields] == ["selection", "power"]
        explicit = FormSpec("Mine", [FieldSpec("power", "Power", "function", quantity="power")])
        registry.register_bc("temp_form_load", TempLoad, form=explicit)
        assert form_for(TempLoad) is explicit
        registry.register_bc("temp_form_load", TempLoad)  # re-registering keeps the form
        assert form_for(TempLoad) is explicit
    finally:
        registry._CLASSES["bc"].pop("temp_form_load")
        registry._BCS.pop("temp_form_load")


def test_non_bc_classes_are_derived_and_can_be_registered() -> None:
    from thermalfea.model.settings import MeshSettings

    spec = form_for(MeshSettings)
    kinds = {f.name: f.kind for f in spec.fields}
    assert kinds["global_size"] == "float" and kinds["order"] == "choice"
    assert spec.field("order").choices == (1, 2)
    assert kinds["curve_sizes"] == "dict" and "refinements" not in kinds
    assert spec.category == "settings"
    custom = FormSpec("Mesh", [FieldSpec("global_size", "Size", "float", quantity="length")])
    previous = forms._FORMS.get(MeshSettings)
    forms.register_form(MeshSettings, custom)
    try:
        assert form_for(MeshSettings) is custom
    finally:  # put back whatever was registered before (the built-in mesh form)
        if previous is None:
            forms._FORMS.pop(MeshSettings)
        else:
            forms._FORMS[MeshSettings] = previous


def test_field_spec_validation() -> None:
    with pytest.raises(ModelError, match="unknown form kind"):
        FieldSpec("a", "A", "nope")
    with pytest.raises(ModelError, match="unknown quantity"):
        FieldSpec("a", "A", "float", quantity="furlongs")
    with pytest.raises(ModelError, match="needs choices"):
        FieldSpec("a", "A", "choice")


def test_default_instance_and_names() -> None:
    conv = forms.default_instance(bcs.Convection, name="C", selection="s")
    assert isinstance(conv.h, Constant) and conv.h.value == 0.0
    corr = forms.default_instance(bcs.CorrelationConvection, name="K")
    assert corr.correlation == "" and corr.params == {} and corr.velocity is None
    assert forms.unique_name("Convection", ["Convection 1", "Convection 2"]) == "Convection 3"
    assert forms.copy_name("Convection 1", ["Convection 1"]) == "Convection 2"
    assert forms.copy_name("Plate", ["Plate", "Plate 2"]) == "Plate 3"
    # digits that belong to the name are not a counter
    grade = "Aluminum, Alloy 2024-T6"
    assert forms.copy_name(grade, [grade]) == f"{grade} 2"
    assert forms.copy_name("Steel 1020", ["Steel 1020"], keep_digits=True) == "Steel 1020 2"


def test_unit_labels() -> None:
    assert forms.unit_label(None, UnitSettings()) == ""
    assert forms.unit_label("temperature", UnitSettings(temperature="degC")) == "°C"
    assert forms.unit_label("htc", UnitSettings()) == "W/(m^2 K)"
    with pytest.raises(ModelError):
        forms.unit_label("bogus", UnitSettings())


@pytest.mark.parametrize("text", ["nan, 1", "1, inf", "1, -inf", "0,0; 2, nan"])
def test_xy_list_refuses_non_finite_numbers(text: str) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        forms.parse_xy_list(text)
    assert forms.parse_xy_list("0,0; 1, 0.5") == [(0.0, 0.0), (1.0, 0.5)]
