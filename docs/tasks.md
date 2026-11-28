# Task list

Work top to bottom. Take the first unchecked task whose milestone dependencies are met
(Plan §5). Tier tags [A] [B] [C] are explained in Plan §4. "Accept" lists the tests that
must exist and pass before the box is ticked. Paths are relative to `src/thermalfea/`
unless they start with `tests/`.

Session prompt to use for each task:
> Read PLAN.md, then do the next unchecked task in docs/tasks.md, following PLAN.md §4.

Session prompt for an unattended run:
> Read PLAN.md, then work through docs/tasks.md in order following PLAN.md §4, including
> rule 11. After each task, tick its box, commit, push, and give a one-line status.

**Plan §7 (designing for future extension) applies to every task** and overrides any task
wording that conflicts with it. In particular: no literal 2 for the space dimension, no
`if etype == …` outside the element registry, boundary elements are `FacetBlock`s, DOFs go
through `DofMap`, and every physics contribution is a `Term` (Data §13).

---

## M0 — Scaffolding

- [x] **M0.1 [A] Project skeleton.** `git init` and add the `origin` remote if the folder
  is not yet a repository (ignore `.venv/` and `.deepeval/`); `pyproject.toml` (package `thermalfea`, src
  layout, Python ≥ 3.11; deps: numpy, scipy, gmsh, PySide6, matplotlib, h5py, meshio;
  extras `dev`: pytest, pytest-qt, ruff; extra `dxf`: ezdxf); console script
  `thermalfea = thermalfea.cli:main`; `.gitignore`; create every package directory from
  Plan §3 with an empty `__init__.py`; `scripts/check.ps1` running `ruff check` then
  `pytest -q`.
  Accept: `pip install -e .[dev]` succeeds; `python -c "import thermalfea"`; `scripts/check.ps1` exits 0.
- [x] **M0.2 [A] Errors, logging, layer test.** `core/errors.py` (Data §12);
  `tests/unit/test_layers.py` parses every source file with `ast` and fails if a module
  outside `geometry/`, `meshing/` imports `gmsh`, or a module outside `gui/` imports
  `PySide6` or `thermalfea.gui` (Plan §3 layer rules).
  Accept: the layer test passes, and fails when a forbidden import is added temporarily.
- [x] **M0.3 [A] `CLAUDE.md`.** Ten lines at most: point to `PLAN.md`, repeat Plan §4 rules
  1–6, give the check command.

## M1 — FE kernel

- [x] **M1.1 [A] Quadrature.** `core/quadrature.py: rule(etype) -> (points, weights)` for
  T3, T6, Q4, Q8, L2, L3 exactly as Theory §3.
  Accept: weights sum to the reference measure; each rule integrates monomials exactly up
  to its degree (T3 rule: 2, Dunavant: 4, 2×2: 3 per axis, 3×3: 5 per axis).
- [x] **M1.2 [A] Shape functions.** `core/elements.py: shape(etype, pts) -> N (n_pts, n)`,
  `dshape(etype, pts) -> dN (n_pts, dim, n)`, `node_coords(etype)`. Theory §3. Register
  each of the six types as an `ElementType` in `core/registry.py` (Data §13) including its
  quadrature (M1.1), facet type, local facet node indices and display simplices; all other
  code obtains element data only through `registry.element(name)`.
  Accept: ΣN = 1; ΣdN = 0; N_i at node j = δ_ij; dN matches central finite differences to
  1e-7; a dummy element registered inside a test is returned by the registry.
- [x] **M1.3 [A] Mesh classes and test-mesh generator.** `core/mesh.py` (Data §2) and
  `core/meshgen.py: rect_mesh(x0, y0, w, h, nx, ny, etype, region=1) -> Mesh` with facet
  blocks tagged entity 1 bottom, 2 right, 3 top, 4 left, plus `distort(mesh, amplitude, seed)`
  that perturbs interior nodes.
  Accept: `validate()` passes for all four types, distorted or not; a mesh with one element
  reversed fails validation.
- [x] **M1.4 [B] Element geometry kernel and conduction matrix.**
  `physics/kernel.py: geometry(block, nodes) -> ElemGeom` with fields `N (gp, n)`,
  `dNdx (e, gp, dim, n)`, `dV (e, gp)` = |J|·w, `xgp (e, gp, dim)`; the same for facets
  (`facet_geometry` → `N`, `dS`, `xgp`, with dS = √det(JᵀJ)·w, J being the dim × (dim−1)
  Jacobian — this reduces to the edge length factor in 2D).
  `gfactor(xgp, axisymmetric, thickness, dim)` (Theory §1; returns 1 when dim = 3).
  `physics/conduction.py: conduction(geom, D, g) -> Ke (e, n, n)` with `D` shaped
  `(e, gp, dim, dim)`, using `einsum`. Theory §2. Nothing in the kernel may assume dim = 2.
  Accept: rows of Ke sum to 0; Ke symmetric; for one unit-square Q4 with k = 1 equals the
  textbook matrix (diag 2/3, adjacent −1/6, opposite −1/3); axisymmetric T3 area integral
  of g reproduces the ring volume.
- [x] **M1.5 [A] DOF map and assembler.** `solver/dofs.py: DofMap` with named fields and
  extra groups exactly as Data §13;
  `solver/assembler.py: Assembler` collecting `(conn, Ke)` and `(conn, fe)` batches and
  producing CSR `K` and dense `F` (COO then `tocsr()`, duplicates summed).
  Accept: assembling two elements by hand gives the expected matrix.
- [x] **M1.6 [B] Linear solve with prescribed values.** `solver/linear.py:
  solve_partitioned(K, F, fixed_idx, fixed_val) -> T` (Theory §4) using `splu`;
  `Factorization` wrapper that can be cached and reused; singular or NaN → `SolverError`.
  Accept: 1D bar by hand; singular system raises.
- [x] **M1.7 [A] Functions.** `core/functions.py` (Data §1).
  Accept: table interpolation and both extrapolation modes; expression vectorised over
  arrays; `__import__('os')`, attribute access and unknown names all raise `ModelError`;
  dependency flags and breakpoints correct.
- [x] **M1.8 [A] Materials and libraries.** `materials/material.py`, `materials/library.py`,
  JSON data files with exactly the numbers in Data §6.
  Accept: every library entry loads; values equal the table in Data §6 (test reads both).
- [x] **M1.G [C] Gate.** Implement V-01 (temperature part) and V-33 with nodal values set
  directly on `rect_mesh` meshes. Implement V-37 (3D tetrahedron guard test). Review M1
  code for vectorisation, units in docstrings, and Plan §7 rules 1–4.

## M2 — Model, geometry, meshing

- [x] **M2.1 [A] Model dataclasses.** `model/model.py`, `bcs.py`, `settings.py`,
  `geometry_ops.py`, `selections.py` (classes only) — Data §3, §4, §5, §8, §10.
- [x] **M2.2 [B] Serialisation.** `model/serialize.py: to_json(model) -> dict`,
  `from_json(dict) -> Model`; every polymorphic class is written with a `"type"` tag;
  `schema_version` checked on load (newer → `ModelError`; older → run
  `model/migrations.py`, Data §13, which starts empty). Polymorphic classes are looked up
  through the registry (`register_bc` etc.), not a hard-coded list. `api.save/load`.
  Accept: a model that uses every class round-trips to an equal object; the JSON is stable
  (sorted keys, 2-space indent).
- [x] **M2.3 [B] Gmsh session.** `geometry/gmsh_session.py`: process-wide singleton guarded
  by a `threading.RLock`; `gmsh.initialize(interruptible=False)` (so it can run in a worker
  thread); terminal output off, messages redirected to `logging`; context manager
  `fresh_model(name)` that clears the previous model.
  Accept: two builds in a row, and one from a non-main thread, both work.
- [x] **M2.4 [B] Builder: primitives.** `geometry/builder.py: build(model) -> BuiltGeometry`
  for `Point, Line, Arc, Spline, Rectangle, Circle, Polygon, SurfaceFromCurves` with the
  OCC kernel. Keep a map op id → list of (dim, tag).
  Accept: areas from `occ.getMass` equal analytic values for each primitive.
- [x] **M2.5 [C] Builder: booleans, transforms, final fragment, fingerprints.** `Boolean`
  via `occ.fuse/cut/intersect`, `Transform`, `Delete`. After every OCC boolean, update the
  op-id map from the returned `outDimTagsMap`. After the last op: one `occ.fragment` of all
  surfaces, `synchronize`, then fill `BuiltGeometry` (surfaces, curves, points, each with
  `Fingerprint` from `occ.getCenterOfMass`, `occ.getMass`, `getBoundingBox`; curve→adjacent
  surfaces from `getAdjacencies`; 40-point display polyline per curve from `getValue`).
  Accept: plate with hole has area w·h − πr²; two touching rectangles yield 2 surfaces and
  exactly one shared curve; rebuild gives identical fingerprints.
- [x] **M2.6 [B] Selection resolution.** `selections.resolve` (Data §5) and API helpers
  `select_points/curves/surfaces(model, built, name, where=predicate | tags=[...])`.
  Accept: a selection survives adding an unrelated shape elsewhere; it becomes stale (with
  a clear message) when its curve is cut in two.
