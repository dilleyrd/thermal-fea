"""Form specification of the mesh settings (Plan M8.7). No Qt.

It is registered with :func:`thermalfea.core.forms.register_form` when
:mod:`thermalfea.model.model` is imported. Every :class:`MeshSettings` field except
``refinements`` is listed here; a list of :class:`Refinement` objects has no editor kind, so
the mesh panel (:class:`thermalfea.gui.property_panels.mesh.MeshPanel`) edits it as a table.

Dictionaries (``curve_sizes``, ``point_sizes``, ``curve_divisions``) are edited as
``selection=value`` lists and their values are stored unscaled (SI for sizes in metres).
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from .settings import MeshSettings

MESH_FORM = FormSpec(
    "Mesh",
    [
        FieldSpec(
            "global_size", "Global element size", "float", quantity="length", minimum=0.0,
            tooltip="Target element size away from point, curve and refinement controls.",
        ),  # fmt: skip
        FieldSpec(
            "order", "Element order", "choice", choices=(1, 2),
            tooltip="1 for linear, 2 for quadratic elements.",
        ),  # fmt: skip
        FieldSpec(
            "element_shape", "Element shape", "choice", choices=("tri", "quad"),
            tooltip="Triangles, or a quad-dominant mesh.",
        ),  # fmt: skip
        FieldSpec(
            "algorithm", "Algorithm", "choice", choices=("delaunay", "frontal", "frontal_quad"),
            tooltip="Free-meshing algorithm.",
        ),  # fmt: skip
        FieldSpec(
            "curve_sizes", "Curve sizes", "dict", quantity="length",
            tooltip="Curve selection and element size, as 'name=size, name=size'.",
        ),  # fmt: skip
        FieldSpec(
            "point_sizes", "Point sizes", "dict", quantity="length",
            tooltip="Point selection and element size, as 'name=size, name=size'.",
        ),  # fmt: skip
        FieldSpec(
            "curve_divisions", "Curve divisions", "dict",
            tooltip="Curve selection and number of elements, as 'name=count, name=count'.",
        ),  # fmt: skip
        FieldSpec(
            "structured_surfaces", "Structured surfaces", "selection_list", selection_dims=(2,),
            tooltip="Surface selections meshed transfinite (3 or 4 sides).",
        ),  # fmt: skip
        FieldSpec(
            "smoothing_passes", "Smoothing passes", "int", minimum=0.0,
            tooltip="Number of mesh smoothing passes.",
        ),  # fmt: skip
    ],
    category="settings",
    description="Element size, order, shape and algorithm of the mesh.",
)

register_form(MeshSettings, MESH_FORM)
