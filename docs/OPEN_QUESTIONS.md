# Open questions

Questions and decisions that the plan documents do not settle (Plan §4 rules 2, 3, 6, 9, 11).
Each entry says what was done in the meantime, so a reviewer can confirm or overrule it.

## Pending human checks

Work that is finished but still needs a person to look at it. Until then the task box in
`docs/tasks.md` stays unticked.

- _None open._ M5.G (plots for V-10 and V-17) was reviewed by the owner on 2026-11-16:
  the images, the animation and the CSV files look fine. More testing of the
  visualisation with a wider range of boundary conditions is planned by the owner after
  the build is complete. MP4 export is tested since 2026-11-23, when ffmpeg was installed
  on the development machine (`test_mp4_is_written_with_ffmpeg`).

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
   **Settled 2026-11-23:** [I] Eq. 9.29 defines L = A_s/P, which is half the selection
   length in a 2D model (Theory §8; Q30). Task M11.38.
3. **Dittus–Boelter as the "optional user selection"** for ducts: it replaces Gnielinski as
   the turbulent formula; the laminar value and the linear transition between Re = 2300 and
   4000 are kept. Its stated range (Re ≥ 1e4) is not enforced in the transition region.
   *Since M11.38 its [I] range (0.6 ≤ Pr ≤ 160, Re ≥ 1e4) is checked where it is used,
   at Re ≥ 4000; still not in the transition region.*
4. **Validity range of `duct_internal`.** The table leaves it blank; the Gnielinski range
   of §8.1 is used (0.5 ≤ Pr ≤ 2000, Re ≤ 5e6).
5. **`duct_internal` is not offered as a boundary condition**; internal flow belongs to
   streams (M7). Using it in a `CorrelationConvection` raises a clear error.
6. **Sources.** `CorrelationInfo.source` holds only the names the theory document gives
   (Churchill–Bernstein, Churchill–Chu, Gnielinski, Dittus–Boelter) and otherwise
   "docs/theory.md §8". Textbook citations are left for the human check of M11.1.
   *Done in M11.38: every source cites [I] with its equation numbers (Theory §8).*
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
9. **Through-plane streams (M7.2) count as a temperature reference in validation.** Data §8
   lists "fixed T, convection, radiation or an in-plane stream". A through-plane stream is
   convection to its bulk temperature, so it fixes the temperature level just as a
   convection condition does; without this a plate cooled only by a through-plane stream
   was rejected. They are refused in axisymmetric models (Theory §9.1 defines them for
   planar models), need a mass flow only when no `h_override` is given, and are linear
   unless Dittus–Boelter is selected (its exponent depends on the wall temperature).

## Q19 — network hydraulics (Theory §9.2) — raised in M7.3

1. **Convergence measure.** Theory: iterate "until the largest relative change in any ṁ
   < 1e-6". With prescribed pressures the branch-law flow does not depend on the
   linearisation coefficient c, so its change alone reached 1e-6 while the reported
   (linearised) flows were still about 20 % off; with prescribed inflows the linearised
   flow is constant, which fails the other way. **Done for now:** the change is the larger
   of (a) the change of the linearised flow between successive solves and (b) the
   difference between the branch-law flow and the linearised flow. This is stricter than
   the text and is what makes V-30 and V-31 pass (errors about 2e-6 against 1e-5; that
   margin is the convergence tolerance itself).
2. **Reported flows** are the linearised ones of the final solve, ṁ = c (p_i − p_j), so
   mass is conserved at every node to solver precision. Friction factor and Reynolds
   number are reported at those flows.
3. **Friction update** uses the Reynolds number of the previous solve's flow; a branch
   with zero flow uses Re = 1000 (the starting assumption) to avoid a division by zero.
4. **Every branch needs a stream**, which supplies its area, hydraulic diameter, roughness
   and fluid; a "loss" branch uses K_minor alone as its resistance. A branch without a
   stream has no area and is refused.
5. **Typical cost:** 25–55 iterations with the prescribed under-relaxation of 0.5; the cap
   is 200.

## Q20 — coupling of streams, network and solid (Theory §9, Data §9, §13) — raised in M7.4

None of these blocks the build; each is a choice the documents leave open. Please confirm.

1. **How the drivers reach the provider.** Data §13 gives `FlowProvider` four methods but
   not where they are called. **Done for now:** `CompiledProblem.providers` (a list);
   `solver/steady.py: assemble` calls `provider.update(state)` before every assembly (so at
   most once per nonlinear iteration), and the run layer calls `provider.results(state)`
   for each stored step. Two optional methods are used when a provider has them:
   `initialize(u, t0)` (start values of its extra DOFs) and `static()` (step-independent
   data for the results file).
   **Corrected in M11.33 (2026-11-23), after M11.20:** the providers are updated once per Newton iterate (and once at the start), never inside line-search trials or the jump probes (Theory §9.2).