- [x] **M2.7 [B] Mesher.** `meshing/mesher.py: generate(model, built) -> Mesh`. Apply
  `MeshSettings`; set `Mesh.SecondOrderIncomplete = 1` (so quads are 8-node, not 9-node);
  quads by `setRecombine` on every surface; then extract: renumber node tags to 0-based
  dense indices, drop unused nodes, element types by the registry's `gmsh_type`
  (2→T3, 3→Q4, 9→T6, 16→Q8, 1→L2, 8→L3); elements of dimension `dim` become
  `ElementBlock`s, those of dimension dim − 1 become `FacetBlock`s; region id = surface
  tag; orient every edge so its parent element is on the
  left (Data §2); find `parent_elem` by matching the edge's end nodes against element
  sides. Any other element type → `MeshError`.
  Accept: for a plate with a hole and a two-region plate, all four element types:
  `validate()` passes; Σ element areas matches geometry (1e-3 linear, 1e-6 quadratic);
  Σ edge lengths on the outer rectangle = perimeter; every interface edge appears once.
- [x] **M2.8 [A] Size controls and structured meshing.** Curve/point sizes, transfinite
  curve divisions, transfinite surfaces (3- or 4-sided only; otherwise `MeshError`),
  distance/threshold refinement fields.
  Accept: a transfinite rectangle has exactly nx·ny quads; refinement gives smaller
  elements near the chosen curve than far from it.
- [x] **M2.9 [A] Mesh quality.** `meshing/quality.py: report(mesh) -> QualityReport`
  (per-element min angle, aspect ratio, min/max Jacobian ratio; counts; worst elements).
- [x] **M2.10 [A] STEP/BREP import.** `geometry/importers.py` via `occ.importShapes`; keep
  only surfaces lying in the z = 0 plane; anything else → `GeometryError` with explanation.
- [x] **M2.11 [A] API facade and `thermalfea info`.** Data §11 (`new_model`, `Geometry`
  helpers, `build`, `mesh`, `assign_region`); CLI prints entity, node and element counts.
- [x] **M2.G [C] Gate.** Script: L-bracket with a hole and an inset second material; save,
  load, rebuild, mesh; selections resolve identically. Review the builder's tag tracking.

## M3 — Loads, nonlinear steady solver, recovery

- [x] **M3.1 [B] Terms and problem compilation.** `solver/terms.py` (`State`, `Term`,
  Data §13). `solver/compile.py: compile(model, built, mesh) -> CompiledProblem`: builds the
  `DofMap` (field `"T"`), and one `Term` per contribution by calling the term factory
  registered for each BC class; each term's `setup` resolves its facet or element blocks
  and precomputes its `ElemGeom`. `is_linear` / `is_time_dependent` are the conjunction of
  the terms' flags (Theory §5 definition). Wrap M1.4 conduction as `ConductionTerm`.
  **All later physics tasks (M3.2–M3.6, M4.1, M6.3, M7, M9.3, M10.1) deliver `Term`s
  registered this way**; the drivers in M3.7 and M4.2 loop over `problem.terms` only.
- [x] **M3.2 [A] Body loads.** `physics/body_loads.py`: `HeatGeneration`, `HeatPower`
  (Theory §2). Function evaluated at integration points with `t, x, y, T`.
- [x] **M3.3 [A] Surface loads.** `physics/surface_loads.py`: `HeatFlux`, `HeatFlow`,
  `Convection` matrices and vectors (Theory §2).
  Accept: total applied heat equals q̄·area for planar and axisymmetric edges.
- [x] **M3.4 [A] Prescribed temperatures.** Collect nodes of `FixedTemperature` selections
  (curves and points) and evaluate `T(t, x, y)`; conflicting values at a shared node →
  the later BC in the list wins, with a logged warning.
- [x] **M3.5 [B] Temperature-dependent properties.** Evaluate k, k2, ρ, c at integration
  points from N·T_e; build D (Theory §2, orthotropic rotation).
  Accept: V-12 matrix check — constant D rotated by 90° swaps the roles of k1 and k2.
- [x] **M3.6 [B] Radiation to ambient.** `physics/radiation_ambient.py` residual and
  tangent (Theory §5).
  Accept: tangent matches a finite-difference derivative of the residual to 1e-5 relative.
- [x] **M3.7 [C] Nonlinear steady driver.** `solver/nonlinear.py: newton(assemble_fn, T0,
  fixed, settings) -> NewtonResult` implementing Theory §5 steps 1–6 exactly;
  `solver/steady.py: solve_steady(problem) -> T`. Linear problems: one solve, no iteration.
  Log one line per iteration (residual, max ΔT, line-search factor).
- [x] **M3.8 [A] Validation.** `model/validate.py` with every check in Data §8, each with a
  unit test that triggers it.
- [x] **M3.9 [B] Recovery.** `post/recovery.py: nodal_flux(mesh, problem, T) ->
  dict[region, (node_idx, q (n, 2))]`, `element_flux`, `gradient` (Theory §7).
- [x] **M3.10 [B] Reactions and energy balance.** `post/reactions.py`, `post/energy.py`
  (Theory §4, §7): heat flow per BC and the balance table.
- [x] **M3.11 [B] Results file, steady.** `solver/results_writer.py` and
  `post/results.py` (Data §9) for a single step; `api.solve` for steady models.
- [x] **M3.G [C] Gate.** V-01 … V-14, V-32, V-33, V-34 (steady part).

## M4 — Transient solver

- [x] **M4.1 [A] Capacitance.** `physics/capacitance.py`: consistent and lumped
  (Theory §2, §3 — HRZ for quadratic elements).
  Accept: total of C equals ∫ρc g dA for both forms, all element types; lumped is diagonal
  and positive.
- [x] **M4.2 [C] θ-method, fixed step.** `solver/transient.py: solve_transient(problem)`
  implementing Theory §6 (residual, tangent, stored g_n, θ = 1 on discontinuity steps,
  factorisation reuse in the linear constant-Δt case).
  Accept: V-16 and V-21.
- [x] **M4.3 [B] Automatic time stepping.** `solver/timestep.py: StepController`
  (Theory §6.1): error estimate, accept/reject, growth limits, Newton-failure cutback,
  mandatory times (outputs, table breakpoints, end time), `max_dT_per_step`, the Δt₀
  suggestion and the oscillation warning.
  Accept: unit tests of the controller alone with scripted error sequences; V-17, V-18.
- [x] **M4.4 [B] Streaming output, progress, cancel.** Extendable datasets; output control
  (`all | every_n | times`); `progress` callback (Data §11); flush every 10 steps so a
  crashed or cancelled run leaves a readable file; per-step energy columns.
- [x] **M4.5 [A] Initial conditions.** All four kinds of `InitialCondition`; prescribed
  nodes take their BC value at t = 0.
- [x] **M4.6 [A] CLI.** `thermalfea solve model.tfea [-o results.h5]` with a progress line
  per step; exit code 2 on `ConvergenceError`.
- [x] **M4.G [C] Gate.** V-16 … V-21, V-34 on all transient cases.

## M5 — Post-processing (headless)

All plotting functions take a `Results`, return a Matplotlib `Figure`, optionally save to
`path`, and take `ax=None` so the GUI can draw into its own axes.

- [x] **M5.1 [B] Contour plot.** `post/plots.py: contour(results, step, field, levels=12,
  vmin=None, vmax=None, smooth=False, show_mesh=False, ax=None)`. Fields: `T`, `qx`, `qy`,
  `qmag`, `gradx`, `grady`, `gradmag`. Build a display triangulation once per mesh
  (T3 as is; Q4 → 2; T6 → 4; Q8 → 6 triangles using mid-side nodes). Flux fields are drawn
  region by region (they are discontinuous at interfaces). Banded by default, colour bar
  with units, min/max markers, time in the title. Temperature shown in the model's
  display unit.
  Accept: image-free tests — the triangulation covers the mesh area exactly; the plotted
  array min/max equal the field's.
- [x] **M5.2 [A] Vector plot.** `vectors(results, step, density=30, scale=None, ax=None)`:
  heat-flux arrows at element centroids, thinned to about `density` arrows across the
  larger model dimension, coloured by magnitude.
- [x] **M5.3 [A] History plots.** `history(results, points=[(x, y), …] | nodes=[…])`
  (nearest node); `history_stat(results, selection, stat="min|max|mean")`;
  `heat_flow_history(results, bc_names)`.
- [x] **M5.4 [B] Path plots.** `post/path.py: sample(results, step, polyline, n=200) ->
  (s, values)`: locate each sample point's element (cKDTree over centroids for candidates,
  then inverse isoparametric mapping by Newton iteration, tolerance 1e-10 in local
  coordinates) and interpolate with the shape functions. `plots.path(...)`.
  Accept: sampling a linear field is exact on distorted quadratic meshes; a point outside
  the mesh returns NaN.
- [x] **M5.5 [A] Export.** `post/export.py`: nodal CSV (x, y, T, qx, qy per step); history
  CSV; VTU per step plus a `.pvd` index through `meshio`; animation of any contour to GIF
  (Pillow writer) or MP4 if ffmpeg is present.
- [x] **M5.6 [A] Text summary.** `post/summary.py`: min/max temperature with locations,
  heat flow per BC, energy balance, steps, iterations, warnings. Printed by the CLI.
