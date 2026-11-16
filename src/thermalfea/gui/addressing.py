"""Stable addresses of the objects inside a model (Plan M8.4).

``Document.edit`` mutates a *copy* of the model and then replaces ``document.model``, so
the GUI cannot hold a reference to an object it wants to edit. It holds an *address*
instead and looks the object up again in whichever model it is given.

An address is a tuple. Its first item is the name of a ``Model`` attribute; a second item,
if present, is a ``str`` key (for dicts such as ``materials``) or an ``int`` index (for
lists such as ``bcs``, ``streams``, ``enclosures``, ``regions``, ``contacts``)::

    ("bcs", 2)                 the third boundary condition
    ("materials", "Steel")     the material named Steel
    ("mesh_settings",)         the mesh settings object
    ("solution",)              the solution settings object
"""

from __future__ import annotations

from typing import Any

from thermalfea.core.errors import ModelError
from thermalfea.model.model import Model

Address = tuple


def resolve(model: Model, address: Address) -> Any:
    """Return the object at ``address`` in ``model``.

    Raises
    ------
    ModelError
        If the address does not exist in the model.
    """
    if not address or not isinstance(address[0], str) or not hasattr(model, address[0]):
        raise ModelError(f"bad object address {address!r}")
    obj = getattr(model, address[0])
    if len(address) == 1:
        if obj is None:
            raise ModelError(f"nothing at {address!r}")
        return obj
    key = address[1]
    try:
        return obj[key]
    except (KeyError, IndexError, TypeError):
        raise ModelError(f"nothing at {address!r}") from None


def exists(model: Model, address: Address) -> bool:
    """True when ``address`` resolves in ``model``."""
    try:
        resolve(model, address)
    except ModelError:
        return False
    return True
