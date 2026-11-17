"""M8.6: form specifications of Material and RegionAssignment (no Qt)."""

from __future__ import annotations

import dataclasses

from thermalfea.core.forms import form_for
from thermalfea.core.units import QUANTITIES, UnitSettings, unit_label
from thermalfea.materials.material import Material
from thermalfea.model import material_forms
from thermalfea.model.model import RegionAssignment


def _names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_material_form_is_registered_and_uses_real_fields() -> None:
    spec = form_for(Material)
    assert spec is material_forms.MATERIAL_FORM
    names = [f.name for f in spec.fields]
    assert names == ["k", "rho", "cp", "k2"]
    assert set(names) <= _names(Material)


def test_material_quantities_exist_in_units() -> None:
    spec = form_for(Material)
    quantities = {f.name: f.quantity for f in spec.fields}
    assert quantities == {
        "k": "conductivity",
        "rho": "density",
        "cp": "specific_heat",
        "k2": "conductivity",
    }
    for quantity in quantities.values():
        assert quantity in QUANTITIES
    assert spec.field("k2").optional  # isotropic when empty
    assert all(f.kind == "function" for f in spec.fields)


def test_region_form_uses_real_fields() -> None:
    spec = form_for(RegionAssignment)
    assert spec is material_forms.REGION_FORM
    assert [f.name for f in spec.fields] == ["selection", "material", "thickness", "material_angle"]
    assert {f.name for f in spec.fields} <= _names(RegionAssignment)


def test_region_fields_kinds_and_quantities() -> None:
    spec = form_for(RegionAssignment)
    selection = spec.field("selection")
    assert selection.kind == "selection" and selection.selection_dims == (2,)
    assert spec.field("material").kind == "str"
    thickness = spec.field("thickness")
    assert thickness.quantity == "length" and thickness.minimum == 0.0
    angle = spec.field("material_angle")
    assert angle.quantity == "angle"  # M10.4; stored in radians
    assert unit_label(angle.quantity, UnitSettings()) == "rad"  # the label shows the unit