- [x] **M5.G [C] Gate.** Produce every plot type for V-10 and V-17; a human looks at them.
  _Reviewed by the owner on 2026-11-16: images, animation and CSV files look fine._

## M6 — Convection library

- [x] **M6.1 [A] Fluid properties.** `convection/fluid_props.py: FluidProps`,
  `Fluid.props(T)` (Data §6): interpolation, β rule, clamping with a single warning.
- [x] **M6.2 [A] Correlations.** `convection/correlations.py`: one pure function per ID in
  Theory §8 and §8.1 (`nu_*`, `friction_churchill`, `nu_duct`), plus a registry
  `CORRELATIONS: dict[str, CorrelationInfo]` (function, required inputs, validity range,
  description, source). No model or mesh access in this file.
  Accept: V-25, V-26.
- [x] **M6.3 [B] Evaluator.** `convection/evaluator.py`: turns a `CorrelationConvection`
  into h at every edge integration point, given the lagged wall temperature (Theory §8):
  film properties, local or average wall-temperature mode, automatic characteristic length
  (total length of the selection for plates; required input for cylinders), automatic
  up/down choice for horizontal plates, `plate_forced_local` distance from the leading
  edge, validity warnings (once per BC per solve). The resulting h feeds the ordinary
  convection assembly of M3.3; the problem is flagged nonlinear.
  Accept: V-15.
- [x] **M6.4 [A] Stand-alone calculator.** `api.htc(correlation, fluid, T_surface, T_inf,
  **inputs) -> HtcResult` (h, Nu, Re or Ra, Pr, regime, warnings) for use by the GUI tool.
- [x] **M6.G [C] Gate.** V-15, V-25, V-26; check each formula against Theory §8 line by line.

## M7 — Flow solver

- [x] **M7.1 [C] In-plane stream.** `flow/stream.py`: build cells along the path, assign
  wall edges to cells, create fluid DOFs in the `DofMap`, and assemble the cell matrices of
  Theory §9.1 (inlet node prescribed to `T_inlet`).
  Accept: V-27, V-28; the cell matrix times a uniform temperature vector is zero.
- [x] **M7.2 [B] Through-plane stream.** h from Theory §8.1 at the specified bulk
  temperature, applied as ordinary convection on the walls.
- [x] **M7.3 [B] Network hydraulics.** `flow/network.py: solve_network(network, streams,
  fluid_T) -> dict[branch, mass_flow], dict[node, pressure]` (Theory §9.2).
  Accept: V-30, V-31; mass is conserved at every node to 1e-10.
- [x] **M7.4 [C] Coupling.** `flow/provider.py` (`FlowProvider`, Data §13) and
  `flow/coupling.py: StreamNetworkProvider`; the drivers call only the provider interface.
  Inside each nonlinear iteration update h
  (lagged properties), then hydraulics when needed (Theory §9.2 last paragraph); the matrix
  is unsymmetric — confirm nothing downstream assumes symmetry. Write `/fluid/<stream>`
  results (Data §9); add the stream enthalpy term to the energy balance.
  Accept: V-29; a transient case with a time-varying flow rate runs and conserves energy.
- [x] **M7.5 [A] Flow post-processing.** Plot fluid and mean wall temperature against s;
  stream summary table (ṁ, Re, regime, mean h, Δp, T_in, T_out, heat picked up).
- [x] **M7.G [C] Gate.** V-26 … V-31 and a review of M7.1 against Theory §9.1.

## M8 — GUI

Layout modelled on ANSYS Mechanical: model tree on the left, viewport in the centre,
property panel under the tree, message log at the bottom, toolbar with selection-mode
buttons. Tree nodes: Geometry, Materials, Regions, Mesh, Initial Condition, Loads &
Boundary Conditions, Flow (Streams, Network), Enclosures, Analysis Settings, Solution
(Results objects). All long operations (build, mesh, solve) run in a worker thread.

- [x] **M8.1 [B] Application shell.** `gui/app.py`, `main_window.py`: docks, menus,
  toolbar, status bar, window-state persistence (`QSettings`), a `logging` handler that
  writes to the message panel, a global handler that shows `ThermalFEAError` messages in a
  dialog.
- [x] **M8.2 [B] Document and undo.** `gui/document.py: Document` owns the `Model`,
  `BuiltGeometry`, `Mesh`, results path, and stale flags (geometry edit → mesh and results
  stale; load edit → results stale). `gui/commands.py: ModelEditCommand(QUndoCommand)`
  stores the model JSON before and after an edit (whole-model snapshot — simple and always
  correct). Signals: `model_changed`, `geometry_built`, `mesh_changed`, `results_changed`.
- [x] **M8.3 [C] Viewport.** `gui/scene.py`: the `SceneView` interface, `FieldDisplay` and
  `LoadSymbol` (Data §13). `gui/viewport_mpl.py: MplSceneView` implements it; no other GUI
  module may touch the model-view Matplotlib artists (add this to the layer test). The
  implementation: Matplotlib canvas with equal aspect and
  separate artist layers (geometry, mesh, load symbols, results, highlight). Wheel zoom
  about the cursor, middle-drag pan, fit-all, coordinate read-out. Picking for points,
  curves, surfaces (point-in-polygon on the sampled boundary), nodes and elements, with
  hover highlight, click, Ctrl-click to add, and box selection; emits
  `selection_changed(dim, tags)`. Use `LineCollection`/`PolyCollection` and blitting so
  hover stays responsive with 100 000 elements.
- [x] **M8.4 [B] Tree and property panels.** `gui/tree.py` with context menus (add, rename,
  duplicate, suppress, delete). `gui/property_panels/form.py` generates a form from a
  dataclass using field metadata (label, quantity for unit conversion, limits);
  `FunctionEditor` widget for constant / table (editable grid, paste from Excel, preview
  plot) / expression (validated live); `SelectionEditor` widget ("pick in viewport" then
  Apply). Every edit goes through `ModelEditCommand`. Tree entries, "add" menus and panels
  for loads are generated from the BC registry (`FormSpec`), so a newly registered load
  appears without editing GUI code.
- [x] **M8.5 [B] Geometry tools.** Dialogs for each op in Data §4 with numeric entry and
  click-to-place with grid snap; booleans and transforms on the current selection; delete;
  STEP/BREP import; editable operation history list (edit parameters, reorder is not
  allowed). Rebuild after each change.
- [x] **M8.6 [A] Materials and regions.** Material editor, library browser (copy into the
  model), user library; region assignment panel with thickness and material angle.
- [x] **M8.7 [B] Mesh panel.** All `MeshSettings`, Generate button, statistics, quality
  histogram, colour elements by quality.
- [x] **M8.8 [B] Load panels.** One panel per class in Data §8 through the form generator;
  load symbols in the viewport (colour per type plus legend); the correlation panel shows
  the formula, validity range and a preview of h from `api.htc`.
- [x] **M8.9 [B] Solve.** Analysis-settings panel; validation issue list (double-click
  selects the offending object); `gui/worker.py` solve thread with progress dialog showing
  time, Δt, iterations and a live residual plot; Cancel uses the progress callback.
- [x] **M8.10 [B] Result display.** Contour and vector result objects in the tree with
  controls (field, step slider and time box, range, levels, smooth/banded, mesh overlay);
  click probe showing interpolated values (uses `post/path.py` point location); min/max
  markers; play animation.
- [x] **M8.11 [B] Charts and export.** Chart window for nodal history (pick nodes in the
  viewport), path plot (pick the polyline), heat-flow history and energy balance; export
  of image, CSV, VTU, GIF.
- [x] **M8.12 [A] Flow panels.** Stream editor (pick walls, pick path points), network
  table editor, flow results table and plot, HTC calculator tool window.
- [x] **M8.13 [A] File handling.** New, Open, Save, Save As, recent files, unsaved-changes
  prompt, results reattached on open if the hash matches, Examples menu that loads the
  verification models.
- [x] **M8.14 [B] GUI tests.** `tests/gui/` with `pytest-qt` and
  `QT_QPA_PLATFORM=offscreen`: start the app, build the V-10 model through the command
  layer, mesh, solve, open a contour, undo/redo ten edits, save and reopen.
- [ ] **M8.G Human gate.** A person builds V-10 and V-17 from scratch in the GUI following
  the tutorial text, and lists every point of friction. V-10 was reviewed on 2026-11-24.
  The owner then decided to review V-10 and V-17 again on the GUI-identity changes, so
  this gate depends on M11.64 (owner, 2026-11-24).

## M9 — Enclosure radiation

- [ ] **M9.1 [B] View factors, unobstructed.** `physics/viewfactors.py` crossed strings and
  the facing test, vectorised over all pairs (Theory §10.1). Accept: V-22a, b, c.
- [ ] **M9.2 [C] Obstruction.** Sight-line blocking test and subdivision; reciprocity and
  row-sum smoothing. Accept: V-22d; closed concave (L-shaped) cavity rows sum to 1 ± 1e-3
  before smoothing.
- [ ] **M9.3 [C] Radiosity coupling.** `physics/enclosure.py`: matrix M, residual and
  tangent block (Theory §10), integrated into the Newton loop for steady and transient.
  Accept: V-23, V-24; tangent verified against finite differences.
- [ ] **M9.4 [A] Model, GUI and post.** Enclosure panel; report of view-factor row sums;
  net radiative flux per face as a plottable boundary result.
