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

**Resolved at M3.G:** V-37 and V-33 now solve with `ConductionTerm` and the steady driver
(hand-built `CompiledProblem`, no change to library code for `Tet4` or 3D); V-01 checks
the recovered nodal flux; V-01 … V-14 and V-32 each have a runnable `examples/vNN_*.py`
that their test loads. V-33 and V-37 have no example script: they are built on hand-made
meshes inside their tests (V-37 by requirement).

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

## Q7 — the selection named "all" (Data §11) — raised in M2.11

The script in Data §11 calls `api.assign_region(model, "all", material=...)` without ever
creating a selection called "all".

**Done for now:** `api.build(model)` creates (and on every rebuild replaces) a selection
named `"all"` that holds every surface. The name is therefore reserved: a user selection
called "all" is overwritten by the next build. `api.build` also resolves every other
selection against the new geometry and logs a warning for each stale one.

Related choices in the facade: `api.Geometry` methods return the id of the operation they
append, auto-named `<class><n>` (`rectangle1`, `boolean2`, ...) unless `id=` is given;
`assign_region` copies a library solid into `model.materials` when the model has no
material of that name, and replaces an existing assignment of the same selection.

## Q8 — how terms express tangent-only and residual-only parts (Data §13) — raised in M3.1

The `Term` protocol has `conductance` ("adds to K and tangent") and `load` ("adds to F /
residual"), but Theory §5 needs four separate things: K and F (with r = F − K T and
F_ref = max(‖F‖, ‖K T‖)), the tangent-only matrix K_rad, and the residual-only vector
r_rad. The protocol does not say how a term tells them apart.

**Done for now:** the `Term` signatures are unchanged. `Assembler` has two extra channels,
`add_tangent` and `add_residual`; a term's `conductance` may call `add_matrix` (K) and/or
`add_tangent` (tangent only), and its `load` may call `add_vector` (F) and/or
`add_residual` (residual only). The drivers form r = F − K u + residual and the tangent
K + tangent, exactly as Theory §5 and §6 write them.

Also added, since Data §13 names a "prescribed-DOF provider" without specifying it: a
`Constraint` protocol (`setup`, `values(t) -> (dofs, values)`, `breakpoints`,
`is_time_dependent`), a `constraint_factory` slot beside `term_factory` in the BC
registry, and `CompiledProblem.prescribed(t)`, which merges the constraints (the later
one wins, with a logged warning).

## Q9 — value of the Stefan–Boltzmann constant — raised in M3.6

Theory §5 uses σ without giving its value. V-14 (NAFEMS T2) quotes σ = 5.67e-8.

**Done for now:** `core/constants.py: STEFAN_BOLTZMANN = 5.670374419e-8` W/(m² K⁴), the
exact CODATA 2018 value. It differs from 5.67e-8 by 6.6e-5 relative, far inside the
0.1 K tolerance of V-14. Verification tests that compute an analytic answer import the
same constant. If the benchmark value 5.67e-8 should be used instead, change that one line.

## Q10 — details of the steady driver that Theory §5 leaves open — raised in M3.7

1. **Starting temperature of the nonlinear iteration.** Not specified. **Done for now:**
   uniform, equal to the mean of the prescribed temperatures; if there are none, the
   model's uniform initial condition; failing that 293.15 K. `steady_solution(problem, T0=…)`
   accepts an explicit start.
2. **Time at which a steady analysis evaluates time-dependent loads.** Not specified.
   **Done for now:** t = 0.
3. **Norms in F_ref = max(‖F‖₂, ‖K T‖₂, 1e-12).** Taken over *all* DOFs, so that the
   reaction heat flows at prescribed nodes count. Over the free DOFs alone F_ref would be
   zero for a body loaded only through fixed temperatures (V-13), and the residual test
   could never pass. ‖r_f‖₂ is over the free DOFs, as written.
4. **When the convergence test is applied.** After the update of step 4, with the residual
   at the new iterate and the step just taken. A linear residual solved exactly in one
   step therefore takes two iterations in the Newton path (the first step is large, the
   second confirms); truly linear problems never enter that path.
