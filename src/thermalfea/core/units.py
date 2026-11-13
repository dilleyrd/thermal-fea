"""Display units (Data §7). Internal values are always SI with temperature in kelvin.

Until task M10.4 only the temperature unit is selectable; every other quantity is SI.
"""

from __future__ import annotations

from dataclasses import dataclass
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
)

_TEMPERATURE_UNITS = ("K", "degC", "degF")
_LENGTH_UNITS = ("m", "mm", "in")


@dataclass
class UnitSettings:
    """Display-unit choices.

    Parameters
    ----------
    temperature : {"K", "degC", "degF"}
        Unit used to show and enter temperatures.
    length : {"m", "mm", "in"}
        Unit used to show and enter lengths (only ``"m"`` has an effect before M10.4).
    """

    temperature: Literal["K", "degC", "degF"] = "K"
    length: Literal["m", "mm", "in"] = "m"

    def __post_init__(self) -> None:
        if self.temperature not in _TEMPERATURE_UNITS:
            raise ModelError(f"unknown temperature unit {self.temperature!r}")
        if self.length not in _LENGTH_UNITS:
            raise ModelError(f"unknown length unit {self.length!r}")


def _check(quantity: str) -> None:
    if quantity not in QUANTITIES:
        raise ModelError(f"unknown quantity {quantity!r}")


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
    elif quantity == "temperature_difference" and settings.temperature == "degF":
        v = v / 1.8
    return float(v) if v.ndim == 0 else v


def from_si(value: float | ndarray, quantity: str, settings: UnitSettings) -> float | ndarray:
    """Convert an SI value to display units (inverse of :func:`to_si`)."""
    _check(quantity)
    v = np.asarray(value, dtype=float)
    if quantity == "temperature":
        if settings.temperature == "degC":
            v = v - 273.15
        elif settings.temperature == "degF":
            v = (v - 273.15) * 1.8 + 32.0
    elif quantity == "temperature_difference" and settings.temperature == "degF":
        v = v * 1.8
    return float(v) if v.ndim == 0 else v
