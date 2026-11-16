"""M8.9: Qt-free forms of the solution settings and the initial condition."""

from __future__ import annotations

import dataclasses

import pytest

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import (
    FIELD_KINDS,
    form_for,
    format_float_list,
    parse_float_list,
)
from thermalfea.core.units import QUANTITIES
from thermalfea.model import solution_forms
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings


def test_solution_form_covers_every_field() -> None:
    spec = form_for(SolutionSettings)
    assert spec is solution_forms.SOLUTION_FORM
    fields = {f.name for f in dataclasses.fields(SolutionSettings)}
    assert [f.name for f in spec.fields] == [
        f.name for f in dataclasses.fields(SolutionSettings)
    ]
    assert {f.name for f in spec.fields} == fields
    for f in spec.fields:
        assert f.kind in FIELD_KINDS
        assert f.quantity is None or f.quantity in QUANTITIES
        assert f.label and f.tooltip


def test_transient_only_fields_are_real_and_exclude_the_shared_ones() -> None:
    names = {f.name for f in dataclasses.fields(SolutionSettings)}
    assert set(solution_forms.TRANSIENT_ONLY_FIELDS) <= names
    shared = {"kind", "rtol", "ttol", "max_iterations", "line_search"}
    assert not shared & set(solution_forms.TRANSIENT_ONLY_FIELDS)
    assert shared | set(solution_forms.TRANSIENT_ONLY_FIELDS) == names


def test_limits_mirror_the_settings_checks() -> None:
    spec = form_for(SolutionSettings)
    assert spec.field("output_every").minimum == 1.0
    assert spec.field("max_iterations").minimum == 1.0
    assert spec.field("end_time").quantity == "time"
    for bad in ({"output_every": 0}, {"max_iterations": 0}, {"theta": 2.0}, {"theta": 0.0}):
        with pytest.raises(ModelError):
            SolutionSettings(**bad)


def test_initial_condition_form() -> None:
    spec = form_for(InitialCondition)
    assert spec is solution_forms.INITIAL_CONDITION_FORM
    assert {f.name for f in spec.fields} == {f.name for f in dataclasses.fields(InitialCondition)}
    assert spec.field("value").quantity == "temperature"


def test_float_list_round_trip_and_errors() -> None:
    assert parse_float_list("0.5, 1; 2") == [0.5, 1.0, 2.0]
    assert parse_float_list("") == []
    assert parse_float_list(format_float_list([0.25, 3.0])) == [0.25, 3.0]
    with pytest.raises(ValueError, match="not a number"):
        parse_float_list("1, x")
    with pytest.raises(ValueError, match="finite"):
        parse_float_list("1, nan")
