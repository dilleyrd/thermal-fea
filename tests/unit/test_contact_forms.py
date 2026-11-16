"""M10.1 GUI support: the form of a thermal contact and the V-35 example file (no Qt)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.core.units import QUANTITIES
from thermalfea.model.bcs import Contact
from thermalfea.model.contact_forms import CONTACT_FORM

EXAMPLES = Path(__file__).resolve().parents[2] / "src" / "thermalfea" / "gui" / "examples"


def test_form_fields_are_contact_fields() -> None:
    names = {f.name for f in dataclasses.fields(Contact)}
    assert [spec.name for spec in CONTACT_FORM.fields] == ["selection", "conductance"]
    assert {spec.name for spec in CONTACT_FORM.fields} <= names
    assert CONTACT_FORM.category == "contact"


def test_field_quantities_are_known() -> None:
    for spec in CONTACT_FORM.fields:
        assert spec.quantity is None or spec.quantity in QUANTITIES
    assert CONTACT_FORM.field("conductance").quantity == "htc"
    assert CONTACT_FORM.field("conductance").minimum == 0.0


def test_selection_takes_curves_only() -> None:
    spec = CONTACT_FORM.field("selection")
    assert spec.kind == "selection"
    assert spec.selection_dims == (1,)


def test_form_is_registered_for_contact() -> None:
    assert form_for(Contact) is CONTACT_FORM


def test_v35_example_is_listed_and_loads_with_one_contact() -> None:
    index = json.loads((EXAMPLES / "index.json").read_text(encoding="utf-8"))
    assert "v35_thermal_contact.tfea" in [entry["file"] for entry in index]
    model = api.load(EXAMPLES / "v35_thermal_contact.tfea")
    assert len(model.contacts) == 1
    assert model.contacts[0].selection == "interface"
