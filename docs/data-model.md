# Data model and public interfaces

All classes are `@dataclass`es with full type hints. Signatures here are fixed (Plan §4.6).

## §1 Functions (load values)

`core/functions.py`. Every numeric load or property field accepts a `Function`.

```python
class Function(Protocol):
    def __call__(self, t: float = 0.0, x: ndarray | float = 0.0,
                 y: ndarray | float = 0.0, T: ndarray | float = 0.0) -> ndarray | float: ...
    depends_on_T: bool
    depends_on_time: bool
    def breakpoints(self) -> list[float]: ...     # times the stepper must land on

Constant(value: float)
Table(xs: list[float], ys: list[float], variable: Literal["t", "T"],
      extrapolate: Literal["hold", "linear"] = "hold")   # piecewise linear
Expression(text: str)      # e.g. "500 + 20*sin(2*pi*t/60)"; variables t, x, y, T
```

`Expression` is evaluated with a restricted AST walker (no `eval` on raw text): allowed
nodes are numbers, the names `t x y T pi e`, arithmetic operators, comparisons, and calls to
`sin cos tan exp log log10 sqrt abs minimum maximum where tanh`. Anything else raises
`ModelError`. `depends_on_T` / `depends_on_time` are found by scanning the names used.

JSON form: `{"type": "constant", "value": 5}`, `{"type": "table", "variable": "t",
"xs": [...], "ys": [...]}`, `{"type": "expression", "text": "..."}`. A bare number in JSON
is read as a `Constant`.

## §2 Mesh

`core/mesh.py`. The only mesh representation the solver and post-processor see.

Written for any space dimension (Plan §7). Today `dim = 2`, element types are T3, Q4, T6,
Q8 and facet types are L2, L3. "Facet" = boundary element of dimension dim − 1 (an element
edge in 2D); "entity" = the geometry curve (2D) or surface (3D) it lies on.

```python
@dataclass
class ElementBlock:
    etype: str             # key into the element registry (§13), e.g. "T3"
    conn: ndarray          # (n_elem, n_nodes_per_elem) int64, 0-based node indices
    region: ndarray        # (n_elem,) int32 region id
    elem_ids: ndarray      # (n_elem,) global element numbers, 0-based, unique across blocks

@dataclass
class FacetBlock:
    etype: str             # e.g. "L2", "L3"
    conn: ndarray          # (n_facet, n_nodes_per_facet)
    entity: ndarray        # (n_facet,) int32 geometry tag of the curve (2D) / surface (3D)
    parent_elem: ndarray   # (n_facet,) global id of the adjacent element
                           # (on an interface: the element on the lower region id)

@dataclass
class Mesh:
    dim: int                           # space dimension; 2 today
    nodes: ndarray                     # (n_nodes, dim) float64, metres
    blocks: list[ElementBlock]
    facets: list[FacetBlock]           # every element facet lying on a geometry entity
    node_sets: dict[str, ndarray]      # named selection -> node indices
    point_nodes: dict[int, int]        # geometry point tag -> node index
    axisymmetric: bool
    def facets_on(self, entity_tags: Sequence[int]) -> list[FacetBlock]: ...
    def region_elements(self, region_id: int) -> list[ElementBlock]: ...
    def outward_normals(self, facet_block: FacetBlock) -> ndarray: ...   # (n_facet, dim)
    def validate(self) -> None:   # positive Jacobians, no orphan nodes, facet orientation
```

Facet orientation in 2D: nodes are stored so that the parent element lies on the **left**;
the outward normal is then (dy, −dx)/length. `outward_normals` must give the same result
by the general rule (normal to the facet, pointing away from the parent element centroid)
so that it also works in 3D.

## §3 Model

`model/model.py`. The complete, serialisable description of an analysis.

