"""Material and fluid property records (Data §6). All values are SI, temperatures in kelvin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from ..core.errors import ModelError
from ..core.functions import Function, as_function, function_from_json, function_to_json

if TYPE_CHECKING:
    from ..convection.fluid_props import FluidProps


@dataclass
class PhaseChange:
    """Melting/solidification range of a material.

    Parameters
    ----------
    T_sol : float
        Solidus temperature [K].
    T_liq : float
        Liquidus temperature [K]; must exceed ``T_sol``.
    latent_heat : float
        Latent heat of fusion [J/kg].
    """

    T_sol: float
    T_liq: float
    latent_heat: float

    def __post_init__(self) -> None:
        if not self.T_liq > self.T_sol:
            raise ModelError("phase change: T_liq must be greater than T_sol")
        if not self.latent_heat > 0.0:
            raise ModelError("phase change: latent heat must be positive")


@dataclass
class MaterialSource:
    """The library entry a material's values were copied from (provenance only).

    Parameters
    ----------
    library : {"builtin", "user"}
        Which library holds the entry.
    entry : str
        Entry name in that library.
    """

    library: Literal["builtin", "user"]
    entry: str

    def to_json(self) -> dict[str, str]:
        """Return the JSON form."""
        return {"library": self.library, "entry": self.entry}

    @classmethod
    def from_json(cls, obj: Any) -> MaterialSource | None:
        """Build from JSON; anything that is not a valid record (e.g. a text note) is None."""
        if (
            isinstance(obj, dict)
            and obj.get("library") in ("builtin", "user")
            and isinstance(obj.get("entry"), str)
        ):
            return cls(obj["library"], obj["entry"])
        return None


PHYSICAL_PROPERTIES = ("k", "k2", "rho", "cp", "phase_change")


@dataclass
class Material:
    """Thermal properties of a solid.

    Parameters
    ----------
    name : str
        Material name.
    k : Function or float
        Thermal conductivity [W/(m K)]; constant or a table against temperature. For an
        orthotropic material this is the conductivity along the material axis.
    rho : Function or float
        Density [kg/m^3].
    cp : Function or float
        Specific heat [J/(kg K)].
    k2 : Function or float, optional, keyword-only
        If set, the material is orthotropic and ``k2`` is the conductivity across the
        material axis [W/(m K)].
    phase_change : PhaseChange, optional, keyword-only
        Melting range and latent heat.
    source : MaterialSource, optional, keyword-only
        Library entry the values were copied from; provenance only, never physics.
    """

    name: str
    k: Function
    rho: Function
    cp: Function
    k2: Function | None = field(default=None, kw_only=True)
    phase_change: PhaseChange | None = field(default=None, kw_only=True)
    source: MaterialSource | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ModelError("material name must be a non-empty string")
        self.k = as_function(self.k)
        self.rho = as_function(self.rho)
        self.cp = as_function(self.cp)
        if self.k2 is not None:
            self.k2 = as_function(self.k2)

    @property
    def orthotropic(self) -> bool:
        """True when a second principal conductivity is given."""
        return self.k2 is not None

    @property
    def depends_on_T(self) -> bool:
        """True when any property depends on temperature."""
        props = [self.k, self.rho, self.cp] + ([self.k2] if self.k2 is not None else [])
        return any(p.depends_on_T for p in props)

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form of the material."""
        out: dict[str, Any] = {
            "name": self.name,
            "k": function_to_json(self.k),
            "rho": function_to_json(self.rho),
            "cp": function_to_json(self.cp),
        }
        if self.k2 is not None:
            out["k2"] = function_to_json(self.k2)
        if self.phase_change is not None:
            pc = self.phase_change
            out["phase_change"] = {
                "T_sol": pc.T_sol,
                "T_liq": pc.T_liq,
                "latent_heat": pc.latent_heat,
            }
        if self.source is not None:
            out["source"] = self.source.to_json()
        return out

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> Material:
        """Build a material from its JSON form (bare numbers are constants)."""
        try:
            pc = obj.get("phase_change")
            return cls(
                name=obj["name"],
                k=function_from_json(obj["k"]),
                rho=function_from_json(obj["rho"]),
                cp=function_from_json(obj["cp"]),
                k2=function_from_json(obj["k2"]) if obj.get("k2") is not None else None,
                phase_change=PhaseChange(**pc) if pc is not None else None,
                # the built-in data files carry a text "source" note, which is not provenance
                source=MaterialSource.from_json(obj.get("source")),
            )
        except (KeyError, TypeError) as exc:
            raise ModelError(f"invalid material definition: {exc}") from None


