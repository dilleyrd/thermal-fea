"""Built-in and user material libraries (Data §6).

The built-in solids and fluids ship as JSON files beside this module. A user library with
the same structure is stored in ``%APPDATA%/ThermalFEA/materials.json``. :func:`fluid`
looks in the built-in fluids first and then in the user library (D12.5); a user fluid
whose name is a built-in name is never used and is reported once.
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
from .material import Fluid, Material, differing_properties

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


def _find(table: dict[str, Any], name: str) -> str | None:
    """Return the key of ``name`` in ``table``, exact first, then case-insensitive."""
    if name in table:
        return name
    folded = {key.casefold(): key for key in table}
    return folded.get(name.casefold())


def _lookup(table: dict[str, Any], name: str, kind: str) -> Any:
    key = _find(table, name)
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
    """Return a copy of a built-in fluid, or of a fluid in the user library.

    The built-in fluids are searched first (exact name, then case-insensitive). If none
    matches, the user library at :func:`user_library_path` is searched the same way.

    Parameters
    ----------
    name : str
        Library name, e.g. ``"Air"`` or ``"Water"`` (case-insensitive).

    Raises
    ------
    ModelError
        If there is no such fluid in either library, or the user library exists but
        cannot be read and the name is not a built-in one.
    """
    builtin = _builtin_fluids()
    key = _find(builtin, name)
    if key is not None:
        return _fresh(builtin[key])
    user = _user_fluids()
    key = _find(user, name)
    if key is not None:
        return _fresh(user[key])
    user_names = ", ".join(sorted(user)) or "none"
    raise ModelError(
        f"no fluid named {name!r} in the library "
        f"({', '.join(sorted(builtin))}; user library: {user_names})"
    )


def fluid_names() -> list[str]:
    """Return the fluid names offered in lists: built-in names, then user names.

    A user fluid whose name is a built-in name is left out, as :func:`fluid` never uses it.
    A user library that cannot be read is logged and left out.
    """
    names = list(_builtin_fluids())
    try:
        user = _user_fluids()
    except ModelError as exc:
        log.warning("%s", exc)
        return names
    folded = {name.casefold() for name in names}
    return names + [name for name in user if name.casefold() not in folded]


# ------------------------------------------------------------------------ user library


def user_library_path() -> Path:
    """Return the path of the user material library file."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "ThermalFEA" / "materials.json"


# (path, mtime_ns) -> the user fluids read from that file version; one entry at a time.
_USER_FLUIDS_CACHE: dict[tuple[str, int], dict[str, Fluid]] = {}


def _user_fluids() -> dict[str, Fluid]:
    """Return the user fluids, re-reading the file only when its path or mtime changes.

    A missing file gives ``{}``. A user fluid whose name is a built-in name (case-insensitive)
    is kept here but never used by :func:`fluid`; one warning per such name is logged on
    each read.

    Raises
    ------
    ModelError
        If the file exists but cannot be read.
    """
    path = user_library_path()
    try:
        stamp = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    key = (str(path), stamp)
    if key not in _USER_FLUIDS_CACHE:
        _, fluids = load_user_library(path)
        builtin = {name.casefold() for name in _builtin_fluids()}
        for name in fluids:
            if name.casefold() in builtin:
                log.warning(
                    "user fluid '%s' has the name of a built-in fluid and is not used; "
                    "rename it in %s",
                    name,
                    path,
                )
        _USER_FLUIDS_CACHE.clear()
        _USER_FLUIDS_CACHE[key] = fluids
    return _USER_FLUIDS_CACHE[key]


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


def source_entry(material: Material, path: Path | None = None) -> Material | None:
    """The library entry a material's ``source`` names, or ``None`` (no source, not found).

    An unreadable user library counts as not found. The entry is the library's own object
    (not a copy); do not modify it.
    """
    src = material.source
    if src is None:
        return None
    if src.library == "builtin":
        return _builtin_solids().get(src.entry)
    try:
        user, _ = load_user_library(path)
    except ModelError:
        return None
    return user.get(src.entry)


def source_state(
    material: Material, path: Path | None = None
) -> tuple[str, Material | None, list[str]]:
    """Where a material stands against the library entry it was copied from.

    Returns
    -------
    state : {"custom", "library", "edited", "missing"}
        No source; values equal the entry's; values differ from the entry's; or the entry
        is not in that library.
    entry : Material or None
        The library entry (``None`` for "custom" and "missing").
    differing : list of str
        Names of the physical properties that differ (non-empty only for "edited").
    """
    if material.source is None:
        return "custom", None, []
    entry = source_entry(material, path)
    if entry is None:
        return "missing", None, []
    diff = differing_properties(material, entry)
    return ("edited" if diff else "library"), entry, diff


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
