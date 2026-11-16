"""M8.7: the form specification of the mesh settings (no Qt)."""

from __future__ import annotations

import dataclasses

from thermalfea.core.forms import form_for, register_form
from thermalfea.model import mesh_forms
from thermalfea.model.settings import MeshSettings

#: Fields of MeshSettings that the form deliberately leaves to the mesh panel's table.
TABLE_FIELDS = {"refinements"}


def _names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_mesh_form_is_registered() -> None:
    # test_forms.py registers and then removes its own form for MeshSettings; restore the
    # registration that importing mesh_forms makes.
    register_form(MeshSettings, mesh_forms.MESH_FORM)
    assert form_for(MeshSettings) is mesh_forms.MESH_FORM


def test_form_fields_are_real_mesh_settings_fields() -> None:
    names = [f.name for f in mesh_forms.MESH_FORM.fields]
    assert len(names) == len(set(names))
    assert set(names) <= _names(MeshSettings)


def test_every_mesh_setting_except_refinements_is_in_the_form() -> None:
    names = {f.name for f in mesh_forms.MESH_FORM.fields}
    assert names == _names(MeshSettings) - TABLE_FIELDS


def test_field_kinds_and_limits() -> None:
    spec = mesh_forms.MESH_FORM
    global_size = spec.field("global_size")
    assert global_size.kind == "float" and global_size.quantity == "length"
    assert global_size.minimum == 0.0
    assert spec.field("order").choices == (1, 2)
    assert spec.field("element_shape").choices == ("tri", "quad")
    assert spec.field("algorithm").choices == ("delaunay", "frontal", "frontal_quad")
    assert spec.field("smoothing_passes").kind == "int"
    assert spec.field("smoothing_passes").minimum == 0.0
    assert spec.field("structured_surfaces").kind == "selection_list"
    assert spec.field("structured_surfaces").selection_dims == (2,)
    for name in ("curve_sizes", "point_sizes", "curve_divisions"):
        assert spec.field(name).kind == "dict"


def test_choices_contain_the_settings_defaults() -> None:
    settings = MeshSettings(global_size=0.1)
    for name in ("order", "element_shape", "algorithm"):
        assert getattr(settings, name) in mesh_forms.MESH_FORM.field(name).choices
