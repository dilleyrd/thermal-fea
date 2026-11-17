"""Unit systems (Data §7, M10.4): conversions, labels, presets, storage."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import unit_label as forms_unit_label
from thermalfea.core.units import (
    PRESETS,
    QUANTITIES,
    UnitSettings,
    from_si,
    is_si,
    si_label,
    to_si,
    unit_label,
    units_of,
)
from thermalfea.model.model import Model
from thermalfea.model.serialize import from_json, to_json

# Definitions the task fixes; the factors under test are recomputed from them here.
INCH, FOOT, LBM = 0.0254, 0.3048, 0.45359237
BTU, LBF, HOUR = 1055.05585262, 4.4482216152605, 3600.0

_FIELDS = [f.name for f in dataclasses.fields(UnitSettings)]


def _settings(quantity: str, unit: str) -> UnitSettings:
    name = "temperature" if quantity == "temperature_difference" else quantity
    return UnitSettings(**{name: unit})


def test_every_quantity_has_a_field_or_follows_temperature() -> None:
    assert set(_FIELDS) == set(QUANTITIES) - {"temperature_difference"}
    assert {"velocity", "area", "angle"} <= set(QUANTITIES)


@pytest.mark.parametrize("quantity", QUANTITIES)
def test_round_trip_every_unit(quantity: str) -> None:
    values = np.array([-12.5, 0.0, 1.0, 273.15, 4.2e5])
    for unit in units_of(quantity):
        s = _settings(quantity, unit)
        assert np.allclose(to_si(from_si(values, quantity, s), quantity, s), values, rtol=1e-13,
                           atol=1e-9)
        assert to_si(from_si(7.5, quantity, s), quantity, s) == pytest.approx(7.5, rel=1e-13)
        assert isinstance(from_si(7.5, quantity, s), float)
        assert isinstance(from_si(values, quantity, s), np.ndarray)


@pytest.mark.parametrize("quantity", QUANTITIES)
def test_default_is_the_identity_with_si_labels(quantity: str) -> None:
    s = UnitSettings()
    assert from_si(3.25, quantity, s) == 3.25
    assert to_si(3.25, quantity, s) == 3.25 if quantity != "temperature" else True
    assert is_si(quantity, s)
    assert unit_label(quantity, s) == si_label(quantity)
    assert units_of(quantity)[0] in (s.unit(quantity),)


def test_default_labels_are_unchanged() -> None:
    s = UnitSettings()
    assert [unit_label(q, s) for q in QUANTITIES[:13]] == [
        "m", "K", "K", "W/(m K)", "W/(m^2 K)", "W/m^2", "W/m^3", "W", "kg/m^3", "J/(kg K)",
        "s", "kg/s", "Pa",
    ]
    assert unit_label(None, s) == ""
    assert forms_unit_label is unit_label


def test_hand_checked_values() -> None:
    us = PRESETS["US customary"]
    k = BTU / (HOUR * FOOT) * 1.8
    assert k == pytest.approx(1.730734666, rel=1e-8)
    assert to_si(1.0, "conductivity", us) == pytest.approx(k, rel=1e-14)
    assert to_si(1.0, "htc", us) == pytest.approx(BTU * 1.8 / (HOUR * FOOT**2), rel=1e-14)
    assert to_si(1.0, "htc", us) == pytest.approx(5.678263, rel=1e-6)
    assert to_si(1.0, "heat_flux", us) == pytest.approx(BTU / (HOUR * FOOT**2), rel=1e-14)
    assert to_si(1.0, "heat_gen", us) == pytest.approx(BTU / (HOUR * FOOT**3), rel=1e-14)
    assert to_si(1.0, "power", us) == pytest.approx(BTU / HOUR, rel=1e-14)
    assert to_si(1.0, "density", us) == pytest.approx(LBM / FOOT**3, rel=1e-14)
    assert to_si(1.0, "specific_heat", us) == pytest.approx(BTU * 1.8 / LBM, rel=1e-14)
    assert to_si(1.0, "specific_heat", us) == pytest.approx(4186.8, rel=1e-5)
    assert to_si(1.0, "length", us) == pytest.approx(INCH, rel=1e-15)
    assert to_si(1.0, "velocity", us) == pytest.approx(FOOT, rel=1e-15)
    assert to_si(1.0, "area", us) == pytest.approx(INCH**2, rel=1e-15)
    assert to_si(180.0, "angle", us) == pytest.approx(np.pi, rel=1e-15)
    assert to_si(1.0, "pressure", us) == pytest.approx(LBF / INCH**2, rel=1e-14)
    assert to_si(1.0, "pressure", us) == pytest.approx(6894.757, rel=1e-6)
    assert from_si(1e5, "pressure", us) == pytest.approx(14.5037738, rel=1e-7)
    assert from_si(373.15, "temperature", us) == pytest.approx(212.0)
    assert from_si(373.15, "temperature", UnitSettings(temperature="degC")) == pytest.approx(100)
    assert from_si(100.0, "temperature_difference", us) == pytest.approx(180.0)
    assert from_si(100.0, "temperature_difference", UnitSettings(temperature="degC")) == 100.0
    assert to_si(1.0, "mass_flow", UnitSettings(mass_flow="lbm/h")) == pytest.approx(LBM / 3600)
    assert to_si(2.0, "time", UnitSettings(time="min")) == 120.0
    assert to_si(1.5, "time", UnitSettings(time="h")) == 5400.0
    assert to_si(1.0, "pressure", UnitSettings(pressure="bar")) == 1e5
    assert to_si(2.0, "pressure", UnitSettings(pressure="MPa")) == 2e6


def test_mm_units() -> None:
    mm = PRESETS["SI (mm)"]
    assert to_si(25.0, "length", mm) == pytest.approx(0.025)
    assert to_si(1.0, "conductivity", mm) == pytest.approx(1000.0)  # W/(mm K) -> W/(m K)
    assert to_si(1.0, "htc", mm) == pytest.approx(1e6)
    assert to_si(1.0, "heat_flux", mm) == pytest.approx(1e6)
    assert to_si(1.0, "heat_gen", mm) == pytest.approx(1e9)
    assert to_si(1.0, "density", mm) == pytest.approx(1e9)
    assert to_si(1.0, "area", mm) == pytest.approx(1e-6)
    assert to_si(1.0, "velocity", mm) == pytest.approx(1e-3)
    assert to_si(1.0, "pressure", mm) == pytest.approx(1e6)


def test_labels_of_presets() -> None:
    us = PRESETS["US customary"]
    assert unit_label("temperature", us) == "°F"
    assert unit_label("temperature_difference", us) == "°F"
    assert unit_label("conductivity", us) == "BTU/(h ft °F)"
    assert unit_label("htc", us) == "BTU/(h ft^2 °F)"
    assert unit_label("specific_heat", us) == "BTU/(lbm °F)"
    assert unit_label("pressure", us) == "psi"
    assert unit_label("temperature", UnitSettings(temperature="degC")) == "°C"
    assert unit_label("conductivity", PRESETS["SI (mm)"]) == "W/(mm K)"


def test_units_of_lists_si_first() -> None:
    assert units_of("length") == ("m", "mm", "in")
    assert units_of("pressure") == ("Pa", "kPa", "MPa", "bar", "psi")
    assert units_of("angle") == ("rad", "deg")
    assert units_of("temperature_difference") == ("K", "degC", "degF")
    for q in QUANTITIES:
        assert is_si(q, UnitSettings()) and len(units_of(q)) >= 2


def test_presets() -> None:
    assert set(PRESETS) == {"SI (m)", "SI (mm)", "US customary"}
    assert UnitSettings.preset("SI (m)") == UnitSettings()
    mm = UnitSettings.preset("SI (mm)")
    assert (mm.length, mm.conductivity, mm.htc, mm.heat_flux, mm.heat_gen) == (
        "mm", "W/(mm K)", "W/(mm^2 K)", "W/mm^2", "W/mm^3")
    assert (mm.density, mm.pressure, mm.velocity, mm.area, mm.angle) == (
        "kg/mm^3", "MPa", "mm/s", "mm^2", "deg")
    assert (mm.power, mm.specific_heat, mm.time, mm.mass_flow) == ("W", "J/(kg K)", "s", "kg/s")
    us = UnitSettings.preset("US customary")
    assert us.temperature == "degF" and us.length == "in" and us.power == "BTU/h"
    assert (us.time, us.mass_flow, us.pressure, us.velocity) == ("s", "lbm/s", "psi", "ft/s")
    # temperature handling
    assert UnitSettings.preset("SI (mm)", "degC").temperature == "degC"
    assert UnitSettings.preset("SI (m)", "K").temperature == "K"
    assert UnitSettings.preset("SI (m)", "degF").temperature == "degC"
    assert UnitSettings.preset("SI (mm)", "degF").temperature == "degC"
    assert UnitSettings.preset("US customary", "degC").temperature == "degF"
    # presets are copies
    UnitSettings.preset("SI (m)").length = "mm"
    assert PRESETS["SI (m)"].length == "m"


def test_validation_errors() -> None:
    for name in _FIELDS:
        with pytest.raises(ModelError, match="unit"):
            UnitSettings(**{name: "furlong"})
    with pytest.raises(ModelError):
        UnitSettings(pressure="mm")  # a unit of another quantity
    with pytest.raises(ModelError, match="quantity"):
        to_si(1.0, "luminosity", UnitSettings())
    with pytest.raises(ModelError, match="quantity"):
        from_si(1.0, "luminosity", UnitSettings())
    with pytest.raises(ModelError, match="quantity"):
        unit_label("luminosity", UnitSettings())
    with pytest.raises(ModelError, match="preset"):
        UnitSettings.preset("cubits")
    with pytest.raises(ModelError, match="temperature"):
        UnitSettings.preset("SI (m)", "rankine")


def test_settings_round_trip_through_a_file(tmp_path: Path) -> None:
    model = Model(display_units=UnitSettings.preset("US customary"))
    path = tmp_path / "m.tfea"
    api.save(model, path)
    loaded = api.load(path)
    assert loaded.display_units == model.display_units
    # the file stores a plain dict of identifiers
    stored = json.loads(path.read_text(encoding="utf-8"))["display_units"]
    assert stored["length"] == "in" and stored["pressure"] == "psi"
    assert from_json(to_json(model)).display_units == model.display_units


def test_old_file_with_only_temperature_and_length_loads() -> None:
    data = to_json(Model())
    data["display_units"] = {"temperature": "degC", "length": "mm"}
    loaded = from_json(data)
    assert loaded.display_units == UnitSettings(temperature="degC", length="mm")
    data["display_units"] = {"temperature": "K", "length": "m", "pressure": "psi"}
    assert from_json(data).display_units.pressure == "psi"
    data["display_units"] = {"pressure": "mm"}
    with pytest.raises(ModelError):
        from_json(data)