```python
@dataclass
class Model:
    schema_version: int = 1
    name: str = "Untitled"
    analysis: Literal["planar", "axisymmetric"] = "planar"
    display_units: UnitSettings              # §7
    geometry: list[GeometryOp]               # §4, replayed in order
    selections: dict[str, Selection]         # §5
    materials: dict[str, Material]           # §6
    regions: list[RegionAssignment]          # surface selection -> material, thickness, angle
    mesh_settings: MeshSettings
    initial_condition: InitialCondition
    bcs: list[BoundaryCondition]             # §8
    streams: list[Stream]                    # §9
    network: FlowNetwork | None
    enclosures: list[Enclosure]
    contacts: list[Contact]
    solution: SolutionSettings               # §10
```

```python
@dataclass
class RegionAssignment:
    selection: str               # name of a surface selection
    material: str
    thickness: float = 1.0       # m, planar only
    material_angle: float = 0.0  # rad, orthotropic only

@dataclass
class MeshSettings:
    global_size: float                       # m
    order: Literal[1, 2] = 1
    element_shape: Literal["tri", "quad"] = "tri"
    algorithm: Literal["delaunay", "frontal", "frontal_quad"] = "frontal"
    curve_sizes: dict[str, float]            # selection name -> size
    point_sizes: dict[str, float]
    curve_divisions: dict[str, int]          # selection name -> number of elements (transfinite curve)
    structured_surfaces: list[str]           # selections to mesh transfinite
    refinements: list[Refinement]            # distance-based: selection, size_min, size_max, dist_min, dist_max
    smoothing_passes: int = 3

@dataclass
class InitialCondition:
    kind: Literal["uniform", "expression", "per_region", "from_results"]
    value: Function | None = None            # uniform / expression (uses x, y)
    per_region: dict[str, float] | None = None
    results_path: str | None = None          # take the last step of another results file
```

## §4 Geometry operations

`model/geometry_ops.py`. Geometry is stored as a **history of operations**, not as shapes.
Each op has a unique `id: str`, and refers to earlier ops' results by id.

| Op | Fields |
|---|---|
| `Point` | x, y |
| `Line` | p1, p2 (point op ids) |
| `Arc` | p_start, p_center, p_end |
| `Spline` | points: list of point op ids |
| `Rectangle` | x, y, width, height, corner_radius = 0 |
| `Circle` | xc, yc, radius |
| `Polygon` | vertices: list[(x, y)] |
| `SurfaceFromCurves` | curves: list of curve op ids (closed loop), holes: list of loops |
| `Boolean` | kind: union \| cut \| intersect, objects: [ids], tools: [ids] |
| `Transform` | kind: translate \| rotate \| mirror \| scale, targets: [ids], params, copy: bool |
| `ImportFile` | path, format: step \| brep \| dxf, scale = 1.0 |
| `Delete` | targets: [ids] |

`geometry.builder.build(model) -> BuiltGeometry` replays the list in gmsh, then performs one
final `occ.fragment` over **all** surfaces so that neighbouring regions share curves and the
mesh is conformal. `BuiltGeometry` lists final surface, curve and point tags, each with a
fingerprint (§5), and sampled polylines for display.

## §5 Selections

Loads never store raw gmsh tags alone, because tags can change when geometry is edited.

```python
@dataclass
class Fingerprint:
    dim: int                      # 0 point, 1 curve, 2 surface (3 volume in future)
    center: tuple[float, float, float]   # centre of mass (z = 0 today)
    measure: float                # 0, length, area (or volume)
    bbox: tuple[float, float, float, float, float, float]   # xmin ymin zmin xmax ymax zmax

@dataclass
class Selection:
    name: str
    dim: int
    tags: list[int]               # tags at the time of selection
    fingerprints: list[Fingerprint]
```

`model/selections.py: resolve(selection, built) -> list[int]`: for each fingerprint find the
entity of the same dim whose centre is within 1e-6·L and measure within 1e-6 relative
(L = model bounding-box diagonal). If none matches, the selection is **stale**: validation
fails with a message naming the selection. `resolve` runs on every build.

