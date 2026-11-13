"""Public scripting facade (Data §11). Everything the GUI does is available from here."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from .core.errors import ModelError
from .geometry.builder import BuiltGeometry
from .model.model import Model
from .model.selections import Fingerprint, Selection
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


# -------------------------------------------------------------------------- selections


def _select(
    model: Model,
    built: BuiltGeometry,
    dim: int,
    name: str,
    where: Callable[[Fingerprint], bool] | None,
    tags: Sequence[int] | None,
) -> Selection:
    entities = built.entities(dim)
    if (where is None) == (tags is None):
        raise ModelError(f"selection {name!r}: give exactly one of where= and tags=")
    if tags is not None:
        chosen = [int(t) for t in tags]
        missing = [t for t in chosen if t not in entities]
        if missing:
            raise ModelError(f"selection {name!r}: no entity with tag(s) {missing}")
    else:
        chosen = [tag for tag, fp in entities.items() if where(fp)]
    if not chosen:
        raise ModelError(f"selection {name!r} matches nothing")
    selection = Selection(name, dim, chosen, [entities[t] for t in chosen])
    model.selections[name] = selection
    return selection


def select_points(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of geometry points.

    Parameters
    ----------
    model : Model
        The selection is stored in ``model.selections[name]``.
    built : BuiltGeometry
        The current build of the model.
    name : str
        Selection name.
    where : callable, optional
        Predicate on each point's :class:`Fingerprint` (``center`` in metres).
    tags : sequence of int, optional
        Explicit tags. Give exactly one of ``where`` and ``tags``.

    Returns
    -------
    Selection
    """
    return _select(model, built, 0, name, where, tags)


def select_curves(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of curves; see :func:`select_points`."""
    return _select(model, built, 1, name, where, tags)


def select_surfaces(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of surfaces; see :func:`select_points`."""
    return _select(model, built, 2, name, where, tags)