2. **Initial fluid temperatures of a transient.** The fluid is quasi-steady and has no
   initial condition. **Done for now:** the fluid nodes start at the values that satisfy
   the fluid energy equation for the initial wall temperatures (marched from the inlet).
3. **A stream named by several branches.** `NetBranch.stream` supplies the flow area, so a
   loss element must name a stream too. **Done for now:** a stream takes the flow of its
   one duct branch (or of its only branch); two duct branches naming one stream is an
   error. Every branch uses the mean temperature of its stream; for a through-plane
   stream that is its bulk temperature.
4. **Reversed flow.** A network solution that drives a stream against its path is refused
   with a `ModelError` (the cell scheme of §9.1 has a fixed inlet).
5. **Enthalpy term.** The heat flow reported for an in-plane stream is
   `ṁ c_p (T_in − T_out)` (heat brought into solid + fluid; negative when the stream cools
   the body), with the one `c_p` of Q18. The inlet constraint reports no heat flow.
6. **Results file.** `/fluid/<i>` is keyed by index with the stream name in an attribute
   (as `/reactions`), holds `mode`, and per step also `T_in`, `T_out` and `heat` besides
   the `mass_flow, h_mean, Re, dp` of Data §9 (the M7.5 summary table needs them). For a
   stream that is not on a network, `dp` is the §8.1 friction drop over the path length
   with the Churchill factor at the mean Reynolds number; for a through-plane stream off
   a network it is NaN (no length is known).
7. **V-29** tightens the nonlinear tolerance (`rtol = 1e-10`) in its example, so that the
   iteration error lies below the 1e-8 of the case; the scheme itself conserves to
   round-off (errors of about 1e-13 are seen).
8. **Symmetry.** Checked: `symmetric` is only an ordering hint to the linear solver
   (`solver/linear.py`); nothing else assumes a symmetric matrix.

## Q21 — GUI choices that the documents leave open — raised in M8.1 – M8.3

None of these blocks the build. Please confirm, or say what to change.

1. **Document staleness (M8.2).** What an edit invalidates is decided by comparing the
   model JSON before and after: a change of `geometry` makes geometry, mesh and results
   stale; of `mesh_settings`, `analysis` or a selection used by the mesh settings, mesh
   and results; anything else, results only. Selection tags and the selection `all` are
   treated as caches of the build, not as edits (a rebuild is not an undo step).
2. **Nodes and elements in `selection_changed(dim, tags)` (M8.3, Data §13).** The
   interface has only `dim` and `tags`. **Done for now:** two reserved pseudo-dimensions,
   `scene.NODE_DIM = -1` (tags are node indices) and `scene.ELEMENT_DIM = -2` (tags are
   element ids).
3. **Additions to the viewport beyond Data §13:** a signal `coordinates_changed(x, y)`
   for the status bar; `FieldDisplay` and `LoadSymbol` are defined in `gui/scene.py`
   (fields listed in their docstrings). The `SceneView` methods are as written.
4. **Picking rules:** 8-pixel tolerance; a left drag longer than 4 pixels is a box
   selection (curves must lie wholly inside, surfaces by bounding box, elements by
   centroid); click replaces, Ctrl-click toggles, a click on nothing clears; changing the
   selection mode clears the selection.
5. **Matplotlib in the GUI:** the layer test holds an allow-list (`gui/viewport_mpl.py`
   now); chart modules are added to it as they are written (Plan §7 rule 8 allows charts).
6. **`FormSpec` (M8.4, Data §13 names it but does not define it).** **Done for now:**
   `core/forms.py` (no Qt): `FieldSpec(name, label, kind, quantity, minimum, maximum,
   choices, optional, tooltip, selection_dims)` and `FormSpec(title, fields, category,
   description)`; a class registered without a form gets one derived from its dataclass
   fields. The built-in forms are in `model/bc_forms.py`.
7. **No velocity quantity in `core/units.py`:** the velocity of a correlation convection
   is shown in m/s without conversion. Say if a velocity unit choice is wanted.
8. **Pasting a table:** lines are split at tabs, else semicolons, else commas, else
   blanks; with tabs or semicolons a comma inside a number is a decimal comma; a
   non-numeric first line is skipped as a header.
9. **Tree actions so far:** loads can be added, renamed, duplicated, suppressed and
   deleted; materials, streams and enclosures renamed, duplicated and deleted (their
   "add" comes with M8.6 and M8.12); `name` and `active` are edited in the tree, not in
   the form.
