"""Part / boundary / edge / point vocabulary (GUI identity plan, section 3).

The user-facing names of entities depend on the dimension of the model's domain: in a
2-D domain a *part* is a surface and a *boundary* is a curve; in a 3-D domain a part is a
volume, a boundary a surface and an *edge* a curve. Geometry dialogs keep the geometric
words "surface" and "curve"; only the roles of selections use this vocabulary.

The domain dimension lives in :data:`_DOMAIN_DIM` and nowhere else.
"""

from __future__ import annotations

from ..core.errors import ModelError
from .model import Model

#: Dimension of the domain of each analysis type.
_DOMAIN_DIM: dict[str, int] = {"planar": 2, "axisymmetric": 2}

#: Roles of an entity, from the domain dimension down to the points.
ROLES: tuple[str, ...] = ("part", "boundary", "edge", "point")

_PLURAL = {"part": "parts", "boundary": "boundaries", "edge": "edges", "point": "points"}


def domain_dim(model: Model) -> int:
    """Dimension of the model's domain, known before any build.

    Parameters
    ----------
    model : Model
        The model; only its ``analysis`` is read.

    Returns
    -------
    int
        The domain dimension.

    Raises
    ------
    ModelError
        If the analysis type is unknown.
    """
    try:
        return _DOMAIN_DIM[model.analysis]
    except KeyError:
        raise ModelError(f"unknown analysis type {model.analysis!r}") from None


def _dim(model_or_dim: Model | int) -> int:
    return model_or_dim if isinstance(model_or_dim, int) else domain_dim(model_or_dim)


def role_dim(role: str, model_or_dim: Model | int) -> int | None:
    """Dimension of the entities that play ``role``.

    Parameters
    ----------
    role : {"part", "boundary", "edge", "point"}
        The role.
    model_or_dim : Model or int
        The model, or the dimension of the domain.

    Returns
    -------
    int or None
        ``part``: the domain dimension; ``boundary``: one less; ``edge``: 1, only when the
        boundary is itself more than a curve, else ``None``; ``point``: 0.

    Raises
    ------
    ModelError
        If ``role`` is not in :data:`ROLES`.
    """
    d = _dim(model_or_dim)
    if role == "part":
        return d
    if role == "boundary":
        return d - 1
    if role == "edge":
        return 1 if d - 1 > 1 else None
    if role == "point":
        return 0
    raise ModelError(f"unknown role {role!r}; expected one of {ROLES}")


def role_of(dim: int, model_or_dim: Model | int) -> str:
    """Role of the entities of dimension ``dim`` (the inverse of :func:`role_dim`).

    The higher-level role wins: in a 2-D domain dimension 1 is a ``boundary``, not an
    ``edge``.

    Parameters
    ----------
    dim : int
        Entity dimension.
    model_or_dim : Model or int
        The model, or the dimension of the domain.

    Raises
    ------
    ModelError
        If no role has this dimension.
    """
    for role in ROLES:
        if role_dim(role, model_or_dim) == dim:
            return role
    raise ModelError(f"no role for entities of dimension {dim} in a {_dim(model_or_dim)}-D domain")


def entity_word(dim: int, model_or_dim: Model | int, plural: bool = False) -> str:
    """The word for entities of dimension ``dim``: "part", "boundary", "edge" or "point".

    Parameters
    ----------
    dim : int
        Entity dimension.
    model_or_dim : Model or int
        The model, or the dimension of the domain.
    plural : bool
        Return the plural ("parts", "boundaries", "edges", "points").
    """
    word = role_of(dim, model_or_dim)
    return _PLURAL[word] if plural else word
