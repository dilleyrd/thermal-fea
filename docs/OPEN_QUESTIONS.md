# Open questions

Questions and decisions that the plan documents do not settle (Plan §4 rules 2, 3, 6, 9, 11).
Each entry says what was done in the meantime, so a reviewer can confirm or overrule it.

## Pending human checks

Work that is finished but still needs a person to look at it. Until then the task box in
`docs/tasks.md` stays unticked.

- **M5.G — plots for V-10 and V-17 (pending since 2026-11-15).** The gate asks for a human
  to look at every plot type. The owner reviewed what could be seen remotely and will
  check the rest at their desk. By their instruction the build continued past this gate
  with M6. To review: run `.venv\Scripts\python.exe examples\m5_gallery.py`, which writes
  19 plots, an animation, CSV and VTU files and two text summaries to
  `examples/output/m5_gallery`. Points already noted for judgement: arrows near the
  singular corner of V-10 overshoot the model outline in the vector plot; the line at
  y = 0.2 in V-10 is the seam of the two rectangles used to put a node at the NAFEMS check
  point; V-17 is a 10:1 strip, so its contours are a narrow band. MP4 export is untested
  because ffmpeg is not installed. When the review is done: tick M5.G, set M5 to ☑ in
  `PLAN.md`, and remove this entry (or list the friction found).

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

## Q14 — which steps count as "discontinuity steps" (Theory §6) — raised in M4.2

Theory §6: "At a step where a prescribed temperature or a load jumps discontinuously, use
θ = 1 for that one step." It does not say how a jump is recognised.

**Done for now** (`solver/transient.py`):

1. **The first step**, when the initial state is not in equilibrium with the loads at the
   start time (‖g(T₀, t₀)‖ on the free DOFs is not negligible), or when an initial
   temperature differs from the prescribed value that replaces it. The loads are, in
   effect, switched on at t₀. *This matters:* without it V-21 cannot be met. On V-16 with
   θ = ½ the suddenly applied convection excites fast modes that Crank–Nicolson hardly
   damps; the resulting ringing (about 0.01 K) hides the O(Δt²) error and the observed
   order came out anywhere between 1.7 and 8.8. With θ = 1 on the first step the observed
   order is 1.99–2.00 for all four element types, and V-16 still passes at 1e-4.
2. **Later steps**, when the change of a prescribed value or of g over the first 1e-8 of
   the step exceeds 1e-3 of its change over the whole step (a continuous function changes
   by about 1e-8 of it, a jump at the start of the step by all of it). This costs two
   extra assemblies per step and is done only when θ < 1 and the problem depends on time.
   A jump that falls strictly inside a step is not seen; table breakpoints are mandatory
   times (M4.3), but a table is continuous anyway, and a jump written in an expression
   (`where(t > 5, …)`) is caught only if a step happens to start at it.

**To confirm:** that an out-of-equilibrium start should be treated as a discontinuity.

Also in M4.2: `solve_transient(problem, T0=None, on_step=None, *, t0=0, store=True)`
returns a `TransientResult`; `on_step(record)` receives a `StepRecord` per accepted step
and may return `False` to cancel. A fixed-step run takes its step from
`solution.initial_dt`.

## Q15 — details of the step controller that Theory §6.1 leaves open — raised in M4.3

1. **First step.** There is no predictor, so no error test; the step size is kept for the
   second step (factor 1).
2. **Error rejection at Δt_min.** Theory raises only for a Newton failure below Δt_min.
   When the error test fails but the step is already at Δt_min, the step is accepted with
   a logged warning rather than looping.
3. **After a step shortened for a mandatory time**, the next step returns to the size the
   controller wanted before shortening (if the shortened step was accurate), instead of
   growing back from the short step.
4. **`max_dT_per_step`.** A step whose largest nodal change exceeds the limit is rejected
   and redone with Δt · 0.9 · limit / change (at most Δt / 2); after an accepted step the
   next Δt is capped at Δt · limit / change.
5. **Fixed stepping** (`auto_timestep = False`) also lands on the mandatory times; it does
   no error control, and a Newton failure raises at once.
6. **Mandatory times:** table breakpoints of every term and constraint, the output times
   when `output == "times"`, and the end time.
7. **Suggested Δt₀ and the oscillation test** use the shortest corner-to-corner element
   edge for h, the larger principal conductivity for k, and properties at the initial
   temperature. The oscillation warning is checked once, for the first step.

## Q16 — what a transient run stores, and its per-step energy balance — raised in M4.4

1. **Which steps are stored.** The initial state (step 0, with no energy balance) and the
   last step are always stored. In between: every step (`all`), every n-th step counted
   from the start (`every_n`), or the steps at `output_times` (`times`). A cancelled run
   also stores the last step it computed.