## §6 Materials

```python
@dataclass
class Material:
    name: str
    k: Function                    # W/m·K (isotropic)  — constant or Table vs T
    k2: Function | None = None     # if set: orthotropic, k = k1 along material axis, k2 across
    rho: Function                  # kg/m³
    cp: Function                   # J/kg·K
    phase_change: PhaseChange | None = None   # T_sol, T_liq [K], latent_heat [J/kg]

@dataclass
class Fluid:
    name: str
    ideal_gas: bool                # True -> beta = 1/T
    T: list[float]                 # K, ascending
    rho: list[float]; cp: list[float]; mu: list[float]; k: list[float]
    beta: list[float] | None       # 1/K, liquids only
    def props(self, T: ndarray) -> FluidProps   # linear interpolation, clamp at ends + warning
```

### Built-in property sources (owner's decision, 2026-11-23; `docs/property-verification.md`)

Every built-in value comes from one of two sources. Nothing is estimated or interpolated when
a table is built:
- **[I]**: Bergman, Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*,
  7th ed., Wiley, 2011, Appendix A. The page numbers are the book's own.
- **[N]**: NIST Chemistry WebBook, SRD 69, *Thermophysical Properties of Fluid Systems*, read
  on 2026-11-23.

Each entry in the data files carries a `source` string, and may carry a `note`. These are
documentation only: `Material.from_json` and `Fluid.from_json` ignore them, and user-library
entries need neither. A material or fluid is built in only if the source gives every value it
needs; anything with a missing value is left out.

### Built-in solids (`materials/data/solids.json`), constant values at 300 K

- **Contents.** Every material of [I] Tables A.1, A.2 and A.3 for which ρ, c_p and k are all
  printed at 300 K. That is 113 isotropic materials.
  - **Orthotropic.** Four more come from Table A.2, which gives k parallel and perpendicular to
    an axis: boron fiber epoxy (30% vol), pyrolytic graphite, graphite fiber epoxy (25% vol)
    and crystalline quartz. Each is built with `k` along the material axis and `k2` across
    it.
- **Names.**
  - Most are as printed, written "group, row" where the book groups rows (for example
    "Aluminum, Alloy 2024-T6"). A composition printed in parentheses after a name goes into
    the `note`.
  - Boron is in both Table A.1 and Table A.2 with different values, so the two are named
    "Boron, Table A.1" and "Boron, Table A.2".
  - The two vermiculite rows are named by their densities.
  - Five materials keep their earlier names: "Copper (pure)", "Carbon steel AISI 1010",
    "Stainless steel 304", "Alumina (polycrystalline)" and "Soda-lime glass". "Silicon" and
    "Concrete (stone mix)" are printed that way already.
- **Removed on 2026-11-23** because [I] does not contain them: Aluminium 6061-T6, Titanium
  Ti-6Al-4V and FR-4. Models saved with them keep their own copies, because a model stores
  its materials.
- **The full list** with values is generated into the guide (`guide/materials.md`). Spot
  values that tests check:

| Name | k [W/m·K] | ρ [kg/m³] | c_p [J/kg·K] | Source |
|---|---|---|---|---|
| Aluminum, Alloy 2024-T6 | 177 | 2770 | 875 | [I] A.1, p. 983 |
| Copper (pure) | 401 | 8933 | 385 | [I] A.1, p. 983 |
| Stainless steel 304 | 14.9 | 7900 | 477 | [I] A.1, p. 985 |
| Alumina (polycrystalline) | 36.0 | 3970 | 765 | [I] A.2, p. 987 |
| Graphite, pyrolytic | 1950 along, 5.70 across | 2210 | 709 | [I] A.2, p. 987 |
| Concrete (stone mix) | 1.4 | 2300 | 880 | [I] A.3, p. 993 |

### Built-in fluids (`materials/data/fluids.json`)