- [ ] **M9.5 [C] Axisymmetric view factors.** Theory §10.2. Until this is done, validation
  rejects enclosures in axisymmetric models with a clear message.

## M10 — Extended features

- [x] **M10.1 [C] Thermal contact.** Mesh post-processing step that duplicates the nodes
  along each contact curve (the side with the higher region id gets the new nodes; an end
  point of the curve is duplicated only if it lies on the outer boundary), then
  `physics/contact.py` (Theory §11). Accept: V-35.
- [ ] **M10.2 [B] Phase change.** Theory §12, with the forced settings. Accept: V-36.
- [x] **M10.3 [B] DXF import.** `ezdxf`: LINE, ARC, CIRCLE, LWPOLYLINE (with bulges),
  SPLINE → curves; join end points within tolerance; closed loops → surfaces, inner loops
  → holes.
- [x] **M10.4 [B] Unit systems.** Full `UnitSettings` (Data §7) through the form generator
  and all plot labels; SI m, SI mm, US customary presets.
- [x] **M10.5 [A] Report.** Self-contained HTML report: model summary, materials, mesh
  statistics, load tables, solver log summary, energy balance, chosen plots.
  *(On hold from 2026-11-16; released by the owner on 2026-11-22, Q29.15.)*
- [x] **M10.6 [A] Restart.** Continue a transient run from the last stored step to a later
  end time, appending to the same results file.

## M11 — Release hardening

- [x] **M11.1 Human task.** Spot-check the property tables (Data §6) and every correlation
  (Theory §8) against a heat-transfer reference text; record the source and edition.
  Closed by the owner on 2026-11-23 after M11.37–M11.42 (`docs/property-verification.md`,
  OPEN_QUESTIONS Q30).
- [x] **M11.2 [B] V&V report.** Script that runs the verification suite and writes a table
  of case, quantity, analytic value, computed value, error and tolerance to
  `docs/vv-report.md`.
- [x] **M11.3 [B] Performance.** Benchmark test for Plan §6 item 6; profile; cache the
  sparsity pattern and element geometry; reuse factorisations; consider `pypardiso` as an
  optional faster solver behind the `Factorization` wrapper.
- [x] **M11.4 [B] User guide.** MkDocs site: installation, three tutorials (NAFEMS T4
  steady plate; transient quench of a fin with natural convection and radiation; cold
  plate with a water stream), theory manual generated from `docs/theory.md`, correlation
  reference with validity ranges, stated limitations.
- [x] **M11.5 [B] Windows build.** PyInstaller spec (gmsh DLL and Qt plugins included);
  smoke test that the built executable opens, solves an example, and exits.
- [x] **M11.7 [B] Axisymmetric control in the GUI.** Defect Q26.4(a); owner's choices in
  Q27. A "Geometry type: Planar / Axisymmetric" choice at the top of the Analysis Settings
  panel sets `Model.analysis`, through the undo stack; changing it marks the mesh and the
  results out of date. The region "Thickness" field is hidden for an axisymmetric model,
  and the viewport draws the axis x = 0 (through `SceneView`). Tests: switching, undo and
  out-of-date mesh; V-05 built from scratch in the window meets its own verification
  target. Remove the limitation from `guide/limitations.md`, `guide/getting-started.md`
  and `docs/gui-walkthrough.md`.
- [x] **M11.8 [A] Display fixes.** Defects Q26.4(b), (c), (f). (b) An unset optional
  function (stream mass flow) is shown as unset, not "Constant 0"; reproduce with a
  failing GUI test first. (c) The HTC calculator offers the cross-section type for the
  duct correlation and passes it to `api.htc`; test: it reproduces the h pinned by the
  cold-plate tutorial. (f) A steady solution is reported as "steady state", not
  "t = 0 s", in plot titles, the summary and the status bar (read `/meta` `analysis`).
  Update the guide pages that describe these defects.
- [x] **M11.9 [B] Inputs for new loads.** Defect Q26.4(d); owner's choices in Q27. Adding
  a correlation convection or a radiation condition in the GUI opens a dialog that asks
  for the correlation, the fluid, the ambient temperature and the emissivity (as New
  stream does); no value is filled in by the program. Validation also reports an error
  for an empty correlation or fluid and a warning for an ambient temperature of 0 K or an
  emissivity of 0, for models from files and scripts. Update the guide.
- [x] **M11.10 [B] First time step without a false warning.** Defect Q26.4(e); owner's
  choice (ii) in Q27. The oscillation warning of Theory §6.1 is not logged for a step the
  program suggested itself; it still applies to a first step set by the user. Add the
  rule to Theory §6.1 in the wording the owner chose on 2026-11-22 (Q27.3, Q29.15): "The
  warning is checked once, for the first step, and is not logged when that step is the
  suggested Δt₀." Regenerate the guide, and test both cases. (M11.7–M11.10 were released
  from hold on 2026-11-22.)
- [x] **M11.11 [B] Restart compatibility.** `REVIEW.md` findings 2, 3, 4; owner's choice
  in Q28.1. Before anything is written to the file, a restart is refused when:
  - the mesh differs: element types, connectivity, element regions, boundary facets, or
    planar against axisymmetric;
  - any region's material, thickness or material angle differs from the file's region
    data;
  - the streams differ from the file's: names, or DOF mapping.

  Loads and solver settings may still change. Tests: each case is refused, the file is
  left byte-for-byte unchanged, and an unchanged model still continues. Update Q25.4 and
  `docs/handover.md`.
- [x] **M11.12 [A] Input guards.** `REVIEW.md` findings 1, 8; Q28.2.
  `thermalfea solve m.tfea -o m.tfea` exits with an error and leaves the model file
  unchanged. Validation reports an error for `dt_max <= 0`, for `dt_max < dt_min`, and for
  `initial_dt <= 0` when it is set. Tests: each case, in the CLI and in `validate`.
  Extended by Q29 (`REVIEW-2.md` 2.1-13f): also `dt_min`, `time_tol`, `rtol`, `ttol` and
  `max_dT_per_step` must be > 0.
- [x] **M11.13 [A] Mesh out of date after selection edits.** `REVIEW.md` finding 5; Q28.3.
  `gui/document.py: classify_change` also counts the selection names listed in
  `structured_surfaces` and in each refinement's `selection`. Tests: editing either kind
  of selection returns `"mesh"`; editing an unused selection still returns `"results"`.
- [x] **M11.14 [B] Path locator fallback.** `REVIEW.md` finding 6; Q28.4. In
  `post/path.py`, a point not found among the nearest candidates is tested against every
  element whose bounding box holds it. Tests: the reviewer's case (a point just inside a
  large quadrilateral next to small ones) is found, and a point outside still gives -1.
- [x] **M11.15 [B] Position-dependent temperatures in validation.** `REVIEW.md` finding 7;
  Q28.5. Tests: `T = 300*x` on a boundary at x = 1 m, with radiation, does not block the
  solve; a constant 0 K still does. Extended by Q29 (`REVIEW-2.md` 2.1-13d): a time table
  is also sampled over the run, not only at t = 0.
- [x] **M11.16 [B] Early output times on long runs.** `REVIEW.md` finding 9; Q28.6.
  `solver/timestep.py` filters and finds mandatory times with a tolerance relative to the
  local time. Tests: end 1e8 s, output at 1e-5 s, first step 1 s; the first step lands on
  1e-5 s and the time is stored.
- [x] **M11.17 [C] Convergence at equilibrium.** `REVIEW-2.md` 2.1-1; Q29.1. Owner's decision D1
  (c): keep the relative test and `ttol`, and also accept when the free-row residual is at
  most N · ε · (‖|K|·|T|‖ + ‖F‖ + ‖r_extra‖), steady and transient, with **N = 100** (owner,
  2026-11-22). Write it into Theory §5, then the code. Test: a steady model with radiation
  to 300 K started at 300 K converges in one iteration; the relative test is unchanged
  elsewhere.
- [x] **M11.18 [B] Restart, second part.** `REVIEW-2.md` 2.1-2, 2.2 (`/meta`), 2.3
  (`from_results`); Q29. A restart of a model whose stream is fed by a pipe network runs
  (the flow providers are updated before the first heat balance); `/meta` is rewritten
  only once the first new step is written; a `from_results` initial condition uses the
  M11.11 mesh check and refuses a file with no steps. Item 2.1-3 (Q29.2) is added once D2
  is decided. Tests: each case.
