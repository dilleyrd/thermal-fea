"""M8.12: the form of a flow stream covers every field of ``Stream`` except its name."""

from __future__ import annotations

from dataclasses import fields

from thermalfea.core.forms import form_for
from thermalfea.core.units import QUANTITIES
from thermalfea.model.bcs import Stream
from thermalfea.model.flow_forms import STREAM_FORM


def test_every_spec_field_is_a_stream_field() -> None:
    stream_fields = {f.name for f in fields(Stream)}
    for spec in STREAM_FORM.fields:
        assert spec.name in stream_fields, spec.name


def test_every_stream_field_except_name_is_in_the_spec() -> None:
    stream_fields = {f.name for f in fields(Stream)}
    spec_fields = [spec.name for spec in STREAM_FORM.fields]
    assert len(spec_fields) == len(set(spec_fields))
    assert stream_fields - {"name"} == set(spec_fields)


def test_quantities_are_known_or_none() -> None:
    for spec in STREAM_FORM.fields:
        assert spec.quantity is None or spec.quantity in QUANTITIES, spec.name


def test_flow_area_and_perimeter_have_no_quantity() -> None:
    # no quantity for an area or a perimeter exists in QUANTITIES
    assert STREAM_FORM.field("flow_area").quantity is None
    assert STREAM_FORM.field("wetted_perimeter").quantity is None


def test_stream_form_is_registered_for_the_class() -> None:
    assert form_for(Stream) is STREAM_FORM