Every row printed in the source is used, except rows with a missing value. Properties are
interpolated linearly between rows and held at the end rows outside them (Theory §8).

| Fluid | Source | Rows (T range) | Notes |
|---|---|---|---|
| Air | [I] A.4, p. 995 | 35 (100–3000 K) | ideal gas; densities are those of **1 bar** |
| Water | [N], liquid at 0.1 MPa | 19 (280–370 K, every 5 K) | β = −(1/ρ) ∂ρ/∂T, a central difference of [N] densities at T ± 0.5 K (agrees with the IAPWS-95 value to 0.04 %); values rounded to 6 significant figures. The table starts at 280 K because β < 0 below 277 K |
| Ammonia, Carbon Dioxide, Carbon Monoxide, Hydrogen, Nitrogen, Oxygen | [I] A.4, pp. 995–999 | all rows | ideal gases; densities are those of 1 bar |
| Helium | [I] A.4, p. 997 | 11 of 24 | ideal gas, 1 atm. The other 13 rows print no ρ (one also no μ, k) and are left out |
| Water Vapor (Steam) | [I] A.4, p. 999 | 11 (380–850 K) | ideal gas, 1 atm |
| Engine Oil (Unused), Ethylene Glycol, Glycerin, Refrigerant-134a, Refrigerant-22, Mercury | [I] A.5, pp. 1000–1001 | all rows | saturated liquids; β from the table |

The pressures were found by comparing each gas's densities with CoolProp 8.1.0 at 1 bar and at
1 atm. Every gas matches one of them to within 0.05 %. Table A.7 (liquid metals) is not used,
because it gives no β. Spot rows that tests check:

| Fluid | T [K] | ρ | c_p | μ [Pa·s] | k [W/m·K] | β [1/K] |
|---|---|---|---|---|---|---|
| Air | 300 | 1.1614 | 1007 | 184.6e-7 | 0.0263 | (1/T) |
| Air | 3000 | 0.1135 | 2726 | 955e-7 | 0.486 | (1/T) |
| Water | 300 | 996.556 | 4180.64 | 8.53743e-4 | 0.609499 | 2.74797e-4 |
| Water | 360 | 967.403 | 4202.34 | 3.25855e-4 | 0.671114 | 6.79384e-4 |
| Ethylene Glycol | 300 | 1114.4 | 2415 | 1.57e-2 | 0.252 | 0.65e-3 |

**Known doubtful value:** the book's oxygen row at 1300 K prints μ·10⁷ = 588.4, but its own ν
(188.6e-6) gives 558.4, and the steps between rows suggest a misprint. It is kept as printed,
by the owner's decision (OPEN_QUESTIONS Q30). The book's water β at 360 K (697.9e-6) is not used, since water comes
from [N].

Users can add their own solids and fluids; user libraries are stored in
`%APPDATA%/ThermalFEA/materials.json`.

## §7 Units

`core/units.py`. Internal values are SI/kelvin. `UnitSettings` holds the display choices:
temperature `K | degC | degF`, length `m | mm | in`, and a consistent derived set.
Functions `to_si(value, quantity, settings)` and `from_si(...)` for quantities:
`length, temperature, temperature_difference, conductivity, htc, heat_flux, heat_gen,
power, density, specific_heat, time, mass_flow, pressure`. The `.tfea` file always stores SI.
Since task M10.4 every quantity has a selectable unit, with the presets `SI (m)`, `SI (mm)`
and `US customary` (`UnitSettings.preset`); further quantities `velocity`, `area`, `angle`
(OPEN_QUESTIONS Q24).

## §8 Boundary conditions

`model/bcs.py`. Every BC has `name`, `selection` (name), and `active: bool`.

