"""Public scripting facade (Data §11). Everything the GUI does is available from here."""

from __future__ import annotations

import json
from pathlib import Path

from .core.errors import ModelError
from .model.model import Model
from .model.serialize import from_json, to_json


def save(model: Model, path: str | Path) -> None:
    """Write a model to a ``.tfea`` file (JSON, sorted keys, 2-space indent, SI units).

    Parameters
    ----------
    model : Model
    path : str or Path
        File to write.
    """
    text = json.dumps(to_json(model), sort_keys=True, indent=2, allow_nan=False)
    Path(path).write_text(text + "\n", encoding="utf-8")


def load(path: str | Path) -> Model:
    """Read a model from a ``.tfea`` file, migrating older schema versions.

    Parameters
    ----------
    path : str or Path
        File to read.

    Raises
    ------
    ModelError
        If the file cannot be read or understood.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelError(f"cannot read model file {path}: {exc}") from None
    return from_json(data)
