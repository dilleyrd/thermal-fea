"""Model-file migrations (Data §13, Plan §7 rule 10).

``MIGRATIONS[n]`` upgrades a model dict from schema version ``n`` to ``n + 1``. Loading an
older file applies them in sequence. The table starts empty: version 1 is the first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..core.errors import ModelError

log = logging.getLogger(__name__)

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(data: dict[str, Any], target: int) -> dict[str, Any]:
    """Upgrade a model dict to schema version ``target``.

    Parameters
    ----------
    data : dict
        Model in JSON form, with a ``schema_version`` entry.
    target : int
        The schema version this program writes.

    Returns
    -------
    dict
        The upgraded dict (the input is returned unchanged when already current).

    Raises
    ------
    ModelError
        If the version is missing, newer than ``target``, or a migration step is missing.
    """
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ModelError("model file has no valid schema_version")
    if version > target:
        raise ModelError(
            f"model file has schema version {version}, but this program reads up to "
            f"version {target}; use a newer version of ThermalFEA"
        )
    while version < target:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ModelError(f"no migration from schema version {version} to {version + 1}")
        log.info("migrating model from schema version %d to %d", version, version + 1)
        data = step(data)
        version += 1
        data["schema_version"] = version
    return data