10. **Geometry tools (M8.5).** Booleans on the viewport selection: the earliest selected
    shape (in history order) is the object, the others are the tools. A selected entity
    is mapped to the latest operation that owns it. Angles are entered in radians (there
    is no angle quantity in `core/units.py`); lengths are in metres. A failed rebuild
    keeps the old geometry, marks it stale and reports the error; undo recovers. An
    operation that later operations refer to cannot be deleted. The rebuild runs in the
    GUI thread for now, behind one method, until the worker of M8.9 exists.

11. **Solve and worker threads (M8.9).** The solve runs in a background thread on its
    own copy of the model. If the model was edited meanwhile, the results are stored but
    marked out of date; if the mesh or the build was replaced, they are discarded (the
    file stays on disk). Cancel keeps the steps written so far. After a successful solve
    the progress dialog stays open ("Finished") so the residual chart can be read.
    Build and mesh run on one dedicated long-lived thread in the application (all gmsh
    calls on a single thread; tried in three arrangements without a hang); a mesh made
    from settings that changed meanwhile is discarded. `theta` is checked by the model,
    not by a limit in the form.

12. **Result display, charts, export and flow panels (M8.10 – M8.12).** Result objects
    (contours, vector plots) are view state: not stored in the model file, not on the
    undo stack. One object is displayed at a time. GIF export runs in the GUI thread, so
    the window does not respond while a long animation is written. Open charts are
    marked "(out of date)" when new results arrive; they are not redrawn. A new stream
    copies the first existing stream, or asks for its required values in a dialog.
    **Known limitation:** the probe, the chart path pick and the stream "pick path
    points" toggle all listen to viewport clicks; the probe and the chart path pick
    exclude each other, but the stream toggle does not switch the others off, and it
    leaves the selection mode at "none" when turned off.

## Q22 — thermal contact (Theory §11, task M10.1) — raised in M10.1

By the owner's instruction of 2026-11-16, M10.1 was done ahead of M9 (enclosure radiation)
and M10.2 (phase change), which are on hold. None of the points below blocks the build.

1. **When the mesh is opened.** The task calls node duplication a "mesh post-processing
   step" without saying where it runs. **Done for now:** in `solver/compile.py`, on the
   plain mesh (`core/contact_split.py`), not in the mesher. The mesh the user holds is
   unchanged; the compiled problem and the results file hold the opened mesh. Original
   nodes keep their numbers and the new nodes are appended, so node numbers picked on
   the original mesh stay valid in the results. Adding or changing a contact therefore
   makes only the results out of date, not the mesh.
2. **The duplication rule, generalised.** The task gives two rules (the higher region id
   gets the new nodes; an end point is duplicated only on the outer boundary). **Done for
   now:** around each node of a contact facet the elements are grouped — two elements
   are in one group when they share a side through the node that is not a contact facet
   — each group gets its own copy, and the group with the lowest region id keeps the
   original. This gives both rules of the task, and also defines what happens where
   several contact curves meet (one copy per region) and where a contact ends inside the
   body or continues as a bonded interface (no duplication there).
3. **Conductance that depends on temperature** is refused: Theory §11 does not say which
   side's temperature would be used. A function of time and position is accepted.
4. **Geometry factor** (thickness, or 2πr) is taken on the side of the lower region id.
   Two regions of different thickness meeting at a contact are not treated specially.