def physical_properties(material: Material) -> dict[str, Any]:
    """The physical properties of a material as JSON forms (name and source left out).

    Returns
    -------
    dict
        Keys ``k``, ``k2``, ``rho``, ``cp`` and ``phase_change`` (``None`` when absent).
    """
    data = material.to_json()
    return {key: data.get(key) for key in PHYSICAL_PROPERTIES}


def differing_properties(a: Material, b: Material) -> list[str]:
    """Names of the physical properties in which two materials differ (empty if none)."""
    pa, pb = physical_properties(a), physical_properties(b)
    return [key for key in PHYSICAL_PROPERTIES if pa[key] != pb[key]]


def same_physics(a: Material, b: Material) -> bool:
    """True when ``k``, ``k2``, ``rho``, ``cp`` and ``phase_change`` agree (not name, source)."""
    return not differing_properties(a, b)


@dataclass
class Fluid:
    """Tabulated properties of a fluid against temperature.

    Parameters
    ----------
    name : str
        Fluid name.
    ideal_gas : bool
        True for an ideal gas, whose expansion coefficient is ``beta = 1/T``.
    T : list of float
        Temperatures [K], ascending.
    rho : list of float
        Density [kg/m^3] at ``T``.
    cp : list of float
        Specific heat [J/(kg K)] at ``T``.
    mu : list of float
        Dynamic viscosity [Pa s] at ``T``.
    k : list of float
        Thermal conductivity [W/(m K)] at ``T``.
    beta : list of float, optional
        Volumetric expansion coefficient [1/K] at ``T``; liquids only.
    """

    name: str
    ideal_gas: bool
    T: list[float]
    rho: list[float]
    cp: list[float]
    mu: list[float]
    k: list[float]
    beta: list[float] | None = None
    _clamp_warned: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ModelError("fluid name must be a non-empty string")
        columns = {"T": self.T, "rho": self.rho, "cp": self.cp, "mu": self.mu, "k": self.k}
        if self.beta is not None:
            columns["beta"] = self.beta
        n = len(self.T)
        if n == 0:
            raise ModelError(f"fluid {self.name!r}: property table is empty")
        for key, values in columns.items():
            if len(values) != n:
                raise ModelError(f"fluid {self.name!r}: column {key!r} has the wrong length")
            arr = np.asarray(values, dtype=float)
            if not np.all(np.isfinite(arr)):
                raise ModelError(f"fluid {self.name!r}: column {key!r} is not finite")
            if key != "beta" and np.any(arr <= 0.0):
                raise ModelError(f"fluid {self.name!r}: column {key!r} must be positive")
        if np.any(np.diff(np.asarray(self.T, dtype=float)) <= 0.0):
            raise ModelError(f"fluid {self.name!r}: temperatures must be ascending")
        if not self.ideal_gas and self.beta is None:
            raise ModelError(f"fluid {self.name!r}: a liquid needs a beta column")

    def props(self, T: Any) -> FluidProps:
        """Properties at temperature T [K] (linear interpolation, clamped at the table ends)."""
        from ..convection.fluid_props import fluid_props  # imported here to avoid an import cycle

        return fluid_props(self, T)

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form of the fluid."""
        return {
            "name": self.name,
            "ideal_gas": self.ideal_gas,
            "T": list(self.T),
            "rho": list(self.rho),
            "cp": list(self.cp),
            "mu": list(self.mu),
            "k": list(self.k),
            "beta": None if self.beta is None else list(self.beta),
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> Fluid:
        """Build a fluid from its JSON form."""
        try:
            return cls(
                name=obj["name"],
                ideal_gas=bool(obj["ideal_gas"]),
                T=[float(v) for v in obj["T"]],
                rho=[float(v) for v in obj["rho"]],
                cp=[float(v) for v in obj["cp"]],
                mu=[float(v) for v in obj["mu"]],
                k=[float(v) for v in obj["k"]],
                beta=None if obj.get("beta") is None else [float(v) for v in obj["beta"]],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError(f"invalid fluid definition: {exc}") from None