- [x] **M11.19 [B] Steps at fast changes.** `REVIEW-2.md` 2.1-5 and the `_jumps` defects;
  Q29.3 (owner's decision D3, 2026-11-22). Write into Theory §6.1, then the code:
  - the prescribed DOFs are left out of the error estimate and of `max_dT_per_step`, and a
    model with no free DOF works;
  - the predictor restarts on the outgoing side of a physical breakpoint, not of an output
    time;
  - a change limit on the free solid temperatures holds for that first step;
  - `_jumps` sees a right-continuous jump, does not misread a periodic load, and its probe
    does not round back to t.

  Tests: each item; the 100 K-over-1 ms ramp of the evaluation takes fewer steps and
  rejects fewer than the 69 steps and 15 rejections recorded there.
- [x] **M11.20 [B] Hydraulics once per nonlinear iteration.** `REVIEW-2.md` 2.1-8. Theory
  §9.2 says the hydraulics are updated at most once per nonlinear iteration; line-search
  trials and the `_jumps` probes must not update the flow providers. Tests: the hydraulic
  solve count per Newton iteration is at most 1; a line-search trial leaves the network
  state unchanged.
- [x] **M11.21 [B] Stream heating flag.** `REVIEW-2.md` 2.1-9a. The heating/cooling flag
  of a stream is decided from the cells that have a wall only. Test: with some cells
  without a wall, a heated stream keeps the Dittus–Boelter exponent 0.4.
- [x] **M11.22 [A] DXF arcs and loops.** `REVIEW-2.md` 2.1-11, 2.2 (duplicate segments,
  fit-point spline nesting). Tests: a bulge of 2 gives the correct centre and area;
  duplicate segments are merged; a closed fit-point spline nests like any other loop.
- [x] **M11.23 [B] Validation coverage.** `REVIEW-2.md` 2.1-13b, c, e, g and the guards of
  2.2 (evaluation §3). Also the owner's decisions of 2026-11-22 (Q29):
  - D5: an inclined-plate angle that is not finite or has |θ| > 90° is refused before
    evaluation, pointing to the horizontal-plate correlations; the validity range stays
    one-sided;
  - D7: `Function.depends_on_position` (add it to Data §1), and a total load refuses a
    position-dependent function;
  - D8: `api.solve` without `built` runs the checks that need only the model.

  Tests: each check.
- [x] **M11.24 [A] Viewport colour bar.** `REVIEW-2.md` 2.1-14, 2.1-17. The axes keep their
  position when the colour bar is removed and redrawn; a Manual scale is allowed on a
  uniform field. Test: the axes position is unchanged over 10 step changes.
- [x] **M11.25 [B] GUI state on New, Open and remesh.** `REVIEW-2.md` 2.1-15, 16, 18, 19 and
  the solve-dialog close. New, Open and Examples clear the results, probes and results
  panel; a background build does not overwrite selections edited during it; a failed
  build keeps the queued rebuild; selection tags and chart nodes are cleared on a new mesh
  or model; `BackgroundTask.shutdown` waits for a running thread. Tests: each
  reproduction, offscreen.
- [x] **M11.26 [B] Meshing.** `REVIEW-2.md` 2.1-12, 2.1-6, `curve_ends` after a Transform.
- [x] **M11.27 [A] Inputs and outputs.** `REVIEW-2.md` items listed in the evaluation §3.
- [x] **M11.28 [B] Term results in the results file.** Q29.6 (owner's decision D6,
  2026-11-22). `Term.results()` (contact heat per contact, h_mean per correlation load) is
  stored in new groups, with a schema-version step (Data §9). Older files stay readable.
  The window shows the values, and the pump example reads them instead of recomputing
  them. Tests: write and read back; an older file still opens.
- [x] **M11.29 [A] GUI flow and selection fixes.** `REVIEW-2.md` 2.2 GUI items.
- [x] **M11.30 [A] Packaging and documentation corrections.** Evaluation §3. Also the
  owner's decisions D10 (Q29.10):
  - an MIT `LICENSE`;
  - pandas moved to an optional extra `examples`;
  - a short root `README.md` (what the program is, how to install it, a link to the
    guide).

  Both copies of the showcase images are kept.
- [x] **M11.31 [C] Fluid rows fully implicit.** `REVIEW-2.md` 2.1-3; Q29.2 (owner's decision
  D2, 2026-11-22). Write into Theory §6 and §9.1, then the code:
  - rows without capacitance (stream fluid rows) are stepped with θ = 1 whatever the
    solid's θ, in both the linear and the Newton paths;
  - on a restart the fluid nodes are first re-solved for the stored wall temperatures and
    the current data, and g(n) is rebuilt;
  - the step energy balance stays closed.

  Tests: a restart with a changed mass flow and θ = 0.5 shows no alternating outlet
  temperature; V-27 to V-29 still pass.
- [x] **M11.32 [B] Network error near zero pressure drop.** `REVIEW-2.md` 2.1-7; Q29.4
  (owner's decision D4). When the network iteration does not converge, the error names the
  worst branch, its Δp, both flow estimates and the largest continuity residual. Theory
  §9.2 is unchanged. Test: the nearly balanced bridge of the evaluation gives that message.
- [x] **M11.33 [A] Document corrections.** Q29.9, Q29.13 (owner's decisions D9, D13).
  - Theory §7: a reported heat flow is positive into the body; reverse the sign of its four
    boundary formulas.
  - Data §8 and §9 brought up to date (numbered `/fluid/<i>` and `/reactions/<i>` with
    `name` attributes; `CorrelationConvection.params`; `Stream.h_override`).
  - Theory §6.1: the suggested Δt₀ is "logged (shown in the Messages panel)".
  - Q20.1 and `docs/handover.md`: providers are updated once per Newton iterate.
  - Drop `thermalfea export` from PLAN.md.

  Regenerate the guide.
- [x] **M11.34 [B] Transforms of points and curves.** Q29.12 (owner's decision D12.4).
  `Transform(copy=False)` moves the points that belong to the shape. Points and curves can
  be transformed, and a transformed point or curve can be used by a Line. Tests: each case,
  and a rebuild keeps the selections.
- [x] **M11.35 [A] User fluids.** Q29.12 (D12.5). `library.fluid(name)` also finds the fluids
  of the user library, as `library.solid` finds user solids. Tests: a user fluid is found
  and used by a convection load; a built-in name still wins, or a clash is reported as for
  solids.
- [x] **M11.36 [B] Fixed temperature at a contact end.** Q29.12 (D12.6), changing Q22.5. A
  fixed temperature on a geometry point at the end of a contact curve fixes the nodes on
  both sides of the contact. Tests: both copies of the node are prescribed; V-35 still
  passes.
- [x] **M11.37 [A] Property tables from the reference text and NIST.** Q30; Data §6
  (owner, 2026-11-23).
  - **The data files.** `fluids.json` and `solids.json` hold the Data §6 contents, each entry
    with `source` and optional `note` (and `k2` for the four orthotropic solids).
  - **The materials page.** `scripts/build_guide.py` accepts those keys, and its generated
    page lists every material with its source.
  - **Removed materials.** Examples, tutorials, their saved models and the guide replace
    Aluminium 6061-T6 with "Aluminum, Alloy 2024-T6". Pages whose numbers follow from the
    material or from the water table are regenerated: the tutorial pages, their hand
    calculations and their tests.
  - **Tests.**
    - Every built-in entry loads.
    - The Data §6 spot rows match exactly.
    - Each fluid's rows ascend, and its source says Table A.4/A.5 or NIST.
    - The orthotropic four have `k2`.
    - No removed name is left in `src`, `examples` or `guide`.
    - The whole suite passes.
- [x] **M11.38 [B] Correlations checked against the reference text.** Theory §8, §8.1 as
  rewritten on 2026-11-23; Q17.2 settled.
  - **Formula.** `hplate_down_natural` becomes Nu = 0.52 Ra^(1/5).
  - **Validity ranges** as in the new table: the Pr ≤ 60 branch of the turbulent plate
    forms, Pr ≥ 0.7 for horizontal plates and for the hot-face-down plate, the Gnielinski
    Re ≥ 3000, and the Dittus–Boelter Pr range.
  - **Inclined plates.** The face check of `inclined_natural` is added.
  - **Horizontal-plate length.** The automatic L_c of the horizontal plates becomes half the
    selection length.
  - **Citations.** Every `CorrelationInfo.source` cites [I] with its equation number, and the
    display texts of `correlation_info.py` follow the theory.
  - **Tests.** V-25 cases for the changed formula, each new validity rule, and the half
    length.
- [x] **M11.39 [B] Non-circular cylinders and spheres.** Theory §8 rows
  `square_corner_crossflow`, `square_face_crossflow`, `hexagon_face_crossflow`,
  `hexagon_corner_crossflow`, `plate_front_crossflow`, `plate_back_crossflow`,
  `sphere_forced` (properties at T∞, μ_s at T_s), `sphere_natural` and
  `vplate_natural_laminar`.
  - Each correlation is in the registry, in `api.htc`, in the evaluator, in the window's
    correlation list, and in the generated guide.
  - **Tests:** V-25 spot checks for each (branches and validity), and a solved model with
    each kind of input.
- [x] **M11.40 [B] Vertical channels.** Theory §8 `vchannel_natural` and
  `vchannel_one_side_natural`, with the param `S`. The rest is as M11.39.
- [x] **M11.41 [B] Impinging jets.** Theory §8 `slot_jet` and `round_jet`.
  - **Params:** `W`/`D`, `H`, `x_r`/`r_r`, with the stated defaults.
  - **Refusals:** a planar `round_jet` without `r_r`, and any `char_length`.
  - The rest is as M11.39.
- [x] **M11.42 [B] Duct sections and Sieder–Tate.** Theory §8.1.
  - **Cross-sections:** the new ones, and the annulus with `Stream.diameter_ratio`
    (Data §8). Its range is checked, and a constant-flux request is refused.
  - **Turbulent option:** `nu_option = "sieder_tate"`, with μ_s at the cell's mean wall
    temperature.
  - **Window and saved files:** the stream form offers both; saved files keep loading, and
    the new field defaults to None.
  - **Tests:** the laminar table values, the annulus interpolation and its limits, a
    Sieder–Tate stream against the formula, and V-27–V-29 still pass.
- [x] **M11.43 [B] Material fields as a function of temperature only.** Owner's request,
  2026-11-24. The owner finished the V-10 review on 2026-11-24, so M11.43–M11.48 may start.
  Material properties are never modelled as a function of time or of a state variable
  (owner, 2026-11-24); Validate already refuses them (`material-not-temperature-only`).
  - **Field setting:** `FieldSpec` gains an optional `variables`: the variables of
    `t, x, y, T` the field's function may use. The default `None` allows all four, so every
    other field is unchanged (Q21.6). A table offers those of `t` and `T` the field allows,
    in that order. The settings are:
    - the material form's `k`, `k2`, `rho` and `cp`: `("T",)`;
    - Heat Power's and Heat Flow's `P`: `("t",)` (owner, 2026-11-24);
    - Fixed Temperature's `T`: `("t", "x", "y")` (owner, 2026-11-24; it may vary with
      position, but not with temperature).
  - **Editor:** the table's variable box shows only the allowed variables, so a material
    table starts on temperature and cannot be switched to time, and a total load's table
    is against time only. An expression that uses a variable the field does not allow is
    refused as it is typed, with a message naming the allowed ones.
  - **Old files:** a material table against time is shown as it is, with the error, and is
    never converted silently.
  - **Label:** the table's "Against" becomes "As a function of" for every field; the guide
    pages that quote it follow.
  - **Tests:** the variable box of a material field, of a total load, of Fixed Temperature
    and of an unrestricted load field; the live expression refusal; an old file with a
    time table; and the new label.
- [x] **M11.44 [B] Library values in the material panel.** Owner's request, 2026-11-24.
  Released: the owner finished the V-10 review on 2026-11-24.
  - **Panel:** a `MaterialPanel` (registered like `RegionPanel`) with a "From library"
    box above the properties, listing the built-in solids and then the user library, with
    type-to-search, and a **Use library values** button.
  - **Effect:** the button replaces this material's `k`, `k2`, `rho`, `cp` and
    `phase_change` with the library entry's, in one undo step. **The material keeps its
    own name** (owner, 2026-11-24), so the regions that use it stay assigned. The values
    stay editable.
  - **Tools > Material library...** stays, for saving to and removing from the user
    library.
  - **Tests:** the list (built-in, then user), type-to-search, use-values (properties,
    name and region kept, one undo step), and an unreadable user library shown as an error
    without losing the built-ins.
- [x] **M11.45 [B] Region highlight, region names and load values in the viewport.**
  Owner's request, 2026-11-24. Released: the owner finished the V-10 review on 2026-11-24.
  - **Region highlight:** selecting a region in the model tree highlights its surfaces
    (`LoadSymbolController.highlight_address`, which today handles only loads and
    contacts); selecting a material highlights every region that uses it.
  - **Region names:** a label with the region's name at each region's surfaces, shown or
    hidden by a checkable View menu entry.
  - **Load values:** a label at each active load's entities giving its name and values in
    the display units, e.g. `cooling: h = 750 W/(m²·K), T_inf = 0 °C`. The values come from
    the load's form fields, so a load registered later is labelled without GUI changes; a
    table is shown as `table(T)` or `table(t)`, an expression as its text. Shown or hidden
    by its own View menu entry.
  - **Viewport:** adds one general `SceneView.set_overlay(layer, items)`, approved by the
    owner on 2026-11-24 as an addition to Data §13 (it replaces the `set_labels` approved
    earlier that day). Its items are plain records with no solver objects: text labels,
    point markers and polylines. Each named layer is replaced as a whole, and an empty
    list clears it. This task, M11.46 and M11.48 each use their own layers. The existing
    methods do not change.
  - **Tests:** the region and material highlight, both toggles, the label text of a
    constant, a table and an expression in SI and in degC, and the labels following
    undo, suppress and rename.
- [x] **M11.46 [B] Probe value at the clicked point.** Owner's request, 2026-11-24.
  Released: the owner finished the V-10 review on 2026-11-24. Depends on M11.45
  (`SceneView.set_overlay`).
  - **Today:** a probe click reports x, y and the value only in the status bar
    (`ResultController.probe_at`).
  - **Change:** each probe click also leaves a marker at the clicked point with the value
    and unit beside it, e.g. `18.21 °C`, in the display units; a click outside the mesh
    leaves no marker.
  - **Behaviour:** markers stay while the probe is on. **Turning the probe off clears
    them** (owner, 2026-11-24), and so does replacing the results; there is no separate
    clear action. When the displayed step, field or unit system changes, each marker is
    evaluated again, so it never shows a stale value. At most `MAX_PROBES` markers are
    kept, as with the readings.
  - **Tests:** a marker and its text after a click, none outside the mesh, re-evaluation on
    a step change and in degC, turning the probe off clearing them, and new results
    clearing them.
- [x] **M11.47 [B] Energy balance window: a table, and no imbalance line.** Owner's request,
  2026-11-24, from the V-10 review. Released: the owner finished the V-10 review on 2026-11-24.
  - **Today:** Results > Energy balance draws `heat_in`, `heat_out`, `net`, `stored_rate`
    and `imbalance` against time on one axis (`gui/charts.py: energy_data`,
    `ENERGY_POWER_COLUMNS`). The imbalance is many orders smaller than the heat flows, and
    equal values hide each other (in V-10, `heat_in` lies under `heat_out`).
  - **Chart:** `imbalance` is no longer drawn; the other four columns are.
  - **Table:** the window gains a table under the chart with one row per stored step and
    the columns time, `heat_in`, `heat_out`, `net`, `stored_rate`, `imbalance` and
    `relative_imbalance`, in the display units (relative imbalance as a plain number). The
    values are the stored ones, with no computation (as `energy_data`). The table can be
    copied; Export CSV is unchanged and still writes every column.
  - **Steady results (owner confirmed, 2026-11-24):** a steady solve has one row at t = 0,
    so the window shows the table only and no chart, titled "Energy balance (steady
    state)".
  - **Tests:** the chart has no imbalance line, the table's rows and columns match
    `Results.energy_balance()` in SI and in other display units, the steady window, and
    Export CSV unchanged.
- [x] **M11.48 [B] Path plot: show the vertices and the path.** Owner's request,
  2026-11-24. Released: the owner finished the V-10 review on 2026-11-24.
  Depends on M11.45 (`SceneView.set_overlay`).
  - **Today:** Results > Path plot... lists the clicked vertices only in the status bar;
    the viewport draws nothing (`gui/chart_tools.py`, "Picking a path").
  - **Change:** while picking, each clicked vertex is drawn as a numbered marker and the
    vertices are joined by the polyline, updated on every click.
  - **Lifetime (owner confirmed, 2026-11-24):** Cancel path plot clears the drawing. After
    Finish, the path stays drawn while its chart window is open and is cleared when that
    window closes; a new path pick replaces it.
  - **Viewport:** drawn in its own layer with M11.45's `SceneView.set_overlay`.
  - **Tests:** markers and polyline after each click, cleared on Cancel, kept with the
    chart and cleared when it closes, and replaced by a new pick.
### GUI identity (owner's decisions D1–D8, 2026-11-24)

The design, the approved data changes and the independent review are in
`docs/gui-identity-plan.md`; each task below names the section it implements. These
tasks come before the owner's M8.G session (D8).

- [x] **M11.49 [B] Part · Boundary · Point vocabulary.** Plan §3.
  - `model/vocabulary.py` provides `domain_dim`, `role_dim`, `role_of` and `entity_word`.
  - It drives the selection toolbar's labels and tooltips, the selection editor's texts,
    the selection-field labels of the forms, and the validation and issue messages that
    name a dimension.
  - The `SelectionMode` values are unchanged, and geometry dialogs keep "surface" and
    "curve".
  - **Tests:** the role mapping for a synthetic 3D domain, an unbuilt model, the toolbar
    labels and the editor texts.
- [x] **M11.50 [B] Summary column in the model tree.** Plan §5.
  - A second, read-only column filled by `gui/tree_summary.py`, refreshed on the model,
    build, mesh, results and stale signals.
  - The Model dock title gives the model name, type, thickness or axis, and units.
  - View > Summary column shows or hides the column. Inline rename edits column 0 only.
  - Summaries for the geometry steps, loads (form title, values, → selection), mesh,
    initial condition, analysis and materials.
  - **Tests:** each summary, the refresh after each signal, column 1 not editable, and
    the existing tree tests still passing.
- [x] **M11.51 [A] Fold empty sections.** Plan §5.
  - While Contacts, Flow (no streams, no network) and Enclosures are all empty, they
    show as one dimmed line, "Contacts · Flow · Enclosures".
  - Its context menu offers Add contact, Add stream and Create network.
  - Once one of them is used, the three show as before. Undo back to empty folds them
    again.
  - **Tests:** folded, unfolded, the menu actions, and undo. Depends on M11.50.
- [x] **M11.52 [B] Geometry steps highlight what they own.** Plan §7.4.
  - Selecting a geometry step highlights `BuiltGeometry.op_entities[id]` of the current
    build, at its highest dimension.
  - A step that owns nothing, or a failed build, clears the highlight and says so in the
    status bar.
  - **Tests:** a rectangle, a cut (its object and its tool), a union, a line, a Delete,
    and a stale build.
- [x] **M11.53 [C] Selection references, rename and delete.** Plan §4.3.
  - `selection_refs` and `selection_users`, from one traversal over every place a
    selection name can appear.
  - `rename_selection`, with a preflight against every collision, and
    `delete_selection`, refused while the selection is used.
  - `all` is reserved.
  - The GUI solve finds the node sets again on the same mesh
    (`meshing/node_sets.py: node_sets_of`), so a renamed or new selection reaches the
    results without a remesh. This replaces "makes the mesh stale" (plan §4.3): a remesh
    for every new load would cost the user much more.
  - **Tests:** a model that uses one selection in every possible place, refusals that
    leave the model and the undo stack untouched, and the node sets of the next solve.
- [x] **M11.54 [B] Selections section and panel.** Plan §4.3, §5.
  - **Tree:** a Selections section, each entry with its role glyph, count and users.
    Selecting an entry highlights it in the current build, and a stale entry is shown as
    stale.
  - **Panel:** rename, kind, entities, the parts it bounds, its users as links, Add from
    viewport, Remove from viewport, and Delete (disabled while used and for `all`).
  - **Navigation:** Page Up / Page Down step through the selections, and the issues
    panel gains a selection branch.
  - **Tests:** the section, the highlight, rename through the panel, delete refused and
    allowed, stepping, and issue navigation.
  - Depends on M11.49, M11.50 and M11.53.
- [x] **M11.55 [B] Name the selection at Apply.** Plan §7.7.
  - The selection editor gains a "New name" box with an unused suggested name.
  - The name is checked inside the same `Document.edit` that assigns the field, and
    Apply reports success explicitly.
  - **Tests:** re-Apply, and a refused collision (widget, model and undo count). Depends
    on M11.53.
- [x] **M11.56 [C] Parts.** Plan §4.1.
  - `RegionAssignment.name` (Data §3) and `part_name()`.
  - "Regions" becomes "Parts" in the tree, the panel and the menus.
  - Add part names each part "Part N". Parts can be renamed inline, and their display
    names are unique.
  - Region labels and the highlight use the part name.
  - Issues navigate by address.
  - The per-region initial-condition editor labels its rows with part names and keeps
    the selection keys.
  - **Tests:** old files and scripts (empty name), uniqueness on add, rename and
    reassignment, a selection rename keeping the display name, and per-region keys.
  - Depends on M11.50 and M11.53.
- [x] **M11.57 [B] Material library source.** Plan §4.2.
  - `Material.source` (`MaterialSource`, Data §6) is set by Use library values from the
    picked `(library, entry)`.
  - The summary and the panel show "‹entry› · library", "· edited" (and which
    properties), "· custom", or "library entry not found".
  - A Restore library values button.
  - The restart check and "edited" compare physical properties only.
  - **Tests:** the same name in the built-in and user libraries, a missing entry, and a
    provenance-only change against an older result. Depends on M11.50.
- [x] **M11.58 [C] Model comparison.** Plan §6.
  - `model/compare.py: model_changes(solved, current) -> list[str]`.
  - It normalises the serialised models and reports every difference left, described
    through names and form labels, with a fallback to the section.
  - It ignores display units, cached tags, `all` and the result displays.
  - **Tests:** a value change, suppress, refinements, geometry reorder, a table value, a
    rename, the ignored items, and the fallback.
- [x] **M11.59 [B] Result header and changes since the solve.** Plan §6.
  - "Solution" becomes "Results".
  - The section summary, the results panel and the viewport title show the analysis, the
    mesh, "results written ‹created›", and current or out of date.
  - The test is `model_changes` against `Results.model`. The panel lists the changes, and
    a missing snapshot shows "comparison unavailable".
  - **Tests:** edit, undo and redo; an unchanged remesh; an edit during a solve; save and
    reopen; a missing snapshot; and a restart. Depends on M11.50 and M11.58.
- [x] **M11.60 [B] Entity report.** Plan §4.6, §7.12.
  - `gui/inspect.py: entity_report(document, dim, tag)` gives the role and number, the
    selections, the loads and contacts (active and suppressed), and every incident part.
  - Adds `BuiltGeometry.point_curves`.
  - **Tests:** a shared interface, a point, and a stale build. Depends on M11.53 and
    M11.56.
- [x] **M11.61 [B] Hover and inspect.** Plan §4.5.
  - Adds the `SceneView.entity_hovered` and `entity_clicked` signals (Data §13).
  - In a Part, Boundary or Point mode, hovering shows a tooltip with the entity report.
  - A single click, while no selection editor or geometry tool is picking, shows the
    report in Properties and marks the tree items involved.
  - **Tests:** the tooltip, the click report, box and Ctrl picks not reporting, and an
    active tool taking precedence. Depends on M11.60.
- [x] **M11.62 [B] Colour by part.** Plan §4.5.
  - Adds `SceneView.set_entity_colors(dim, colors, legend)` (Data §13).
  - View > Colour by: Part / Material / None (default Part), with tree swatches in the
    same colours.
  - **Tests:** the colours of parts and materials, holes kept, fills hidden under a
    result contour, and the load legend kept. Depends on M11.56.
- [x] **M11.63 [C] Rename geometry steps.** Plan §4.4.
  - `rename_operation` (Data §4) rewrites every reference through `REF_RULES`.
  - Inline rename in the tree, in one undo step.
  - **Tests:** references from a point, line, arc, spline, hole loop, boolean, transform
    and delete; rename, build, undo, rebuild; and blank or duplicate ids refused.
  - Depends on M11.52.
- [x] **M11.64 [B] Guide and walkthrough for the new names.**
  - Rewrite the V-10 and V-17 steps of `docs/gui-walkthrough.md`, plus
    `guide/getting-started.md` and the tutorial pages, for Parts, Selections, the
    vocabulary, the summary column and the result header.
  - Give the expected tree of each case.
  - The owner's M8.G re-review of V-10 and V-17 depends on this task.
  - Depends on M11.49–M11.63.
### Flow showcase (owner's choice, 2026-11-26)

- [x] **M11.65 [C] Counterflow double-pipe oil cooler example.** The owner chose this case
  from five candidates (Codex-reviewed) and wrote its spec in `examples/oil_cooler/spec/`
  (an engineering brief PDF, a model-creation brief and an illustration). The decisions of
  2026-11-26 are appended to the model-creation brief.
  - **Model:** axisymmetric copper tube (ASTM B88 Type K 3/8 in) between an in-plane oil
    stream in the bore (z = 0 to L) and an in-plane water stream in the annulus (z = L to
    0, `annulus_inner`); adiabatic shell and tube ends; library copper, unused engine oil
    and water.
  - **Runs and checks** (`examples/oil_cooler/oil_cooler.py`):
    - constant film coefficients against counterflow effectiveness-NTU on four axial
      meshes (both outlets and both duties);
    - the duct correlations, with Re, mean h and regime per stream, and an LMTD
      cross-check;
    - a start-up with the oil inlet rising 20 K over 1 s, checking the copper energy
      storage against the integrated duty difference at two time steps, and the end state
      against the steady solution at the new inlet.
  - **Guide:** `examples/oil_cooler/README.md` with the window steps and screenshots
    (zoomed), the engineering plots (counterflow profiles against z, local ΔT and q′,
    verification, start-up, wall response), and the simplifications stated plainly
    (fully developed duct correlations, quasi-steady streams with no transit delay,
    constant solid properties).
### Held: window fixes from the second M8.G review (owner, 2026-11-25 to 2026-11-26)

**Held until the owner has finished the M8.G re-review (V-10 done, V-17 in progress).**
Then each item becomes a task, together with anything the V-17 review adds. Do not start
before the owner releases them.

From the owner's V-10 review. These are also entries 1–3 of the friction log on the session
page https://claude.ai/artifact/AVKWHDY1Pa6YZ22go6weAH.
1. **Load labels hidden by the boundary line.** The load symbol line and the yellow pick
   highlight are drawn over the value label (e.g. "Fixed Temperature 1: T = 373.15 K"). The
   owner asks for the label to be offset slightly from the line, or drawn in front of it.
   This is the same problem as walkthrough §4 item 11 (the inspect highlight over a label).
2. **Spelling "color", not "colour",** everywhere: menus (View > Colour by), panel groups
   ("Colour scale"), messages and documentation. About 26 files say "colour". This is a
   standing preference (owner, 2026-11-25).
3. **No way to hide a result display.** Today the only way is to delete the plot item;
   Results > Add contour then starts again with default settings. The owner asks for a
   show/hide toggle that keeps the plot and its settings (a checkbox on the result item, or
   Results > Show results).

Found while building the oil-cooler example in the window (M11.65):

4. **Stream mass flow starts at "None".** A number typed while the mode box is "None" is
   ignored, and Validate then reports no mass flow. Default to Constant, or apply a typed
   number by switching the mode.
5. **Selecting a stream does not highlight its walls.** Selections, loads and parts
   highlight their entities when selected in the tree; a stream should highlight its wall
   selections (and could draw its path).
6. **A transient that starts from a steady result can overwrite it.** A model's solve
   writes to `<model file>.h5`, so a start-up solved under the same file name as the steady
   run overwrites the results file its initial condition reads. Today the guide works
   around this by saving the start-up as its own model. Refuse, or warn, when the initial
   condition's results file is the one the solve will write.
7. **No stretched view for slender models.** A 1.2 mm wall over 2 m cannot be seen at true
   scale; the oil-cooler screenshots stretch the radial direction through code. Offer a
   view option to scale one axis (stated in the view so the picture is not mistaken for
   true scale).
8. **Initial Condition panel with kind "from results".** It still shows the uniform
   temperature fields, which are ignored, and the "Results file" box is a plain text field
   with no Browse button, so a long path is clipped.
9. **Stream panel too narrow at the default dock width.** The picking row ("Pick in
   viewport", "New name", Apply, Clear) is cut off, and the mass-flow and path rows need
   scrolling. Walkthrough §4 item 10 is the same problem in the Mesh panel.

From the owner's V-17 review:

10. **Documents still name the old labels.** Two panels were changed during the review
    (owner, 2026-11-27):
    - the material fields are "Conductivity (along axis)" and "Conductivity (across axis,
      empty = isotropic)", and the panel says that each part's Material angle sets the axis;
      `docs/gui-walkthrough.md` (§2 step 2, §3), `guide/tutorials/t4-plate.md` and any
      screenshot of the Material panel still show "Thermal conductivity";
    - "Theta" in Analysis Settings is now "Time integration", a choice of Backward Euler
      (θ = 1), Galerkin (θ = 2/3) and Crank-Nicolson (θ = 1/2); the model still stores the
      number, and another stored value shows as "Custom (θ = …)".
      `guide/getting-started.md` and `guide/tutorials/fin-quench.md` still say "Theta".
11. **Analysis Settings panel grouped by purpose** (owner, 2026-11-27). For a transient
    analysis the panel lists 16 fields of equal weight with no grouping. Lay it out as
    Ansys Mechanical (Step / Nonlinear / Output Controls) and Abaqus (Basic /
    Incrementation tabs) do, in this order, each group a **framed box** (owner's choice; they
    will judge whether boxes are awkward to navigate) with a title and a one-line
    description:
    - **Analysis:** Geometry type, Analysis type.
    - **Time** ("How long the analysis runs."): End time.
    - **Time stepping** ("The solver sizes each step to keep its error estimate within the
      tolerance."): Adaptive time step, Time-step tolerance (shown only when adaptive is
      on), Initial, Smallest and Largest time step, Largest temperature change per step.
    - **Integration** ("How each step is calculated."): Time integration, Lumped capacitance.
    - **Results to store:** Output steps, and "Store every n-th step" / "Output times" for
      their output choice, as today.
    - **Convergence (advanced)** ("Iteration within each step; the defaults suit most
      models."): Residual tolerance, Temperature tolerance, Maximum iterations, Line search.
      **Collapsed by default** (owner); shown for steady and transient analyses.

    Optional boxes show placeholder text for an empty value: "suggested from the mesh"
    (initial step), "no limit" (largest step, largest temperature change). A steady
    analysis shows only Analysis and the collapsed Convergence group. Validate and Solve stay
    below the groups. Panel-only (`SolutionPanel`): the model, files and `docs/data-model.md`
    are unchanged. The guide pages that describe this panel (`guide/getting-started.md`,
    `guide/tutorials/fin-quench.md`, the walkthrough) are updated with item 10.
12. **Selection fields redesigned** (owner, 2026-11-27; friction entry 4 on the session
    page). Today a selection field shows its value twice (a label and the dropdown), a
    "New name" box crowded onto the button row, and "Nothing picked" when nothing is being
    picked. Its default name ("Convection 1 selection") reads like the load's name, and it
    is not clear that "New name" creates a selection and attaches it. Redesign, after Ansys
    (Scoping Method, Apply), COMSOL (Selection list, Create Selection / "Use in") and Abaqus
    (Sets, Done, Edit Region):
    - one row: the role as its label ("Boundary", "Part", "Point"), one dropdown of the
      compatible named selections with their sizes ("cooled · 1 boundary"), and the buttons
      "New…" and "Edit…"; no second value label and no idle status line;
    - "New…" opens a strip below the row only while picking: an instruction, "N boundaries
      picked", a Name box (default "Boundary N" / "Part N", text pre-selected) and
      "Create and use for this load" / Cancel; the toolbar's pick mode is set to the field's
      role (walkthrough friction 2);
    - "Edit…" changes the entities of the current selection, says which other objects use
      it, and offers "Save as new selection…";
    - the chosen selection is highlighted in the view;
    - list fields (a stream's walls, the mesh panel's structured parts) show their
      selections as a list, each with ✕, and the same "add" control. This also removes the
      cut-off picking rows of item 9 and walkthrough friction 10.

    Owner's decisions (2026-11-27):
    - **A dropdown change waits for an "Update" button.** Choosing another selection does not
      change the object; it enables "Update" (one undo step) and a way to revert the
      dropdown to the stored selection. The dropdown of an existing object starts on its
      stored selection.
    - **Default names are empty.** The Name box of a new selection starts empty with a
      placeholder; "Create and use" stays disabled until a valid, unused name is typed.
    - **Buttons are icons** (new, edit, update, remove), each with a tooltip and an
      accessible name that says what it does.

    The same rule holds for item 13's table rows (owner, 2026-11-27).
13. **Value-per-selection fields as tables** (owner, 2026-11-27). "Boundary divisions"
    (`cooled=1, long sides=40, symmetry plane=1`) is typed as comma-separated text; so are
    "Boundary sizes", "Point sizes" and the Initial Condition's "Temperature per part". Show
    each as a small table: one row per entry, a dropdown of the compatible named selections
    (boundaries, points or parts; a name already used is not offered twice), the value box
    with its unit (an integer box for divisions), ✕ to remove the row, and "+ Add" below
    it, with "New…" to pick a new selection as in item 12. Changing a row's dropdown waits
    for the "Update" button, as in item 12 (owner, 2026-11-27). A row's selection is highlighted
    in the view while the row is focused. The model keeps its mappings; panel-only.
    Consider grouping "Boundary divisions" with "Structured parts" under one heading
    ("Structured mesh"), since a structured part's opposite sides need matching divisions.
14. **Nodal history picked in a panel, with node labels in the view** (owner, 2026-11-27).
    Today Results > Nodal history… with no nodes selected switches to node picking and
    asks, in the status bar only, to "choose the action again"; nothing on screen says how
    to finish, and the plotted nodes are not marked on the model. Instead:
    - the action opens a non-modal picking panel (in the property dock or a small tool
      window) that stays while picking: an instruction ("Click nodes in the view;
      Ctrl+click adds or removes"), the list of picked nodes (node number, coordinates and
      the displayed value, each with ✕), and the buttons "Plot history" (enabled from one
      node) and Cancel; nodes already selected when the action starts fill the list;
    - each picked node is marked in the view with a marker and its node number, through the
      viewport overlay that the path plot uses (`SceneView.set_overlay`); the labels stay
      while the chart window is open, as the path drawing does, and the chart's legend uses
      the same node numbers;
    - the path plot is replaced by item 15.
15. **Path plots as saved, editable result items** (owner, 2026-11-27). Today a path is a
    polyline clicked out once, finished through Results > Finish path plot, plotted for the
    displayed step only, and lost when its chart closes. Instead, after Ansys Mechanical
    (Path by two points, edge or axis; sampling points; snap to nodes), Abaqus/CAE (point,
    node and edge list paths; x-value choice) and COMSOL (Cut Line 2D; line graph along a
    boundary selection):
    - Results > Add path plot adds a tree item ("Path 1 · along boundary 'oil wall' ·
      2 times") with a panel in two boxes, **Path** and **Plot**;
    - **Path, defined by:** *Two points* (start and end typed, or picked with a pick icon
      beside each; "snap to nearest node"; number of samples), *Along boundaries* (a
      boundary selection whose curves join end to end; samples are the mesh nodes on them;
      refused with a message when they do not form one chain), or *Points* (an editable
      table of typed or picked points with + and ✕); a direction A → B with a reverse
      button;
    - **Plot:** quantity; times (the displayed step, or several result times overlaid on
      one chart); horizontal axis distance along the path, r or z (x or y in planar
      models); "Plot" and "Export CSV";
    - in the view, a selected path item is drawn with its ends labelled A and B and an
      arrow for the direction;
    - the path is saved with the model; a new solve redraws its chart instead of marking it
      "(out of date)"; Results > Finish / Cancel path plot are removed.

    This adds a saved model type, so `docs/data-model.md` gains it: the owner approves the
    data-model entry when the item is released. Uses item 12's selection dropdown and
    Update rule and item 14's view labels. Phasing if needed: (1) two points and along
    boundaries; (2) the point table and several times on one chart.

- [ ] **M11.6 [C] Release review.** Check every item of Plan §6; resolve or document every
  entry in `docs/OPEN_QUESTIONS.md`. Version 1 excludes the held features M9 and M10.2 and
  their cases V-22a–d, V-23, V-24 and V-36 (owner, 2026-11-22, Q29.15); the guide's
  limitations say so. Depends on M11.7–M11.64, M8.G and M11.1.