| Class | Applies to | Fields |
|---|---|---|
| `FixedTemperature` | curves, points | `T: Function` |
| `HeatFlux` | curves | `q: Function` [W/m²], positive into the body |
| `HeatFlow` | curves | `P: Function` [W] total, spread uniformly |
| `HeatGeneration` | surfaces | `Q: Function` [W/m³] |
| `HeatPower` | surfaces | `P: Function` [W] total |
| `Convection` | curves | `h: Function`, `T_inf: Function` |
| `CorrelationConvection` | curves | `correlation: str` (Theory §8 ID), `fluid: str`, `T_inf: Function`, `velocity: Function \| None`, `char_length: float \| None` (auto from geometry if None), `face_direction: up \| down \| None`, `wall_T_mode: local \| average`, `multiplier: float = 1`, `params: dict[str, float]` (keys per correlation, Theory §8: `theta_deg`; `x0, y0, dir_x, dir_y`; `C, n`; `S`; `W, H, x_r`; `D, H, r_r`) |
| `RadiationAmbient` | curves | `emissivity: Function`, `T_inf: Function` |
| `Symmetry` / `Adiabatic` | curves | none (documentation only; contributes nothing) |

Enclosure radiation, streams and contacts are separate lists on the model:

```python
@dataclass
class Enclosure:
    name: str
    surfaces: list[EnclosureSurface]     # each: selection (curves), emissivity: float
    open_to_ambient: bool = False
    T_ambient: Function | None = None

@dataclass
class Contact:
    name: str; selection: str            # interface curves between two regions
    conductance: Function                # W/m²·K

@dataclass
class Stream:
    name: str
    fluid: str
    mode: Literal["in_plane", "through_plane"]
    walls: list[str]                     # curve selections wetted by the stream
    flow_area: float                     # m²
    wetted_perimeter: float              # m, for D_h
    cross_section: Literal["circular", "parallel_plates", "parallel_plates_one_side", "square",
                           "rectangle_1_43", "rectangle_2", "rectangle_3", "rectangle_4",
                           "rectangle_8", "triangle", "annulus_inner", "annulus_outer"]
                                         # Theory §8.1 (added 2026-11-23)
    roughness: float = 0.0
    mass_flow: Function | None           # kg/s; None when taken from a network branch
    T_inlet: Function
    path: list[tuple[float, float]] | None    # polyline inlet -> outlet (in_plane only)
    n_cells: int | None = None           # default: one per wall edge along the path
    nu_option: Literal["auto", "dittus_boelter", "sieder_tate"] = "auto"
    h_multiplier: float = 1.0
    diameter_ratio: float | None = None  # D_i/D_o, annulus cross-sections only (Theory §8.1)

@dataclass
class FlowNetwork:
    nodes: list[NetNode]        # id, pressure: float | None, inflow: float | None
    branches: list[NetBranch]   # id, node_from, node_to, kind: duct | loss, length, K_minor,
                                # stream: str | None (takes area, D_h, roughness from the stream)
```

### Validation (`model/validate.py: validate(model, built, mesh) -> list[Issue]`)
Errors block the solve; warnings do not. Minimum checks:
- every surface has exactly one region assignment; every referenced material/fluid exists
- no stale selection; no curve carries two `FixedTemperature` BCs
- steady analysis has at least one temperature reference (fixed T, convection, radiation
  or an in-plane stream); otherwise the matrix is singular — error
- radiation present and any temperature ≤ 0 K — error
- transient analysis: ρ and c_p > 0 everywhere, end time > 0
- axisymmetric: no node with x < −1e-9·L
- material property tables cover the expected temperature range — warning
- contact curve is an interface between exactly two regions

## §9 Results file (HDF5, `<model>.tfea.h5`)

