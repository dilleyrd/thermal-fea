"""Display units (Data §7). Internal values are always SI with temperature in kelvin.

:class:`UnitSettings` holds one display unit per quantity. The ``.tfea`` file and every
internal value stay SI; the settings only decide how numbers are shown and typed.

Unit identifiers are plain ASCII (``"degC"``, ``"BTU/(h ft degF)"``); :func:`unit_label`
returns the text shown to the user (``"°C"``, ``"BTU/(h ft °F)"``). Every factor is
derived from the exact definitions below, nothing else is typed in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from typing import Literal

import numpy as np
from numpy import ndarray

from .errors import ModelError

QUANTITIES = (
    "length",
    "temperature",
    "temperature_difference",
    "conductivity",
    "htc",
    "heat_flux",
    "heat_gen",
    "power",
    "density",
    "specific_heat",
    "time",
    "mass_flow",
    "pressure",
    "velocity",
    "area",
    "angle",
)

# Exact definitions (SI values of the non-SI units).
_MM = 1.0e-3  # m
_INCH = 0.0254  # m
_FOOT = 0.3048  # m
_LBM = 0.45359237  # kg
_BTU = 1055.05585262  # J (International Table)
_LBF = 4.4482216152605  # N
_HOUR = 3600.0  # s
_MINUTE = 60.0  # s
_BAR = 1.0e5  # Pa
_DEGF = 1.0 / 1.8  # K, size of one degree Fahrenheit

_TEMPERATURE_LABELS = {"K": "K", "degC": "°C", "degF": "°F"}

#: Per quantity: ``{unit id: (label, factor)}``; SI value = display value * factor.
#: The first entry of each quantity is the SI unit.
_TABLE: dict[str, dict[str, tuple[str, float]]] = {
    "length": {"m": ("m", 1.0), "mm": ("mm", _MM), "in": ("in", _INCH)},
    "conductivity": {
        "W/(m K)": ("W/(m K)", 1.0),
        "W/(mm K)": ("W/(mm K)", 1.0 / _MM),
        "BTU/(h ft degF)": ("BTU/(h ft °F)", _BTU / (_HOUR * _FOOT * _DEGF)),
    },
    "htc": {
        "W/(m^2 K)": ("W/(m^2 K)", 1.0),
        "W/(mm^2 K)": ("W/(mm^2 K)", 1.0 / _MM**2),
        "BTU/(h ft^2 degF)": ("BTU/(h ft^2 °F)", _BTU / (_HOUR * _FOOT**2 * _DEGF)),
    },
    "heat_flux": {
        "W/m^2": ("W/m^2", 1.0),
        "W/mm^2": ("W/mm^2", 1.0 / _MM**2),
        "BTU/(h ft^2)": ("BTU/(h ft^2)", _BTU / (_HOUR * _FOOT**2)),
    },
    "heat_gen": {
        "W/m^3": ("W/m^3", 1.0),
        "W/mm^3": ("W/mm^3", 1.0 / _MM**3),
        "BTU/(h ft^3)": ("BTU/(h ft^3)", _BTU / (_HOUR * _FOOT**3)),
    },
    "power": {"W": ("W", 1.0), "kW": ("kW", 1.0e3), "BTU/h": ("BTU/h", _BTU / _HOUR)},
    "density": {
        "kg/m^3": ("kg/m^3", 1.0),
        "kg/mm^3": ("kg/mm^3", 1.0 / _MM**3),
        "lbm/ft^3": ("lbm/ft^3", _LBM / _FOOT**3),
    },
    "specific_heat": {
        "J/(kg K)": ("J/(kg K)", 1.0),
        "kJ/(kg K)": ("kJ/(kg K)", 1.0e3),
        "BTU/(lbm degF)": ("BTU/(lbm °F)", _BTU / (_LBM * _DEGF)),
    },
    "time": {"s": ("s", 1.0), "min": ("min", _MINUTE), "h": ("h", _HOUR)},
    "mass_flow": {
        "kg/s": ("kg/s", 1.0),
        "lbm/s": ("lbm/s", _LBM),
        "lbm/h": ("lbm/h", _LBM / _HOUR),
    },
    "pressure": {
        "Pa": ("Pa", 1.0),
        "kPa": ("kPa", 1.0e3),
        "MPa": ("MPa", 1.0e6),
        "bar": ("bar", _BAR),
        "psi": ("psi", _LBF / _INCH**2),
    },
    "velocity": {"m/s": ("m/s", 1.0), "mm/s": ("mm/s", _MM), "ft/s": ("ft/s", _FOOT)},
    "area": {
        "m^2": ("m^2", 1.0),
        "mm^2": ("mm^2", _MM**2),
        "in^2": ("in^2", _INCH**2),
    },
    "angle": {"rad": ("rad", 1.0), "deg": ("deg", math.pi / 180.0)},
}

_TEMPERATURE_UNITS = ("K", "degC", "degF")
_LENGTH_UNITS = tuple(_TABLE["length"])


def _check(quantity: str) -> None:
    if quantity not in QUANTITIES:
        raise ModelError(f"unknown quantity {quantity!r}")


def units_of(quantity: str) -> tuple[str, ...]:
    """Return the unit identifiers offered for a quantity (the SI unit first).

    ``temperature_difference`` offers the units of ``temperature`` (it follows it).

    Parameters
    ----------
    quantity : str
        One of :data:`QUANTITIES`.
    """
    _check(quantity)
    if quantity in ("temperature", "temperature_difference"):
        return _TEMPERATURE_UNITS
    return tuple(_TABLE[quantity])


@dataclass
class UnitSettings:
    """Display-unit choices (one identifier per quantity; the default is SI).

    ``temperature_difference`` is not a field: it follows ``temperature`` (K for K and
    degC, degrees Fahrenheit for degF).

    Parameters
    ----------
    temperature : {"K", "degC", "degF"}
        Unit used to show and enter temperatures.
    length : {"m", "mm", "in"}
        Unit of lengths and coordinates.
    conductivity : {"W/(m K)", "W/(mm K)", "BTU/(h ft degF)"}
        Unit of thermal conductivity.
    htc : {"W/(m^2 K)", "W/(mm^2 K)", "BTU/(h ft^2 degF)"}
        Unit of heat-transfer coefficients and contact conductances.
    heat_flux : {"W/m^2", "W/mm^2", "BTU/(h ft^2)"}
        Unit of heat flux.
    heat_gen : {"W/m^3", "W/mm^3", "BTU/(h ft^3)"}
        Unit of volumetric heat generation.
    power : {"W", "kW", "BTU/h"}
        Unit of heat flow and power.
    density : {"kg/m^3", "kg/mm^3", "lbm/ft^3"}
        Unit of density.
    specific_heat : {"J/(kg K)", "kJ/(kg K)", "BTU/(lbm degF)"}
        Unit of specific heat.
    time : {"s", "min", "h"}
        Unit of time.
    mass_flow : {"kg/s", "lbm/s", "lbm/h"}
        Unit of mass flow.
    pressure : {"Pa", "kPa", "MPa", "bar", "psi"}
        Unit of pressure.
    velocity : {"m/s", "mm/s", "ft/s"}
        Unit of velocity.
    area : {"m^2", "mm^2", "in^2"}
        Unit of area (flow area).
    angle : {"rad", "deg"}
        Unit of angles.
    """

    temperature: Literal["K", "degC", "degF"] = "K"
    length: Literal["m", "mm", "in"] = "m"
    conductivity: Literal["W/(m K)", "W/(mm K)", "BTU/(h ft degF)"] = "W/(m K)"
    htc: Literal["W/(m^2 K)", "W/(mm^2 K)", "BTU/(h ft^2 degF)"] = "W/(m^2 K)"
    heat_flux: Literal["W/m^2", "W/mm^2", "BTU/(h ft^2)"] = "W/m^2"
    heat_gen: Literal["W/m^3", "W/mm^3", "BTU/(h ft^3)"] = "W/m^3"
    power: Literal["W", "kW", "BTU/h"] = "W"
    density: Literal["kg/m^3", "kg/mm^3", "lbm/ft^3"] = "kg/m^3"
    specific_heat: Literal["J/(kg K)", "kJ/(kg K)", "BTU/(lbm degF)"] = "J/(kg K)"
    time: Literal["s", "min", "h"] = "s"
    mass_flow: Literal["kg/s", "lbm/s", "lbm/h"] = "kg/s"
    pressure: Literal["Pa", "kPa", "MPa", "bar", "psi"] = "Pa"
    velocity: Literal["m/s", "mm/s", "ft/s"] = "m/s"
    area: Literal["m^2", "mm^2", "in^2"] = "m^2"
    angle: Literal["rad", "deg"] = "rad"

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value not in units_of(f.name):
                raise ModelError(f"unknown {f.name.replace('_', ' ')} unit {value!r}")

    def unit(self, quantity: str) -> str:
        """Return the unit identifier chosen for a quantity.

        ``temperature_difference`` returns the identifier of ``temperature``.
        """
        _check(quantity)
        return getattr(self, "temperature" if quantity == "temperature_difference" else quantity)

    @classmethod
    def preset(cls, name: str, temperature: str | None = None) -> UnitSettings:
        """Return a named preset (a key of :data:`PRESETS`).

        Parameters
        ----------
        name : str
            ``"SI (m)"``, ``"SI (mm)"`` or ``"US customary"``.
        temperature : {"K", "degC", "degF"}, optional
            The temperature unit currently in use. The SI presets keep ``K`` and
            ``degC`` and turn ``degF`` into ``degC``; ``"US customary"`` always sets
            ``degF``. Default ``"K"``.

        Raises
        ------
        ModelError
            If ``name`` is not a preset or ``temperature`` is not a temperature unit.
        """
        if name not in PRESETS:
            raise ModelError(f"unknown unit preset {name!r}")
        if temperature is not None and temperature not in _TEMPERATURE_UNITS:
            raise ModelError(f"unknown temperature unit {temperature!r}")
        base = PRESETS[name]
        if name == "US customary":
            return replace(base)
        kept = temperature if temperature in ("K", "degC") else ("degC" if temperature else "K")
        return replace(base, temperature=kept)


#: Named unit systems (the SI presets use ``K``; see :meth:`UnitSettings.preset`).
PRESETS: dict[str, UnitSettings] = {
    "SI (m)": UnitSettings(),
    "SI (mm)": UnitSettings(
        length="mm",
        conductivity="W/(mm K)",
        htc="W/(mm^2 K)",
        heat_flux="W/mm^2",
        heat_gen="W/mm^3",
        density="kg/mm^3",
        pressure="MPa",
        velocity="mm/s",
        area="mm^2",
        angle="deg",
    ),
    "US customary": UnitSettings(
        temperature="degF",
        length="in",
        conductivity="BTU/(h ft degF)",
        htc="BTU/(h ft^2 degF)",
        heat_flux="BTU/(h ft^2)",
        heat_gen="BTU/(h ft^3)",
        power="BTU/h",
        density="lbm/ft^3",
        specific_heat="BTU/(lbm degF)",
        mass_flow="lbm/s",
        pressure="psi",
        velocity="ft/s",
        area="in^2",
        angle="deg",
    ),
}


def unit_label(quantity: str | None, settings: UnitSettings) -> str:
    """Return the display-unit label of a quantity (empty for ``None``).

    Parameters
    ----------
    quantity : str or None
        One of :data:`QUANTITIES`.
    settings : UnitSettings
        Display-unit choices.
    """
    if quantity is None:
        return ""
    _check(quantity)
    if quantity in ("temperature", "temperature_difference"):
        return _TEMPERATURE_LABELS[settings.temperature]
    return _TABLE[quantity][settings.unit(quantity)][0]


def label_of(quantity: str, unit: str) -> str:
    """Return the label of one unit identifier of a quantity (``"degF"`` -> ``"°F"``).

    Raises
    ------
    ModelError
        If ``unit`` is not offered for ``quantity`` (see :func:`units_of`).
    """
    if unit not in units_of(quantity):
        raise ModelError(f"unknown {quantity.replace('_', ' ')} unit {unit!r}")
    if quantity in ("temperature", "temperature_difference"):
        return _TEMPERATURE_LABELS[unit]
    return _TABLE[quantity][unit][0]


def si_label(quantity: str) -> str:
    """Return the label of the SI unit of a quantity (``"K"`` for temperatures)."""
    _check(quantity)
    if quantity in ("temperature", "temperature_difference"):
        return "K"
    return next(iter(_TABLE[quantity].values()))[0]


def is_si(quantity: str, settings: UnitSettings) -> bool:
    """True if the display unit of ``quantity`` is its SI unit (kelvin for temperature)."""
    _check(quantity)
    return settings.unit(quantity) == units_of(quantity)[0]


def _factor(quantity: str, settings: UnitSettings) -> float:
    return _TABLE[quantity][settings.unit(quantity)][1]


def _out(v: ndarray) -> float | ndarray:
    return float(v) if v.ndim == 0 else v


def to_si(value: float | ndarray, quantity: str, settings: UnitSettings) -> float | ndarray:
    """Convert a value in display units to SI.

    Parameters
    ----------
    value : float or ndarray
        Value in the display unit of ``quantity``.
    quantity : str
        One of :data:`QUANTITIES`.
    settings : UnitSettings
        Display-unit choices.

    Returns
    -------
    float or ndarray
        The value in SI (temperatures in kelvin).
    """
    _check(quantity)
    v = np.asarray(value, dtype=float)
    if quantity == "temperature":
        if settings.temperature == "degC":
            v = v + 273.15
        elif settings.temperature == "degF":
            v = (v - 32.0) / 1.8 + 273.15
    elif quantity == "temperature_difference":
        if settings.temperature == "degF":
            v = v / 1.8
    else:
        factor = _factor(quantity, settings)
        if factor != 1.0:
            v = v * factor
    return _out(v)


def from_si(value: float | ndarray, quantity: str, settings: UnitSettings) -> float | ndarray:
    """Convert an SI value to display units (inverse of :func:`to_si`)."""
    _check(quantity)
    v = np.asarray(value, dtype=float)
    if quantity == "temperature":
        if settings.temperature == "degC":
            v = v - 273.15
        elif settings.temperature == "degF":
            v = (v - 273.15) * 1.8 + 32.0
    elif quantity == "temperature_difference":
        if settings.temperature == "degF":
            v = v * 1.8
    else:
        factor = _factor(quantity, settings)
        if factor != 1.0:
            v = v / factor
    return _out(v)