5. **Node sets and geometry points** keep the original nodes, which lie on the side of
   the lower region id. A fixed temperature on a geometry *point* at the end of a contact
   curve therefore fixes that side only; on a boundary *curve* it fixes each side's own
   nodes, as expected.
   **Changed by M11.36 (2026-11-23, owner's decision D12.6):** a fixed temperature on a
   geometry point fixes every copy of its node, so a point at the end of a contact curve
   fixes both sides. Other point loads are unchanged.
6. **Reported heat.** The heat crossing a contact is internal to the body, so it is not
   in the energy balance; the term reports it as `contact_heat:<name>` (from the lower
   to the higher region id) [W].

7. **GUI.** The model tree has an eleventh top-level node, "Contacts", after "Loads &
   Boundary Conditions" (the M8 list of nodes does not mention contacts); the expected
   list in `tests/gui/test_tree.py` was extended by that one entry. A new contact starts
   with an empty selection and a conductance of 0 (the neutral default; no number is
   invented), which the user must set. The panel refuses a temperature-dependent
   conductance. Contact curves are drawn as load symbols of kind "contact". The V-35
   model is in File > Examples.

## Q23 — DXF import (task M10.3) — raised in M10.3

The task text is one sentence; these choices fill it in. None blocks anything.

1. **Join tolerance.** The task says "within tolerance" without a value. **Done for now:**
   end points closer than `JOIN_TOL = 1e-6` times the largest in-plane extent of the
   drawing are one point (the same fraction as `importers.PLANE_TOL`). Not settable from
   the model or the GUI.
2. **What is ignored and what is refused.** Entity types other than the five named ones
   (including ELLIPSE, old-style POLYLINE, HATCH, INSERT/blocks, TEXT) are ignored with
   one warning. Chains that do not close are ignored with a warning; a drawing with no
   closed outline, a point where more than two segment ends meet, and anything out of the
   plane z = 0 are errors.
3. **Nesting.** A loop inside an even number of other loops is a surface, the loops one
   level deeper are its holes, so an island inside a hole is a surface again. Loops are
   assumed not to cross; crossing loops are not detected.
4. **Units.** The `$INSUNITS` header of the file is not read; the `scale` of `ImportFile`
   is the only conversion, as for STEP and BREP.
5. **Curve counts.** Arcs are split into pieces of at most 120 degrees and a spline that
   closes on itself into two curves (an OpenCASCADE restriction), so a semicircle in the
   drawing is two curves of the model.
6. **Two existing assertions changed.** `test_importers.py` and
   `test_builder_primitives.py` asserted that DXF import is "not supported", the
   placeholder this task replaces; they now assert "file not found" for a missing `.dxf`.
7. **`ezdxf` was installed into the project venv** (`pip install ezdxf`, the declared
   extra `dxf`). Without it the DXF tests are skipped and the import raises an error that
   says how to install it.

## Q24 — unit systems (Data §7, task M10.4) — raised in M10.4

Data §7 names the temperature and length units and "a consistent derived set"; the task
names three presets. Everything else here is a choice. None blocks anything.

1. **One unit per quantity.** `UnitSettings` has a field for every quantity, each with a
   short list of units (`core/units.py: _TABLE`); a preset only fills them in, and any
   single one can be changed in Tools > Units.... All factors are computed from the exact
   definitions of the inch, foot, pound, International Table BTU and pound-force.
2. **The presets.** *SI (mm)*: mm, W/(mm K), W/(mm^2 K), W/mm^2, W/mm^3, kg/mm^3, MPa,
   mm/s, mm^2, degrees; power W, specific heat J/(kg K), time s, mass flow kg/s.
   *US customary*: degF, in, BTU/(h ft degF), BTU/(h ft^2 degF), BTU/(h ft^2),
   BTU/(h ft^3), BTU/h, lbm/ft^3, BTU/(lbm degF), s, lbm/s, psi, ft/s, in^2, degrees (the
   textbook units; lengths in inches but feet inside the heat-transfer units). The SI
   presets keep K or degC as it is. **To confirm with the owner.**
3. **New quantities** beyond the Data §7 list: `velocity`, `area`, `angle`.
4. **Expressions stay SI.** A function given as an expression is evaluated with t [s],
   x, y [m], T [K] and returns the SI unit whatever the display units; the function editor
   says so when a display unit is not SI. Constants and tables convert.
5. **Still SI only:** the parameters of a geometry `Transform` (label says so), the HTC
   calculator window, the solve-progress dialog and solver messages, the extra parameters
   of a correlation, CSV and VTU export, and the `api.summary` text. The `.tfea` and
   results files store SI, as before; no schema change (missing unit keys take the SI
   default).
6. **Units of a results display.** Results are shown in the units of the model stored in
   the results file until the units are changed in the session, after which they follow
   the document (`Results.display_units`, in memory only). So a model file whose units
   differ from those its results were solved with shows the results in the latter until
   Units is used once.
7. **Two existing assertions changed**, both of which asserted the limitation this task
   removes: `test_flow_forms.py` (flow area and wetted perimeter "have no quantity") and
   `test_material_forms.py` (the material angle has no quantity). They now assert the
   quantities `area`, `length` and `angle`.
8. **The chart CSV** writes the chart's own axis values and headings, so it follows the
   display units; the results CSV export stays SI.

## Q25 — restart of a transient run (task M10.6) — raised in M10.6

The task is one sentence ("continue a transient run from the last stored step to a later
end time, appending to the same results file"). These choices fill it in.

1. **How it is asked for.** `api.solve(..., path=..., restart=True)` (a new keyword with a
   default, so the Data §11 signature still works), `thermalfea solve model.tfea --restart`,
   and Solve > Continue transient run in the GUI. The end time is the one of the model:
   raise it, then continue. A cancelled run is continued the same way without raising it.
2. **What is the same as an uninterrupted run.** With a fixed step the continued run
   repeats the uninterrupted one to round-off in the linear case (tested at 1e-12, also
   with a stream at 1e-9) and to the iteration tolerance in the nonlinear case: Theory §6
   keeps g(T_n, t_n) from the previous step, and on a restart it is recomputed from the
   stored T_n, which is the same value up to the convergence of that step. The theta = 1
   start-up step is not repeated.
3. **Automatic stepping.** The controller's history is not stored. The continued run
   starts with the larger of the last two stored step sizes (the last one is usually cut
   short to land on the end time) and without an error estimate for its first step, as at
   the start of any run. Its steps therefore differ from those of an uninterrupted run
   within the time-stepping tolerance.
4. **What may change between the runs.** The restart compares the full mesh (nodes,
   element types, connectivity, element regions, boundary facets, planar or axisymmetric),
   the region data (material, thickness, material angle) and the streams (names, mode, DOF
   mapping) with the results file, and is refused if any differs, before anything is
   written; so is a file of a steady solution, a last step that did not converge, and an
   end time the file has already reached. Loads and settings are *not* compared: the
   continued steps use the current model, and the model embedded in the results file is
   replaced by it. A load changed between the runs takes effect
   from the restart time, without the theta = 1 step that a jump inside a run gets.
   **Decided by the owner on 2026-11-20 (Q28.1, task M11.11):** a changed material,
   thickness or material angle is refused; changed loads and settings are still allowed.
5. **File layout.** One addition to Data §9: the attribute `last_step` on `/steps` (the
   number of the time step of the last stored step), so that step numbers and "every
   n-th step" output carry on correctly when not every step is stored. No dataset was
   added and the schema version is unchanged; a file without the attribute counts its
   stored steps instead.
6. **The step at which a run was stopped stays in the file** even when the output rule of
   an uninterrupted run would not have stored it (the last step is always stored).

## Q26 — user guide (task M11.4, Plan §6 item 7) — raised in M11.4

1. **Where it is.** A MkDocs site (`mkdocs.yml`, sources in `guide/`, built-in
   `readthedocs` theme, no plugins beyond search). `mkdocs` was installed into the project
   venv and added as the optional dependency group `docs`.
2. **Sources of the correlations and the property tables are not in the guide.** Plan §6
   item 7 asks for the source of every correlation. The project documents record none
   (Q17.6 left the citations to M11.1), so the guide says "source not yet recorded; to be
   confirmed in the release check, task M11.1" for every correlation and for the material
   tables, and names only what the theory text names (Churchill-Bernstein, Churchill-Chu,
   Gnielinski, Dittus-Boelter, Churchill 1977). **This release criterion is not met until
   the owner does M11.1**; then add the references to `docs/theory.md` / the data files and
   regenerate.
3. **Tutorial inputs** (dimensions, temperatures, emissivity 0.8, flow rates) are example
   values chosen for the tutorials; materials, fluid properties and correlations are the
   built-in ones. The GUI steps of tutorials 2 and 3 are exercised by offscreen tests that
   drive the same dialogs and panels, but no tutorial has been followed on a real screen
   (as M8.G).
4. **Defects met while writing the guide, not fixed here** (each is stated in the guide
   where it matters): (a) the window has no control to make a model axisymmetric — only
   the examples and the API can; (b) in the stream panel an unset mass flow is shown as
   "Constant 0" (`FormPanel._load` does not show `None`); (c) the HTC calculator window has
   no cross-section input, so it cannot reproduce the h of a non-circular stream; (d) a
   new correlation convection or radiation condition starts with an empty correlation and
   fluid, T_inf = 0 and emissivity 0; (e) the first time step suggested by Theory §6.1 can
   trigger the "may oscillate" warning for a uniform start (the fin tutorial sets 1 s);
   (f) a steady solve is reported as "t = 0 s".
5. **One defect fixed with this task.** A model with an enclosure (M9, on hold) or with a
   region whose material has a phase change (M10.2, on hold) used to solve with that part
   silently left out. Validation now reports the error `not-implemented` and the compiler
   refuses such a model. When M9 or M10.2 is built, remove the corresponding entry of
   `model/validate.py: not_implemented`.
6. **Fixes planned** as tasks M11.7–M11.10 (added 2026-11-17); the owner's choices are in
   Q27.

## Q27 — fixing the defects of Q26.4 (tasks M11.7–M11.10) — raised 2026-11-17

The owner decided on 2026-11-17 (not built yet):

1. **Axisymmetric control (M11.7):** in the Analysis Settings panel, not in File > New.
2. **New loads (M11.9):** both. A dialog asks for the correlation, the fluid, the ambient
   temperature and the emissivity when the load is added, and validation catches blank or
   zero values in models from files and scripts. No default value is invented.
3. **First time step (M11.10):** option (ii), keep the suggestion Δt₀ = h_min²/(4 α_max)
   and do not log the oscillation warning for a step the program suggested itself. The
   cause: the suggestion uses the smallest edge and the largest diffusivity of the whole
   model, while the warning tests h² ρc/(6k) per element, so on a graded mesh or with mixed
   materials the suggestion fails the test in most elements. Proposed sentence for Theory
   §6.1, after "Oscillation warning: ...", **to be confirmed by the owner before M11.10 is
   built**: "The warning is not logged when Δt is the suggested initial step Δt₀; it
   applies to a step set by the user and to steps chosen by the step control."
   Still open for the owner: whether a later step chosen by the automatic step control
   should be warned about (the proposed sentence says yes, as now).
   **Settled 2026-11-22 (Q29.15).** The warning is in fact checked only once, before the
   first step (Q15.7), so the sentence above would have added warnings. The owner chose
   instead: "The warning is checked once, for the first step, and is not logged when that
   step is the suggested Δt₀."

## Q28 — code-review findings of 2026-11-20 (tasks M11.11–M11.16) — raised 2026-11-20

`REVIEW.md` lists nine findings, each reproduced by the reviewer. The cause named in each
was confirmed in the code. All nine are code defects. None needs a new equation, property
or benchmark target.

1. **Restart compatibility (M11.11; findings 2, 3, 4).** The owner decided on 2026-11-20 to
   **refuse a restart when any region's material, thickness or material angle has
   changed**. Loads and solver settings may still change between the runs, as Q25.4 says.
   This settles the point Q25.4 left open, and the results-file layout (Data §9) is
   unchanged. The restart check also compares the whole mesh (element types,
   connectivity, element regions, boundary facets, planar or axisymmetric), not only the
   node coordinates. It also compares the streams of the model with those of the file
   (names and DOF mapping). Every check is made before anything is written to the file.
2. **Input guards (M11.12; findings 1, 8).** The command line refuses an output path that
   is the model file itself. Validation reports an error for a largest time step that is
   not positive or is below the smallest step, and for a first time step that is not
   positive.
3. **Mesh out of date (M11.13; finding 5).** An edit to a selection that is named in
   `structured_surfaces` or in a refinement's `selection` marks the mesh out of date.
4. **Path locator (M11.14; finding 6).** A point that is not inside any of the nearest
   candidate elements is searched for among all elements whose bounding box holds it,
   before it is reported as outside the mesh.
5. **Position-dependent temperatures in validation (M11.15; finding 7).** A
   position-dependent prescribed or ambient temperature is evaluated at the points of
   the entities it applies to, not at the origin. When that is not possible it is
   treated as unknown, as a temperature-dependent value is now, so it never blocks a
   solve.
6. **Early output times (M11.16; finding 9).** The step controller compares a mandatory
   time with the current time using a tolerance relative to the local time, not to the
   length of the whole run. Distinct output times that can be represented are kept.

## Q29 — external codebase review of 2026-11-21 (tasks M11.17–M11.30) — raised 2026-11-22

`REVIEW-2.md` is an external review of commit 353a3ca. Every claim was checked against
the code; the verdicts and the plan are in `docs/review-2026-11-21-evaluation.md`. On
2026-11-22 the owner asked for the clear-cut defects, which need no decision, to be fixed
first: M11.20, M11.24, M11.22, M11.21, M11.25 and M11.18 (without item 2.1-3).

**The owner decided D1–D13 on 2026-11-22**, through `docs/owner-review.html`, after an
independent check of `TODO.md` by a Codex agent. The options are in `TODO.md` (as of
commit 314093c) and in the evaluation, §4.

1. **D1, Theory §5 convergence at equilibrium (M11.17): option (c).** Keep the relative
   test ‖r‖ ≤ rtol · F_ref and `ttol`. Also accept an iterate when ‖r‖ on the free rows is
   at most N · ε · (‖|K|·|T|‖ + ‖F‖ + ‖r_extra‖), the same free-row norms, where ε is the
   machine precision. This applies to steady and transient solves. **N = 100** (owner,
   2026-11-22).
   **Built in M11.17 (2026-11-23)** as a floor on the residual allowance,
   ‖r_f‖ ≤ max(rtol · F_ref, floor), with `ttol` still required, as option (c) read in
   `TODO.md` ("keep the physical relative test and ttol, and add a round-off floor").
   Radiation to 300 K started at 300 K now converges in one iteration (steady and
   transient). The M3.7 test that an exact but large first step needs a second, confirming
   iteration is unchanged.
2. **D2, fluid rows with θ < 1 (M11.31): option (a).**
   - Rows without capacitance (the stream fluid rows) are always stepped with θ = 1,
     whatever θ the solid uses, in both the linear and the Newton paths.
   - On a restart the fluid nodes are first re-solved for the stored wall temperatures
     and the current data, and g(n) is then rebuilt.

   **Built in M11.31 (2026-11-23)**, written into Theory §6 and §9.1:
   - A row without capacitance is one whose row of C is all zero. Its θ is 1 in the
     residual, the tangent and the reactions of the step energy balance.
   - The ρc of the solid is still evaluated at T_θ with the solid's θ.
   - The loads of the energy balance keep the θ weighting. A fluid row that is converged
     at both ends of a step has g_r = 0, so the balance closes. On a restart, the start
     heats are taken from the re-solved state.
   - Reproduced on a plate with a linear stream (h given) at θ = 0.5, restarted with a
     fifth of the mass flow: before, the outlet alternated by about ±0.3 K a step; now it
     rises smoothly.
3. **D3, Theory §6.1 error estimate (M11.19): yes, as recommended.**
   - The prescribed DOFs are left out of the error estimate and out of
     `max_dT_per_step`; a model with no free DOF is handled.
   - The predictor history restarts on the outgoing side of a physical breakpoint, not of
     an output time.
   - A change limit on the free solid temperatures is kept for the first step after the
     restart.
   - The `_jumps` defects are fixed.

   **Built in M11.19 (2026-11-23)**, written into Theory §6 and §6.1. Readings, none of
   which needs a new constant:
   - **Physical breakpoint:** a breakpoint of a load or prescribed-temperature table, or
     a time at which a jump is found. A jump in an expression with no breakpoint is
     looked for only when θ < 1, as before; doing it on every θ = 1 step would cost four
     more assemblies a step.
   - **Change limit on the first step:** the predictor T_pred = T_n with the same
     threshold 4·tol·max(T_range, 1 K), taken over the free DOFs that have capacitance
     (the fluid rows of a stream have none).
   - **No first-step limit at the start of a run:** the first step of a run still skips
     the error test, as before.
   - **Jump test:** a jump is now a local test on each side of t_n (Theory §6). It uses
     the existing constants 10⁻⁸, 10⁻³ and 10⁻⁶.
4. **D4, network near Δp = 0 (M11.32): option (a).** Raise a clear error naming the worst
   branch, its Δp, both flow estimates and the largest continuity residual. No change to
   the iteration of Theory §9.2.
   **Built in M11.32 (2026-11-23).** The worst branch is the one with the largest relative
   change in the last iteration. The two estimates are the flow of the nodal solve and the
   flow of the branch's pressure-drop law. The continuity residual is that of the
   branch-law flows at the free nodes; the nodal-solve flows meet continuity exactly.
5. **D5, inclined natural convection (M11.23).**
   - A non-finite angle or |θ| > 90° is refused before evaluation, pointing to the
     horizontal-plate correlations.
   - The validity range stays one-sided, as written in Theory §8 (θ ≤ 60°).
6. **D6, term results in the results file (M11.28): yes.**
   - `Term.results()` (contact heat, h_mean of correlation loads) goes in new groups.
   - The schema version is raised.
   - The window shows the values.
   - The pump example reads them.
7. **D7 (M11.23): yes.** `Function` gets a read-only `depends_on_position` (Data §1), and
   a total load (`HeatPower`, `HeatFlow`) refuses a position-dependent function.
8. **D8 (M11.23): yes.** `api.solve` without `built` runs the checks that need only the
   model.
9. **D9, documents (M11.33): all as recommended.**
   - Theory §7 becomes "positive into the body", with the sign of its four boundary
     formulas reversed.
   - The Q11 imbalance scale is confirmed.
   - Data §8 and §9 are brought up to date.
   - Theory §6.1 says the suggested Δt₀ is "logged (shown in the Messages panel)".
   - Q20.1 and `docs/handover.md` are corrected for M11.20.
10. **D10, packaging (M11.30).**
    - Licence: **MIT**.
    - pandas moves to an optional extra `examples`.
    - Both copies of the showcase images are kept.
    - A short root `README.md` is written.
11. **D11, air at 1 atm or 1 bar, the water table:** still part of M11.1. Checked on 2026-11-23
    (`docs/property-verification.md`):
    - the air densities are those of 1 bar;
    - the 5-row water table is off by up to 5.1 % in μ between rows;
    - Incropera's β at 360 K looks like a misprint;
    - 6061-T6, Ti-6Al-4V and FR-4 have no source found.

    The choices are listed in the report's §5.
12. **D12, design choices.**
    - Kept as now:
      - one Dittus–Boelter heating flag per stream;
      - no duct validity warnings in the stream solver;
      - no bounding box in selection matching;
      - duplicate fingerprint matches left as now;
      - the run-layer tolerances confirmed;
      - no embedding of free points or curves (Q5).
    - **To build:**
      - transforms move the shape's points with `copy=False`, and points and curves can
        be transformed and used by a Line (M11.34);
      - user fluids become usable through `library.fluid()` (M11.35);
      - a fixed temperature on a point at the end of a contact curve fixes both sides
        (M11.36; changes Q22.5).
    - **Built in M11.34 (2026-11-23):**
      - gmsh keeps the tags of a moved surface and its curves, but may renumber the points.
        The builder follows each owned point with a probe point moved alongside it, and
        each curve by its moved end points.
      - The kind of a Transform follows its targets (Data §4).
      - Not handled: moving a point that an earlier Line already uses.
      - The M2-gate test that asserted the old release of the boundary ops now asserts that
        they follow the shape.
    - **Built in M11.35 (2026-11-23):** `library.fluid` looks in the built-in fluids first,
      then in the user library (re-read when the file changes). A user fluid with a
      built-in name is not used and is reported once. The GUI fluid lists use
      `library.fluid_names()`.
    - The "Pick in viewport" start mode is checked in M8.G.
13. **D13, scope:** excluded, and the `thermalfea export` line is dropped from PLAN.md
    (M11.33).
14. **Result objects on a new model (M11.25, settled 2026-11-22).** The owner confirmed
    that New, Open and Examples clear the result objects and probes; the M8.10 test
    `test_results_cleared_clears_the_display` now requires this.
15. **Other answers of 2026-11-22.**
    - **Q27.3:** wording (i) for Theory §6.1, built in M11.10: "The warning is checked
      once, for the first step, and is not logged when that step is the suggested Δt₀."
    - **Release scope (Plan §6 item 1):** version 1 excludes the held features (M9
      enclosure radiation, M10.2 phase change) and their verification cases (V-22a–d,
      V-23, V-24, V-36); the guide's limitations say so.
    - **Holds released:** M10.5, M11.7, M11.8, M11.9, M11.10. Still on hold: M9, M10.2 and
      scripting features.
    - **Order:** the default order of `TODO.md` §3.3, then the newly unblocked tasks.
    - **3D:** not yet.
    - **Confirmed as documented:** Q1, Q14, Q18.2, Q20.2–8, Q21, Q22 (except 22.5, see
      D12), Q23.1–5, Q24, Q25, Q26.1 and 26.3, and all earlier interim choices (Q2, Q4,
      Q6–Q10, Q12, Q13, Q15, Q16, Q19).
    - **Still open:** Q17.2 (with M11.1). *Settled 2026-11-23 by [I] Eq. 9.29 and
      Example 9.3: L = A_s/P, half the selection length (Theory §8, Q30).*
    - **Guide publishing** stays manual; GIF is enough (no ffmpeg).

## Q30 — properties and correlations from the reference text (M11.37–M11.42) — raised 2026-11-23

The owner's decisions of 2026-11-23, on `docs/property-verification.md`:
- **Air** is labelled 1 bar, and uses every row of [I] Table A.4.
- **Water** uses NIST rows every 5 K, and β from NIST.
- **Solids:** only materials in [I], with every material it gives added; 6061-T6,
  Ti-6Al-4V and FR-4 are removed.
- **Correlations:** those of [I], plus the useful ones not yet applied.
- **The PDF** of [I] is kept in `docs/`, git-ignored.

These are written into Data §6 and Theory §8. The remaining points:

1. **Oxygen at 1300 K** ([I] Table A.4, p. 999). μ·10⁷ is printed as 588.4. The same row's
   ν·10⁶ = 188.6 gives 558.4. The steps from the rows below are +27.0, then +55.9 (they would
   be +25.9 with 558.4). Very likely a misprint. **Kept as printed** (owner, 2026-11-23).
2. **Helium and water vapour are at 1 atm, the other gases at 1 bar.** A CoolProp check of
   every A.4 density gives a match to 0.05 % for one pressure or the other. Each entry's note
   says which.
3. **Water starts at 280 K.** NIST gives β < 0 below 277 K, where water is densest. A
   negative β makes Ra negative, and the natural-convection formulas take fractional powers
   of Ra. Below 280 K the end row is used, with the usual warning.
4. **Three seeds for later decisions**, recorded in Theory §8.2:
   - **(a)** Enclosure correlations ([I] 9.49–9.63) would need a load that couples two
     surfaces across a cavity.
   - **(b)** Mixed convection (9.64) would need a load that names a forced and a natural
     correlation.
   - **(c)** The laminar f·Re of non-circular ducts (Table 8.1) would need a rule for joining
     it to Churchill's turbulent branch.

   **Declined** (owner, 2026-11-23): the current correlations are adequate for now; none of
   the three is to be built.
5. **Names.** The seven materials that stay keep their library names. The others use the
   book's wording ("group, row").
6. **Linear interpolation in the annulus table** (Theory §8.1) is the program's rule. Nu_i
   changes quickly between D_i/D_o = 0.05 and 0.10 (17.46 to 11.56), so values between rows
   are approximate there.

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