```
/meta            attrs: schema_version, model_hash, created, analysis, solver settings (JSON)
/mesh            attr dim
/mesh/nodes      (n_nodes, dim)
/mesh/blocks/<i> conn, region, elem_ids; attr etype
/mesh/facets/<i> conn, entity, parent_elem; attr etype
/steps/time      (n_steps,) extendable
/steps/fields/<name>   (n_steps, n_values[, n_components]) extendable, chunked by step, gzip;
                 attrs: location (node | element | facet | extra:<group>), units.
                 Today the only stored field is `T` (location node) plus one
                 `T_fluid:<stream>` per in-plane stream (location extra:<stream>).
/steps/dt, /steps/iterations, /steps/converged
/steps           attr last_step: time-step number of the last stored step (M10.6, Q25)
/steps/energy    (n_steps, k) columns named in attr `columns`
/fluid/<stream>  node s-coordinates, dof indices; per step: mass_flow, h_mean, Re, dp
/reactions/<bc>  (n_steps,) total heat flow per boundary condition [W]
```

`post/results.py: Results(path)` gives lazy access: `times`, `temperature(step)`,
`nodal_history(node)`, `flux(step)`, `heat_flow(bc_name)`, `energy_balance()`, `mesh`.
Flux is computed on demand from T (not stored), which needs the materials: the model JSON
is embedded in `/meta`.

## §10 Solution settings

```python
@dataclass
class SolutionSettings:
    kind: Literal["steady", "transient"] = "steady"
    end_time: float = 1.0
    initial_dt: float | None = None       # None -> Theory §6.1 suggestion
    dt_min: float = 1e-9; dt_max: float | None = None
    auto_timestep: bool = True
    time_tol: float = 0.02
    max_dT_per_step: float | None = None
    theta: float = 1.0
    lumped_capacitance: bool = False
    output: Literal["all", "every_n", "times"] = "all"
    output_every: int = 1; output_times: list[float] = field(default_factory=list)
    rtol: float = 1e-6; ttol: float = 1e-4; max_iterations: int = 30
    line_search: bool = True
```

## §11 Public scripting API (`thermalfea.api`)

```python
model = api.new_model(analysis="planar")
api.load(path) -> Model;  api.save(model, path)
geo = api.Geometry(model)                 # thin helpers that append GeometryOps
r = geo.rectangle(0, 0, 0.6, 1.0)
built = api.build(model)                  # BuiltGeometry
sel = api.select_curves(model, built, name="bottom", where=lambda c: abs(c.center[1]) < 1e-9)
api.assign_region(model, "all", material="Carbon steel AISI 1010")
model.bcs.append(FixedTemperature("base", "bottom", T=373.15))
mesh = api.mesh(model, built)
results = api.solve(model, mesh, progress=callback)   # -> Results
api.plot_contour(results, step=-1, field="T", path="out.png")
```

`progress(info: StepInfo) -> bool`: called after each step/iteration; returning `False`
cancels the solve cleanly (results so far remain valid).

## §13 Extension interfaces (Plan §7)

These are the seams that let later versions add 3D, new physics, another flow solver and
another viewport. Build them as specified even though each has one implementation today.

```python
# core/registry.py
@dataclass(frozen=True)
class ElementType:
    name: str                    # "T3"
    dim: int                     # dimension of the element itself (2 for T3, 1 for L2)
    n_nodes: int
    order: int
    gmsh_type: int
    shape: Callable[[ndarray], ndarray]      # pts (n, dim) -> N (n, n_nodes)
    dshape: Callable[[ndarray], ndarray]     # pts -> dN (n, dim, n_nodes)
    node_coords: ndarray                     # (n_nodes, dim) reference coordinates
    quadrature: tuple[ndarray, ndarray]      # points, weights
    facet_type: str | None                   # "L2" for T3/Q4, "L3" for T6/Q8, None for facets
    facets: ndarray | None                   # local node indices of each facet
    display_simplices: ndarray               # local indices splitting it into linear simplices

register_element(et: ElementType) -> None;  element(name: str) -> ElementType
register_bc(tag: str, cls: type, term_factory: Callable, form: FormSpec | None) -> None
register_field(name: str, spec: ResultFieldSpec) -> None    # derived, plottable result fields
```

