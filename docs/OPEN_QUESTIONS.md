# Open questions

Questions and decisions that the plan documents do not settle (Plan §4 rules 2, 3, 6, 9, 11).
Each entry says what was done in the meantime, so a reviewer can confirm or overrule it.

## Q1 — `Material` field order (Data §6) — raised in M1.8

Data §6 lists the fields of `Material` as `name, k, k2 = None, rho, cp, phase_change = None`.
A dataclass cannot have a field without a default (`rho`) after one with a default (`k2`).

**Done for now:** `k2` and `phase_change` are keyword-only fields, so the signature is
`Material(name, k, rho, cp, *, k2=None, phase_change=None)`. Every call written with
keywords, as in the data model, works unchanged. Field names, types and defaults are as
specified.

**To confirm:** that keyword-only `k2` / `phase_change` is acceptable, or give the
intended positional order.

## Q2 — fluid names in the built-in library (Data §6) — raised in M1.8

The data model heads the two fluid tables "Air at 1 atm" and "Water, saturated liquid" but
does not give the `name` stored in `fluids.json`.

**Done for now:** the names are `"Air"` and `"Water"`; lookups by `library.fluid(name)` and
`library.solid(name)` ignore case.

## Q3 — V-01 / V-37 at the M1 gate use the kernel directly — raised in M1.G

V-37 asks for a solve "with the unmodified kernel, `ConductionTerm` and steady driver", and
verification cases are meant to have a runnable script in `examples/`. `ConductionTerm`
(M3.1), the steady driver (M3.7) and the scripting API (M2.11, M3.11) do not exist at M1.G.

**Done for now:** V-01 (temperature part), V-33 and V-37 solve through
`geometry` -> `conduction` -> `DofMap`/`Assembler` -> `solve_partitioned`
(`tests/verification/kernel_solve.py`). All three pass at their stated tolerances, and
V-37 passes with no library code mentioning `Tet4` or a 3D case.

**Still to do at M3.G:** switch V-37 to `ConductionTerm` + `solve_steady`, add the flux part
of V-01 through `post/recovery.py`, and add the `examples/` scripts for these cases.

## Q4 — defaults and field order in the model classes (Data §3, §8) — raised in M2.1

1. `Stream` (Data §8) lists `roughness = 0.0` before the required `mass_flow`, `T_inlet` and
   `path`, the same problem as Q1. **Done for now:** `Stream` is a keyword-only dataclass;
   `mass_flow` and `path` default to `None` (the data model says they may be `None`).
2. `BoundaryCondition.active` has no stated default. **Done for now:** keyword-only,
   default `True`, so `FixedTemperature("base", "bottom", T=373.15)` works as in Data §11.
3. `Model()` needs a `mesh_settings` and an `initial_condition`, but `MeshSettings.global_size`
   and `InitialCondition.kind` have no defaults. **Done for now:** a new model gets
   `global_size = 0.01` m and a uniform initial temperature of 293.15 K
   (`model/model.py: DEFAULT_GLOBAL_SIZE, DEFAULT_INITIAL_TEMPERATURE`). Both are
   placeholders chosen here, not numbers from the plan.
4. `Transform.params` is not specified. **Done for now:** a `dict[str, float]` with keys
   `dx, dy` (translate); `angle, cx, cy` (rotate, radians); `x0, y0, x1, y1` (mirror line);
   `factor, cx, cy` (scale).
5. `NetBranch` defaults: `kind = "duct"`, `length = 0`, `K_minor = 0`, `stream = None`.

## Q5 — construction geometry after the final fragment — raised in M2.5

The plan says the builder ends with one `occ.fragment` over all surfaces, but not what
happens to points and curves that bound no surface (construction points, a spline's
interior points, unused lines). Left in the gmsh model they would be meshed as curve
elements with no parent element.

**Done for now:** after the fragment, curves and points that bound no surface are removed,
and their operations own no entities (`built.op_entities[id] == []`). Consequence: a free
point or curve drawn *inside* a surface is not embedded in the mesh. If embedded points or
curves are wanted (for a point load or a probe line), that needs a decision and an
explicit embed step.

Also: `SurfaceFromCurves` accepts its curves in any order; the builder chains them by
shared end points because gmsh requires loop order.

## Q6 — definitions of the mesh quality measures — raised in M2.9

The plan names the measures (min angle, aspect ratio, min/max Jacobian ratio) without
defining them. **Done for now** (`meshing/quality.py`): minimum interior corner angle in
degrees from the straight lines between corner nodes; aspect ratio = longest / shortest
corner-to-corner side; Jacobian ratio = min det J / max det J over the integration points
and the nodes. No pass/fail thresholds are applied; the report only measures.
