"""Registries that let new element types be added without editing other code (Data §13).

An :class:`ElementType` record holds everything the rest of the program needs to know
about one element: its shape functions, quadrature, gmsh type code, facet type and
display subdivision. All other code obtains element data only through :func:`element`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from numpy import ndarray

from .errors import ModelError


@dataclass(frozen=True, eq=False)
class ElementType:
    """Description of one finite-element type.

    Attributes
    ----------
    name : str
        Registry key, e.g. ``"T3"``.
    dim : int
        Dimension of the element itself (2 for T3, 1 for L2).
    n_nodes : int
        Number of nodes.
    order : int
        Polynomial order of the shape functions.
    gmsh_type : int
        gmsh element type code.
    shape : callable
        ``pts (n, dim) -> N (n, n_nodes)``, reference coordinates in, dimensionless out.
    dshape : callable
        ``pts (n, dim) -> dN (n, dim, n_nodes)``, derivatives with respect to the
        reference coordinates.
    node_coords : ndarray, shape (n_nodes, dim)
        Reference coordinates of the nodes.
    quadrature : tuple of ndarray
        ``(points (n_gp, dim), weights (n_gp,))``.
    facet_type : str or None
        Name of the element type of its facets; ``None`` when the type is itself only
        used as a facet.
    facets : ndarray or None, shape (n_facets, n_nodes_per_facet)
        Local node indices of each facet, ordered so the element lies on the left of a
        line facet (outward normal by the right-hand rule in 3D).
    display_simplices : ndarray, shape (n_simplices, dim + 1)
        Local node indices that split the element into linear simplices for display.
    """

    name: str
    dim: int
    n_nodes: int
    order: int
    gmsh_type: int
    shape: Callable[[ndarray], ndarray]
    dshape: Callable[[ndarray], ndarray]
    node_coords: ndarray
    quadrature: tuple[ndarray, ndarray]
    facet_type: str | None
    facets: ndarray | None
    display_simplices: ndarray


_ELEMENTS: dict[str, ElementType] = {}
_builtin_loaded = False


def _load_builtin() -> None:
    """Import the module that registers the built-in element types (once)."""
    global _builtin_loaded
    if not _builtin_loaded:
        _builtin_loaded = True
        from . import elements  # noqa: F401  (registers on import)


def register_element(et: ElementType) -> None:
    """Add an element type to the registry, replacing any type of the same name.

    Parameters
    ----------
    et : ElementType
        The record to register.

    Raises
    ------
    ModelError
        If the record is internally inconsistent.
    """
    if et.node_coords.shape != (et.n_nodes, et.dim):
        raise ModelError(
            f"element type {et.name!r}: node_coords has shape {et.node_coords.shape}, "
            f"expected {(et.n_nodes, et.dim)}"
        )
    points, weights = et.quadrature
    if points.ndim != 2 or points.shape != (weights.shape[0], et.dim):
        raise ModelError(f"element type {et.name!r}: quadrature arrays have the wrong shape")
    _ELEMENTS[et.name] = et


def element(name: str) -> ElementType:
    """Return the registered element type called ``name``.

    Parameters
    ----------
    name : str
        Registry key, e.g. ``"Q8"``.

    Raises
    ------
    ModelError
        If no such element type is registered.
    """
    _load_builtin()
    try:
        return _ELEMENTS[name]
    except KeyError:
        raise ModelError(f"unknown element type {name!r}") from None


def element_names() -> list[str]:
    """Return the names of all registered element types, sorted."""
    _load_builtin()
    return sorted(_ELEMENTS)


def element_by_gmsh_type(gmsh_type: int) -> ElementType:
    """Return the registered element type with the given gmsh type code.

    Raises
    ------
    ModelError
        If no registered element type has that code.
    """
    _load_builtin()
    for et in _ELEMENTS.values():
        if et.gmsh_type == gmsh_type:
            return et
    raise ModelError(f"no element type registered for gmsh type {gmsh_type}")