5. **Line search switched off** (`line_search = False`): the full step is taken, except
   that a trial with a temperature ≤ 0 K is still halved, as Theory §5 requires.

## Q11 — sign convention of reported heat flows — raised in M3.10

Theory §4 defines the reaction at a prescribed node as positive when heat *enters* the
body, and the energy balance of §7 sums "generation + heat in". Theory §7 also lists the
heat flow through a boundary set as positive *out* of the body. Reporting some flows
positive-in and others positive-out in one table would be confusing.

**Done for now:** one convention everywhere — a reported heat flow is positive when heat
enters the body (`Term.boundary_heat`, `post/reactions.heat_flows`, the energy balance,
and later the `/reactions/<bc>` datasets). The magnitudes are those of Theory §7; only
the sign of the boundary-set formulas is reversed. A fixed-temperature set reports
+Σ R_p. If §7's positive-out convention is wanted for boundary sets, it is one sign in
`heat_flows`.

**Scale of the relative imbalance (found at M3.G).** Theory §7 reports
imbalance / max(|terms|). When one fixed-temperature condition both supplies and removes
all the heat (the patch test: one condition on the whole boundary), its net flow is zero
and so is every term, and the ratio becomes round-off over round-off. **Done for now:**
the scale also includes the heat passing through the prescribed nodes, summed node by
node (the larger of what enters and what leaves). This only ever enlarges the scale in
that degenerate situation; in every other verification case it changes nothing.

## Q13 — choices made in the verification examples — raised in M3.G

- **Nodes at check points.** V-09 and V-10 check the temperature at given points. Point
  interpolation arrives with M5.4, so the geometry is drawn in several rectangles whose
  corners are the check points, making them mesh nodes. The physics is unchanged.
- **Structured meshes.** The "1D" strips, V-12 and V-32 use transfinite meshes with the
  stated number of elements or size. V-12 needs this for Q8: an eight-node serendipity
  quadrilateral reproduces a full quadratic field only when it is a parallelogram, so the
  1e-9 tolerance cannot hold on a free quad mesh. T6 does not have that restriction.
- **V-07** lists only "linear 1e-3"; all four element types are run at 1e-3.
- **V-10 coarse mesh.** The requirement is 0.15 °C at size 0.025, which all four types
  meet (0.05–0.09 °C). At size 0.05 the linear types are 0.16–0.21 °C off; the test only
  requires the coarse result to be within 1 °C.

## Q12 — `api.solve` and the results file (Data §9, §11) — raised in M3.11

1. **`api.solve(model, mesh)` has no built geometry**, but selections are resolved against
   one. **Done for now:** `solve` takes an optional keyword `built=`. With it, the model is
   validated first and selections are resolved by fingerprint. Without it, the tags stored
   in the selections are used as they are; `api.build` refreshes them, so the Data §11
   script works. A model whose geometry was edited without rebuilding would then use old
   tags unnoticed — pass `built=` to be safe.
2. **Where the results go.** A `Model` does not know its file name, so "beside the model"
   cannot be the default. **Done for now:** `solve(..., path=…)`; by default a file named
   after the model in the system temporary folder. `api.results_path(model_path)` gives
   `<model>.tfea.h5`.
3. **Additions to the file layout**, needed to read results without gmsh: `/meta` also
   holds `regions` (region id → material, thickness, angle) so that flux can be recovered;
   `/mesh` also holds `axisymmetric`, `point_nodes` and `node_sets`; `/reactions/<i>` is
   keyed by index with the BC name in an attribute (names may contain `/`).
4. **Energy columns** of `/steps/energy`: `heat_in, heat_out, net, stored_rate, imbalance,
   relative_imbalance`.

Also: total loads (`HeatPower`, `HeatFlow`) and `FixedTemperature` refuse a function that
depends on T (a total, or a prescribed value, as a function of the local temperature has
no defined meaning); the error message says what to use instead.