2. **Per-step energy balance.** The θ-method balances the stored-energy rate against the
   θ-weighted heat flows at the two ends of the step. The balance stored for a step uses
   the same weighting — each load contributes θ q(n+1) + (1 − θ) q(n), a fixed temperature
   the reaction (C ΔT/Δt − θ g(n+1) − (1 − θ) g(n)) at its nodes — so that it closes to the
   solver residual (below 1e-8 on linear cases). For θ = 1 this is simply the balance at
   the end of the step. A balance built from the end-of-step flows alone would show an
   O(Δt) imbalance for θ < 1 that is not a solver error.
3. **Progress callback.** Called after every accepted step, stored or not, with a
   `StepInfo` (step, time, Δt, iterations, converged, residual, end time). Only an explicit
   `False` cancels.

## Q17 — convection correlations as boundary conditions (Theory §8, Data §8) — raised in M6.2 / M6.3

1. **Inputs the class has no field for.** `inclined_natural` needs the inclination,
   `plate_forced_local` the leading-edge point and flow direction, `power_law` its C and n;
   `CorrelationConvection` has no fields for them. **Done for now:** one optional field
   `params: dict[str, float]` was added after `multiplier` (keys `theta_deg`; `x0, y0,
   dir_x, dir_y`; `C, n`). Existing fields are unchanged; older files load as before.
2. **Characteristic length of horizontal plates.** Theory §8 lists "area/perimeter"; task
   M6.3 says the automatic value for plates is the total length of the selection. In a 2D
   model of unit depth these differ (an infinitely deep strip of width L has
   area/perimeter = L/2). **Done for now:** the task text — the selection length — for all
   plate correlations; cylinders require `char_length`. An explicit `char_length` always
   overrides. **To confirm** which is intended for horizontal plates.
3. **Dittus–Boelter as the "optional user selection"** for ducts: it replaces Gnielinski as
   the turbulent formula; the laminar value and the linear transition between Re = 2300 and
   4000 are kept. Its stated range (Re ≥ 1e4) is not enforced in the transition region.
4. **Validity range of `duct_internal`.** The table leaves it blank; the Gnielinski range
   of §8.1 is used (0.5 ≤ Pr ≤ 2000, Re ≤ 5e6).
5. **`duct_internal` is not offered as a boundary condition**; internal flow belongs to
   streams (M7). Using it in a `CorrelationConvection` raises a clear error.
6. **Sources.** `CorrelationInfo.source` holds only the names the theory document gives
   (Churchill–Bernstein, Churchill–Chu, Gnielinski, Dittus–Boelter) and otherwise
   "docs/theory.md §8". Textbook citations are left for the human check of M11.1.
7. **"Lagged" wall temperature** is the current Newton iterate: the tangent carries no
   dh/dT, which is the lagging Theory §8 describes. No separate state is kept.
8. **"Once per BC per solve"** for validity warnings: once per compiled problem, since a
   problem is compiled for each solve.
9. **Ideal-gas β** is 1/T at the film temperature as given, even beyond the property table;
   the other properties are held at the table's end values, with one warning per fluid.

## Q18 — in-plane streams (Theory §9.1, Data §8) — raised in M7.1

1. **"Constant h override" (V-27).** The `Stream` class has no field for a given
   heat-transfer coefficient. **Done for now:** one optional field
   `h_override: Function | None = None` (a function of time only) was added. With it, and
   the single c_p below, the stream's rows are linear and a problem with such streams
   solves in one step.
2. **Which c_p.** Theory §9.1 names the temperature for the properties behind h (the
   cell's upstream fluid node) but not for the c_p in NTU = G / (ṁ c_p). **Done for now:**
   one c_p per stream, at its inlet temperature. V-27 ("the scheme is exact here", 1e-6
   for 1 and 20 cells) and V-29 (ṁ c_p (T_in − T_out) with a single c_p) only hold with a
   c_p that is the same in every cell. **To confirm.**
3. **Default cells.** "One per wall edge along the path": wall edges whose midpoints
   project to the same path coordinate (the two sides of a channel) share a cell; cell
   boundaries lie half-way between neighbouring edge midpoints.
4. **Edge midpoint** is the length-weighted mean of the edge's points; its path
   coordinate is that of the nearest point of the path polyline.
5. **Flow direction.** The mass flow must be positive; flow the other way needs the path
   reversed. Reverse flow from a network is not handled yet (M7.3 / M7.4).
6. **Wall condition for the laminar Nusselt number** is the constant-wall-temperature
   value (the stated default); the "wall hotter than fluid" flag of Dittus–Boelter is
   taken from the mean wall and mean fluid temperature of the stream.
7. **Assembly.** Theory suggests building a dense matrix per cell and scattering it. The
   same matrix is built with sparse products over all cells at once (no Python loop over
   cells); a test checks it against the scattered dense cell matrices.
8. Fluid DOFs are an extra group of the DOF map named `stream:<name>`; the inlet node is
   prescribed through a constraint, like a fixed temperature.

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
