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


# ------------------------------------------------------------ polymorphic class families
#
# A *family* is a base class whose subclasses are written to JSON with a ``"type"`` tag
# (geometry operations, boundary conditions, ...). The serialiser, the solver and the GUI
# find the concrete class through these tables, so adding a class never means editing them.

_FAMILIES: dict[str, type] = {}
_CLASSES: dict[str, dict[str, type]] = {}


def register_family(family: str, base: type) -> None:
    """Declare a family of tagged classes with the given base class."""
    _FAMILIES[family] = base
    _CLASSES.setdefault(family, {})


def families() -> dict[str, type]:
    """Return the registered families: name -> base class."""
    return dict(_FAMILIES)


def register_class(family: str, tag: str, cls: type) -> None:
    """Register ``cls`` under ``tag`` in a family.

    Raises
    ------
    ModelError
        If the family is unknown, the class is not a subclass of its base, or the tag is
        already used by a different class.
    """
    if family not in _FAMILIES:
        raise ModelError(f"unknown class family {family!r}")
    if not issubclass(cls, _FAMILIES[family]):
        raise ModelError(f"{cls.__name__} is not a {_FAMILIES[family].__name__}")
    existing = _CLASSES[family].get(tag)
    if existing is not None and existing is not cls:
        raise ModelError(f"{family} tag {tag!r} is already used by {existing.__name__}")
    _CLASSES[family][tag] = cls


def class_by_tag(family: str, tag: str) -> type:
    """Return the class registered under ``tag`` in a family."""
    try:
        return _CLASSES[family][tag]
    except KeyError:
        raise ModelError(f"unknown {family} type {tag!r}") from None


def tag_of(family: str, cls: type) -> str:
    """Return the tag a class is registered under in a family."""
    for tag, registered in _CLASSES.get(family, {}).items():
        if registered is cls:
            return tag
    raise ModelError(f"{cls.__name__} is not registered in family {family!r}")


def tags(family: str) -> list[str]:
    """Return the tags registered in a family, in registration order."""
    return list(_CLASSES.get(family, {}))


# ------------------------------------------------------------------ boundary conditions

BC_FAMILY = "bc"


@dataclass
class BcInfo:
    """Registry record of a boundary-condition class.

    Attributes
    ----------
    tag : str
        JSON ``"type"`` tag.
    cls : type
        The boundary-condition dataclass.
    term_factory : callable or None
        Builds the solver terms of one instance; ``None`` if it contributes nothing or
        the physics is not implemented yet.
    form : object or None
        GUI form metadata (``FormSpec``), or ``None``.
    """

    tag: str
    cls: type
    term_factory: Callable | None = None
    form: object | None = None


_BCS: dict[str, BcInfo] = {}


def register_bc(
    tag: str, cls: type, term_factory: Callable | None = None, form: object | None = None
) -> None:
    """Register a boundary-condition class with its JSON tag, term factory and form."""
    register_class(BC_FAMILY, tag, cls)
    _BCS[tag] = BcInfo(tag, cls, term_factory, form)


def bc_info(key: str | type) -> BcInfo:
    """Return the registry record of a boundary condition, by tag or by class."""
    tag = key if isinstance(key, str) else tag_of(BC_FAMILY, key)
    try:
        return _BCS[tag]
    except KeyError:
        raise ModelError(f"unknown boundary-condition type {tag!r}") from None


def set_bc_term_factory(key: str | type, term_factory: Callable) -> None:
    """Attach the solver term factory to an already registered boundary condition."""
    bc_info(key).term_factory = term_factory


def bc_tags() -> list[str]:
    """Return the tags of all registered boundary conditions, in registration order."""
    return list(_BCS)