```python
# solver/dofs.py
class DofMap:
    def add_field(self, name: str, n_nodes: int, components: int = 1) -> None
    def add_extra(self, group: str, count: int) -> None          # e.g. fluid nodes of a stream
    def node_dofs(self, field: str, nodes: ndarray, component: int = 0) -> ndarray
    def extra_dofs(self, group: str) -> ndarray
    n_dofs: int

# solver/terms.py
@dataclass
class State:
    u: ndarray            # current iterate, all DOFs
    u_prev: ndarray       # converged solution of the previous step (transient)
    t: float; dt: float | None
    dofs: DofMap

class Term(Protocol):
    name: str
    is_linear: bool                  # contribution does not depend on u
    is_time_dependent: bool
    symmetric: bool
    def setup(self, problem: "CompiledProblem") -> None: ...        # precompute geometry etc.
    def conductance(self, s: State, asm: Assembler) -> None: ...    # adds to K and tangent
    def load(self, s: State, asm: Assembler) -> None: ...           # adds to F / residual
    def capacitance(self, s: State, asm: Assembler) -> None: ...    # adds to C (may do nothing)
    def breakpoints(self) -> list[float]: ...
    def boundary_heat(self, s: State) -> float | None: ...          # for the energy balance
    def results(self, s: State) -> dict[str, ndarray]: ...          # extra per-step output
```

`CompiledProblem` is a list of terms, a `DofMap`, the prescribed-DOF provider and the
settings. `solver/steady.py` and `solver/transient.py` loop over `problem.terms` and
contain no heat-transfer-specific code. Each module in `physics/`, plus `flow/` and the
convection evaluator, exposes its work as one or more `Term`s.

```python
# flow/provider.py
class FlowProvider(Protocol):
    def setup(self, problem) -> None: ...          # may add extra DOF groups
    def terms(self) -> list[Term]: ...             # coupling terms for the solid system
    def update(self, s: State) -> None: ...        # e.g. re-solve hydraulics (lagged)
    def results(self, s: State) -> dict[str, ndarray]: ...
```
The 1D stream/network solver is `flow/coupling.py: StreamNetworkProvider`.

```python
# gui/scene.py — the only viewport API the rest of the GUI may use
class SceneView(Protocol):
    selection_changed: Signal            # (dim: int, tags: list[int])
    point_picked: Signal                 # (x, y, z)
    def widget(self) -> QWidget: ...
    def set_geometry(self, built: BuiltGeometry | None) -> None: ...
    def set_mesh(self, mesh: Mesh | None, color_by: ndarray | None = None) -> None: ...
    def set_field(self, spec: FieldDisplay | None) -> None: ...      # contour / vector display
    def set_symbols(self, symbols: list[LoadSymbol]) -> None: ...
    def set_selection_mode(self, mode: Literal["none","point","curve","surface","node","element"]) -> None: ...
    def highlight(self, dim: int, tags: list[int]) -> None: ...
    def fit(self) -> None: ...
    def save_image(self, path: str, dpi: int = 200) -> None: ...
```
`FieldDisplay` carries plain arrays (display simplices, values, vectors, range, levels,
labels) prepared by `post/`, so a different renderer needs no access to solver objects.

```python
# solver/linear.py
class LinearSolver(Protocol):
    def factorize(self, A: csr_matrix, symmetric: bool) -> "Factorization": ...
class Factorization(Protocol):
    def solve(self, b: ndarray) -> ndarray: ...
```

`model/migrations.py: MIGRATIONS: dict[int, Callable[[dict], dict]]` — entry `n` upgrades a
model dict from schema version n to n + 1; `from_json` applies them in sequence.

## §12 Errors
`core/errors.py`: `ThermalFEAError` base; `ModelError` (bad input), `GeometryError`,
`MeshError`, `ConvergenceError`, `SolverError` (singular matrix etc.). The GUI shows the
message of any `ThermalFEAError` in a dialog; any other exception is a bug and is logged
with traceback.
