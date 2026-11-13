"""Conversion of a :class:`Model` to and from plain JSON data (Data §3).

The conversion is driven by the dataclass fields and their type hints, so a new model
class needs no code here. Classes belonging to a registered family (geometry operations,
boundary conditions) are written with a ``"type"`` tag and found again through the
registry (Plan §7 rule 6). Functions use the forms of Data §1.
"""

from __future__ import annotations

import dataclasses
import types
from functools import cache
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from ..core import registry
from ..core.errors import ModelError
from ..core.functions import Function, function_from_json, function_to_json
from .migrations import migrate
from .model import SCHEMA_VERSION, Model

TYPE_KEY = "type"
_NONE = type(None)


@cache
def _fields(cls: type) -> tuple[tuple[str, Any], ...]:
    """Init fields of a dataclass with their resolved type hints."""
    hints = get_type_hints(cls)
    return tuple((f.name, hints[f.name]) for f in dataclasses.fields(cls) if f.init)


def _family_of(cls: type) -> str | None:
    for family, base in registry.families().items():
        if isinstance(cls, type) and issubclass(cls, base):
            return family
    return None


# ------------------------------------------------------------------------------ encode


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        cls = type(value)
        if isinstance(value, Function):
            return function_to_json(value)
        out = {name: _encode(getattr(value, name)) for name, _ in _fields(cls)}
        family = _family_of(cls)
        if family is not None:
            if TYPE_KEY in out:
                raise ModelError(f"{cls.__name__} may not have a field called {TYPE_KEY!r}")
            out[TYPE_KEY] = registry.tag_of(family, cls)
        return out
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ModelError("only string keys can be written to a model file")
        return {k: _encode(v) for k, v in value.items()}
    raise ModelError(f"cannot write a value of type {type(value).__name__} to a model file")


def to_json(model: Model) -> dict[str, Any]:
    """Return the model as JSON-compatible data (dicts, lists, numbers, strings).

    Parameters
    ----------
    model : Model

    Returns
    -------
    dict
        Sharing nothing with the model. Write it with sorted keys and a 2-space indent
        (:func:`thermalfea.api.save` does) to get a stable, diffable file.
    """
    return _encode(model)


# ------------------------------------------------------------------------------ decode


def _decode_dataclass(obj: Any, cls: type, where: str) -> Any:
    if not isinstance(obj, dict):
        raise ModelError(f"{where}: expected an object for {cls.__name__}, got {obj!r}")
    data = dict(obj)
    family = _family_of(cls)
    if family is not None:
        tag = data.pop(TYPE_KEY, None)
        if not isinstance(tag, str):
            raise ModelError(f"{where}: missing {TYPE_KEY!r} tag")
        cls = registry.class_by_tag(family, tag)
    fields = dict(_fields(cls))
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ModelError(f"{where}: unknown field(s) {', '.join(unknown)} for {cls.__name__}")
    kwargs = {
        name: _decode(value, fields[name], f"{where}.{name}") for name, value in data.items()
    }
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise ModelError(f"{where}: {exc}") from None


def _decode(obj: Any, hint: Any, where: str) -> Any:
    if hint is Any:
        return obj
    if hint is Function:
        return function_from_json(obj)
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        options = [a for a in get_args(hint) if a is not _NONE]
        if obj is None:
            if len(options) == len(get_args(hint)):
                raise ModelError(f"{where}: null is not allowed")
            return None
        if len(options) != 1:
            raise ModelError(f"{where}: unsupported type hint {hint!r}")
        return _decode(obj, options[0], where)
    if origin is Literal:
        if obj not in get_args(hint):
            allowed = ", ".join(map(repr, get_args(hint)))
            raise ModelError(f"{where}: {obj!r} is not one of {allowed}")
        return obj
    if origin is list:
        if not isinstance(obj, list):
            raise ModelError(f"{where}: expected a list, got {obj!r}")
        (item,) = get_args(hint)
        return [_decode(v, item, f"{where}[{i}]") for i, v in enumerate(obj)]
    if origin is tuple:
        if not isinstance(obj, (list, tuple)):
            raise ModelError(f"{where}: expected a list, got {obj!r}")
        args = get_args(hint)
        if len(args) == 2 and args[1] is Ellipsis:  # noqa: PLR2004 - (X, ...) form
            args = (args[0],) * len(obj)
        if len(args) != len(obj):
            raise ModelError(f"{where}: expected {len(args)} values, got {len(obj)}")
        return tuple(
            _decode(v, a, f"{where}[{i}]")
            for i, (v, a) in enumerate(zip(obj, args, strict=True))
        )
    if origin is dict:
        if not isinstance(obj, dict):
            raise ModelError(f"{where}: expected an object, got {obj!r}")
        _, item = get_args(hint)
        return {str(k): _decode(v, item, f"{where}.{k}") for k, v in obj.items()}
    if dataclasses.is_dataclass(hint):
        return _decode_dataclass(obj, hint, where)
    if hint is float:
        if isinstance(obj, bool) or not isinstance(obj, (int, float)):
            raise ModelError(f"{where}: expected a number, got {obj!r}")
        return float(obj)
    if hint is int:
        if isinstance(obj, bool) or not isinstance(obj, int):
            raise ModelError(f"{where}: expected an integer, got {obj!r}")
        return obj
    if hint is bool:
        if not isinstance(obj, bool):
            raise ModelError(f"{where}: expected true or false, got {obj!r}")
        return obj
    if hint is str:
        if not isinstance(obj, str):
            raise ModelError(f"{where}: expected a string, got {obj!r}")
        return obj
    raise ModelError(f"{where}: unsupported type hint {hint!r}")


def from_json(data: dict[str, Any]) -> Model:
    """Build a model from JSON data.

    The ``schema_version`` is checked first: a file newer than this program is refused,
    an older one is migrated (``model/migrations.py``).

    Parameters
    ----------
    data : dict
        Model in the form written by :func:`to_json`. It is not modified.

    Returns
    -------
    Model

    Raises
    ------
    ModelError
        If the data cannot be understood.
    """
    if not isinstance(data, dict):
        raise ModelError("model file must contain a JSON object")
    data = migrate(dict(data), SCHEMA_VERSION)
    return _decode_dataclass(data, Model, "model")
