"""The complete, serialisable description of an analysis (Data §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.errors import ModelError
from ..core.functions import Constant, Function
from ..core.units import UnitSettings
from ..materials.material import Material
from .bcs import BoundaryCondition, Contact, Enclosure, FlowNetwork, Stream, coerce_functions
from .geometry_ops import GeometryOp
from .selections import Selection
from .settings import MeshSettings, SolutionSettings

SCHEMA_VERSION = 1

#: Element size [m] of a new model, until the user sets one (OPEN_QUESTIONS Q4).
DEFAULT_GLOBAL_SIZE = 0.01
#: Uniform initial temperature [K] of a new model, 20 degC (OPEN_QUESTIONS Q4).
DEFAULT_INITIAL_TEMPERATURE = 293.15


@dataclass
class RegionAssignment:
    """Assigns a material to the surfaces of a selection.

    Parameters
    ----------
    selection : str
        Name of a surface selection.
    material : str
        Name of a material in the model.
    thickness : float
        Thickness [m]; planar models only.
    material_angle : float
        Angle of the material axis [rad], counter-clockwise from x; orthotropic only.
    """

    selection: str
    material: str
    thickness: float = 1.0
    material_angle: float = 0.0


@dataclass
class InitialCondition:
    """Initial temperature field of a transient analysis.

    Parameters
    ----------
    kind : {"uniform", "expression", "per_region", "from_results"}
    value : Function, optional
        Temperature [K] for ``uniform`` / ``expression`` (may use x and y).
    per_region : dict of str to float, optional
        Region selection name -> temperature [K].
    results_path : str, optional
        Results file whose last step is taken as the initial field.
    """

    kind: Literal["uniform", "expression", "per_region", "from_results"]
    value: Function | None = None
    per_region: dict[str, float] | None = None
    results_path: str | None = None

    def __post_init__(self) -> None:
        kinds = ("uniform", "expression", "per_region", "from_results")
        if self.kind not in kinds:
            raise ModelError(f"initial condition kind must be one of {', '.join(kinds)}")
        coerce_functions(self)


def _default_mesh_settings() -> MeshSettings:
    return MeshSettings(global_size=DEFAULT_GLOBAL_SIZE)


def _default_initial_condition() -> InitialCondition:
    return InitialCondition("uniform", value=Constant(DEFAULT_INITIAL_TEMPERATURE))


@dataclass
class Model:
    """Everything needed to build, mesh and solve an analysis.

    Attributes
    ----------
    schema_version : int
        Version of the file format.
    name : str
    analysis : {"planar", "axisymmetric"}
        Axisymmetric models use x as the radius and y as the axis.
    display_units : UnitSettings
    geometry : list of GeometryOp
        Replayed in order by the builder.
    selections : dict of str to Selection
    materials : dict of str to Material
    regions : list of RegionAssignment
    mesh_settings : MeshSettings
    initial_condition : InitialCondition
    bcs : list of BoundaryCondition
    streams : list of Stream
    network : FlowNetwork, optional
    enclosures : list of Enclosure
    contacts : list of Contact
    solution : SolutionSettings
    """

    schema_version: int = SCHEMA_VERSION
    name: str = "Untitled"
    analysis: Literal["planar", "axisymmetric"] = "planar"
    display_units: UnitSettings = field(default_factory=UnitSettings)
    geometry: list[GeometryOp] = field(default_factory=list)
    selections: dict[str, Selection] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    regions: list[RegionAssignment] = field(default_factory=list)
    mesh_settings: MeshSettings = field(default_factory=_default_mesh_settings)
    initial_condition: InitialCondition = field(default_factory=_default_initial_condition)
    bcs: list[BoundaryCondition] = field(default_factory=list)
    streams: list[Stream] = field(default_factory=list)
    network: FlowNetwork | None = None
    enclosures: list[Enclosure] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    solution: SolutionSettings = field(default_factory=SolutionSettings)

    def __post_init__(self) -> None:
        if self.analysis not in ("planar", "axisymmetric"):
            raise ModelError(f"analysis must be 'planar' or 'axisymmetric', got {self.analysis!r}")

    @property
    def axisymmetric(self) -> bool:
        """True for an axisymmetric analysis."""
        return self.analysis == "axisymmetric"
