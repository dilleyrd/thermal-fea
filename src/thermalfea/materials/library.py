"""Built-in and user material libraries (Data §6).

The built-in solids and fluids ship as JSON files beside this module. A user library with
the same structure is stored in ``%APPDATA%/ThermalFEA/materials.json``.
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from ..core.errors import ModelError
from .material import Fluid, Material

log = logging.getLogger(__name__)

_DATA_PACKAGE = "thermalfea.materials"


def _read_builtin(filename: str) -> list[dict[str, Any]]:
    path = resources.files(_DATA_PACKAGE).joinpath("data", filename)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@cache
def _builtin_solids() -> dict[str, Material]:
    return {m.name: m for m in map(Material.from_json, _read_builtin("solids.json"))}


@cache
def _builtin_fluids() -> dict[str, Fluid]:
    return {f.name: f for f in map(Fluid.from_json, _read_builtin("fluids.json"))}


def _fresh(item: Material | Fluid) -> Any:
    """Return an independent copy, so callers can edit it without changing the library."""
    return type(item).from_json(item.to_json())


def solids() -> dict[str, Material]:
    """Return the built-in solids, keyed by name (independent copies)."""
    return {name: _fresh(m) for name, m in _builtin_solids().items()}


def fluids() -> dict[str, Fluid]:
    """Return the built-in fluids, keyed by name (independent copies)."""
    return {name: _fresh(f) for name, f in _builtin_fluids().items()}


def _lookup(table: dict[str, Any], name: str, kind: str) -> Any:
    if name in table:
        return _fresh(table[name])
    folded = {key.casefold(): key for key in table}
    key = folded.get(name.casefold())
    if key is None:
        raise ModelError(f"no {kind} named {name!r} in the library ({', '.join(sorted(table))})")
    return _fresh(table[key])


def solid(name: str) -> Material:
    """Return a copy of a built-in solid.

    Parameters
    ----------
    name : str
        Library name, e.g. ``"Copper (pure)"`` (case-insensitive).

    Raises
    ------
    ModelError
        If there is no such solid.
    """
    return _lookup(_builtin_solids(), name, "solid")


def fluid(name: str) -> Fluid:
    """Return a copy of a built-in fluid.

    Parameters
    ----------
    name : str
        Library name, ``"Air"`` or ``"Water"`` (case-insensitive).

    Raises
    ------
    ModelError
        If there is no such fluid.
    """
    return _lookup(_builtin_fluids(), name, "fluid")


# ------------------------------------------------------------------------ user library


def user_library_path() -> Path:
    """Return the path of the user material library file."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "ThermalFEA" / "materials.json"


def load_user_library(path: Path | None = None) -> tuple[dict[str, Material], dict[str, Fluid]]:
    """Read the user library.

    Parameters
    ----------
    path : Path, optional
        File to read; defaults to :func:`user_library_path`.

    Returns
    -------
    solids : dict of str to Material
    fluids : dict of str to Fluid
        Both empty when the file does not exist.

    Raises
    ------
    ModelError
        If the file exists but cannot be understood.
    """
    path = path or user_library_path()
    if not path.exists():
        return {}, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        solid_items = [Material.from_json(obj) for obj in data.get("solids", [])]
        fluid_items = [Fluid.from_json(obj) for obj in data.get("fluids", [])]
    except (OSError, ValueError, AttributeError) as exc:
        raise ModelError(f"cannot read the user material library {path}: {exc}") from None
    return {m.name: m for m in solid_items}, {f.name: f for f in fluid_items}


def save_user_library(
    solids: dict[str, Material], fluids: dict[str, Fluid], path: Path | None = None
) -> Path:
    """Write the user library and return the path written.

    Parameters
    ----------
    solids : dict of str to Material
    fluids : dict of str to Fluid
    path : Path, optional
        File to write; defaults to :func:`user_library_path`.
    """
    path = path or user_library_path()
    data = {
        "solids": [m.to_json() for m in solids.values()],
        "fluids": [f.to_json() for f in fluids.values()],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("wrote user material library %s", path)
    return path
