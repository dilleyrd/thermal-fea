"""Degree-of-freedom numbering (Data §13).

Unknowns are named fields with a number of components per node, plus named groups of
extra DOFs that belong to no mesh node (for example the fluid nodes of a stream). Nothing
else in the program may assume that a DOF index equals a node index; always ask the map.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError


@dataclass(frozen=True)
class _Field:
    offset: int
    n_nodes: int
    components: int


@dataclass(frozen=True)
class _Extra:
    offset: int
    count: int


class DofMap:
    """Maps (field, node, component) and (group, index) to global DOF numbers.

    DOFs are numbered in the order fields and groups are added. Within a field the DOF of
    component ``c`` at node ``i`` is ``offset + i * components + c``.
    """

    def __init__(self) -> None:
        self._fields: dict[str, _Field] = {}
        self._extras: dict[str, _Extra] = {}
        self._n_dofs = 0

    @property
    def n_dofs(self) -> int:
        """Total number of DOFs."""
        return self._n_dofs

    @property
    def fields(self) -> list[str]:
        """Names of the nodal fields, in the order they were added."""
        return list(self._fields)

    @property
    def extras(self) -> list[str]:
        """Names of the extra DOF groups, in the order they were added."""
        return list(self._extras)

    def _check_new(self, name: str) -> None:
        if name in self._fields or name in self._extras:
            raise ModelError(f"DOF field or group {name!r} already exists")

    def add_field(self, name: str, n_nodes: int, components: int = 1) -> None:
        """Add a nodal field.

        Parameters
        ----------
        name : str
            Field name, e.g. ``"T"``.
        n_nodes : int
            Number of mesh nodes carrying the field.
        components : int
            Number of components per node (1 for temperature).
        """
        self._check_new(name)
        if n_nodes < 0 or components < 1:
            raise ModelError(f"field {name!r}: invalid size ({n_nodes} nodes, {components} comp.)")
        self._fields[name] = _Field(self._n_dofs, int(n_nodes), int(components))
        self._n_dofs += int(n_nodes) * int(components)

    def add_extra(self, group: str, count: int) -> None:
        """Add a group of DOFs that are not attached to mesh nodes.

        Parameters
        ----------
        group : str
            Group name, e.g. the name of a stream.
        count : int
            Number of DOFs in the group.
        """
        self._check_new(group)
        if count < 0:
            raise ModelError(f"extra DOF group {group!r}: negative count")
        self._extras[group] = _Extra(self._n_dofs, int(count))
        self._n_dofs += int(count)

    def components(self, field: str) -> int:
        """Number of components per node of a field."""
        return self._field(field).components

    def n_nodes(self, field: str) -> int:
        """Number of nodes carrying a field."""
        return self._field(field).n_nodes

    def _field(self, name: str) -> _Field:
        try:
            return self._fields[name]
        except KeyError:
            raise ModelError(f"unknown DOF field {name!r}") from None

    def node_dofs(self, field: str, nodes: ndarray, component: int = 0) -> ndarray:
        """Global DOF numbers of one component of a field at the given nodes.

        Parameters
        ----------
        field : str
            Field name.
        nodes : ndarray of int, any shape
            Node indices.
        component : int
            Component index, ``0 <= component < components``.

        Returns
        -------
        ndarray of int64, same shape as ``nodes``
        """
        f = self._field(field)
        if not 0 <= component < f.components:
            raise ModelError(f"field {field!r} has no component {component}")
        nodes = np.asarray(nodes, dtype=np.int64)
        if nodes.size and (nodes.min() < 0 or nodes.max() >= f.n_nodes):
            raise ModelError(f"field {field!r}: node index out of range")
        return f.offset + nodes * f.components + component

    def field_dofs(self, field: str, component: int = 0) -> ndarray:
        """Global DOF numbers of one component of a field at every node, in node order."""
        return self.node_dofs(field, np.arange(self._field(field).n_nodes), component)

    def extra_dofs(self, group: str) -> ndarray:
        """Global DOF numbers of an extra group.

        Parameters
        ----------
        group : str
            Group name.

        Returns
        -------
        ndarray of int64, shape (count,)
        """
        try:
            e = self._extras[group]
        except KeyError:
            raise ModelError(f"unknown extra DOF group {group!r}") from None
        return e.offset + np.arange(e.count, dtype=np.int64)
