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
- [ ] **M1.3 [A] Mesh classes and test-mesh generator.** `core/mesh.py` (Data §2) and
  `core/meshgen.py: rect_mesh(x0, y0, w, h, nx, ny, etype, region=1) -> Mesh` with facet
  blocks tagged entity 1 bottom, 2 right, 3 top, 4 left, plus `distort(mesh, amplitude, seed)`
  that perturbs interior nodes.
  Accept: `validate()` passes for all four types, distorted or not; a mesh with one element
  reversed fails validation.
- [ ] **M1.4 [B] Element geometry kernel and conduction matrix.**
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
- [ ] **M1.5 [A] DOF map and assembler.** `solver/dofs.py: DofMap` with named fields and
  extra groups exactly as Data §13;
  `solver/assembler.py: Assembler` collecting `(conn, Ke)` and `(conn, fe)` batches and
  producing CSR `K` and dense `F` (COO then `tocsr()`, duplicates summed).
  Accept: assembling two elements by hand gives the expected matrix.
- [ ] **M1.6 [B] Linear solve with prescribed values.** `solver/linear.py:
  solve_partitioned(K, F, fixed_idx, fixed_val) -> T` (Theory §4) using `splu`;
  `Factorization` wrapper that can be cached and reused; singular or NaN → `SolverError`.
  Accept: 1D bar by hand; singular system raises.
- [ ] **M1.7 [A] Functions.** `core/functions.py` (Data §1).
  Accept: table interpolation and both extrapolation modes; expression vectorised over
  arrays; `__import__('os')`, attribute access and unknown names all raise `ModelError`;
  dependency flags and breakpoints correct.
- [ ] **M1.8 [A] Materials and libraries.** `materials/material.py`, `materials/library.py`,
  JSON data files with exactly the numbers in Data §6.
  Accept: every library entry loads; values equal the table in Data §6 (test reads both).
- [ ] **M1.G [C] Gate.** Implement V-01 (temperature part) and V-33 with nodal values set
  directly on `rect_mesh` meshes. Implement V-37 (3D tetrahedron guard test). Review M1
  code for vectorisation, units in docstrings, and Plan §7 rules 1–4.

## M2 — Model, geometry, meshing

- [ ] **M2.1 [A] Model dataclasses.** `model/model.py`, `bcs.py`, `settings.py`,
  `geometry_ops.py`, `selections.py` (classes only) — Data §3, §4, §5, §8, §10.
- [ ] **M2.2 [B] Serialisation.** `model/serialize.py: to_json(model) -> dict`,
  `from_json(dict) -> Model`; every polymorphic class is written with a `"type"` tag;
  `schema_version` checked on load (newer → `ModelError`; older → run
  `model/migrations.py`, Data §13, which starts empty). Polymorphic classes are looked up
  through the registry (`register_bc` etc.), not a hard-coded list. `api.save/load`.
  Accept: a model that uses every class round-trips to an equal object; the JSON is stable
  (sorted keys, 2-space indent).
- [ ] **M2.3 [B] Gmsh session.** `geometry/gmsh_session.py`: process-wide singleton guarded
  by a `threading.RLock`; `gmsh.initialize(interruptible=False)` (so it can run in a worker
  thread); terminal output off, messages redirected to `logging`; context manager
  `fresh_model(name)` that clears the previous model.
  Accept: two builds in a row, and one from a non-main thread, both work.
- [ ] **M2.4 [B] Builder: primitives.** `geometry/builder.py: build(model) -> BuiltGeometry`
  for `Point, Line, Arc, Spline, Rectangle, Circle, Polygon, SurfaceFromCurves` with the
  OCC kernel. Keep a map op id → list of (dim, tag).
  Accept: areas from `occ.getMass` equal analytic values for each primitive.
- [ ] **M2.5 [C] Builder: booleans, transforms, final fragment, fingerprints.** `Boolean`
  via `occ.fuse/cut/intersect`, `Transform`, `Delete`. After every OCC boolean, update the
  op-id map from the returned `outDimTagsMap`. After the last op: one `occ.fragment` of all
  surfaces, `synchronize`, then fill `BuiltGeometry` (surfaces, curves, points, each with
  `Fingerprint` from `occ.getCenterOfMass`, `occ.getMass`, `getBoundingBox`; curve→adjacent
  surfaces from `getAdjacencies`; 40-point display polyline per curve from `getValue`).
  Accept: plate with hole has area w·h − πr²; two touching rectangles yield 2 surfaces and
  exactly one shared curve; rebuild gives identical fingerprints.
- [ ] **M2.6 [B] Selection resolution.** `selections.resolve` (Data §5) and API helpers
  `select_points/curves/surfaces(model, built, name, where=predicate | tags=[...])`.
  Accept: a selection survives adding an unrelated shape elsewhere; it becomes stale (with
  a clear message) when its curve is cut in two.
- [ ] **M2.7 [B] Mesher.** `meshing/mesher.py: generate(model, built) -> Mesh`. Apply
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
- [ ] **M2.8 [A] Size controls and structured meshing.** Curve/point sizes, transfinite
  curve divisions, transfinite surfaces (3- or 4-sided only; otherwise `MeshError`),
  distance/threshold refinement fields.
  Accept: a transfinite rectangle has exactly nx·ny quads; refinement gives smaller
  elements near the chosen curve than far from it.
- [ ] **M2.9 [A] Mesh quality.** `meshing/quality.py: report(mesh) -> QualityReport`
  (per-element min angle, aspect ratio, min/max Jacobian ratio; counts; worst elements).
- [ ] **M2.10 [A] STEP/BREP import.** `geometry/importers.py` via `occ.importShapes`; keep
  only surfaces lying in the z = 0 plane; anything else → `GeometryError` with explanation.
- [ ] **M2.11 [A] API facade and `thermalfea info`.** Data §11 (`new_model`, `Geometry`
  helpers, `build`, `mesh`, `assign_region`); CLI prints entity, node and element counts.
- [ ] **M2.G [C] Gate.** Script: L-bracket with a hole and an inset second material; save,
  load, rebuild, mesh; selections resolve identically. Review the builder's tag tracking.

## M3 — Loads, nonlinear steady solver, recovery

- [ ] **M3.1 [B] Terms and problem compilation.** `solver/terms.py` (`State`, `Term`,
  Data §13). `solver/compile.py: compile(model, built, mesh) -> CompiledProblem`: builds the
  `DofMap` (field `"T"`), and one `Term` per contribution by calling the term factory
  registered for each BC class; each term's `setup` resolves its facet or element blocks
  and precomputes its `ElemGeom`. `is_linear` / `is_time_dependent` are the conjunction of
  the terms' flags (Theory §5 definition). Wrap M1.4 conduction as `ConductionTerm`.
  **All later physics tasks (M3.2–M3.6, M4.1, M6.3, M7, M9.3, M10.1) deliver `Term`s
  registered this way**; the drivers in M3.7 and M4.2 loop over `problem.terms` only.
- [ ] **M3.2 [A] Body loads.** `physics/body_loads.py`: `HeatGeneration`, `HeatPower`
  (Theory §2). Function evaluated at integration points with `t, x, y, T`.
- [ ] **M3.3 [A] Surface loads.** `physics/surface_loads.py`: `HeatFlux`, `HeatFlow`,
  `Convection` matrices and vectors (Theory §2).
  Accept: total applied heat equals q̄·area for planar and axisymmetric edges.
- [ ] **M3.4 [A] Prescribed temperatures.** Collect nodes of `FixedTemperature` selections
  (curves and points) and evaluate `T(t, x, y)`; conflicting values at a shared node →
  the later BC in the list wins, with a logged warning.
- [ ] **M3.5 [B] Temperature-dependent properties.** Evaluate k, k2, ρ, c at integration
  points from N·T_e; build D (Theory §2, orthotropic rotation).
  Accept: V-12 matrix check — constant D rotated by 90° swaps the roles of k1 and k2.
- [ ] **M3.6 [B] Radiation to ambient.** `physics/radiation_ambient.py` residual and
  tangent (Theory §5).
  Accept: tangent matches a finite-difference derivative of the residual to 1e-5 relative.
- [ ] **M3.7 [C] Nonlinear steady driver.** `solver/nonlinear.py: newton(assemble_fn, T0,
  fixed, settings) -> NewtonResult` implementing Theory §5 steps 1–6 exactly;
  `solver/steady.py: solve_steady(problem) -> T`. Linear problems: one solve, no iteration.
  Log one line per iteration (residual, max ΔT, line-search factor).
- [ ] **M3.8 [A] Validation.** `model/validate.py` with every check in Data §8, each with a
  unit test that triggers it.
- [ ] **M3.9 [B] Recovery.** `post/recovery.py: nodal_flux(mesh, problem, T) ->
  dict[region, (node_idx, q (n, 2))]`, `element_flux`, `gradient` (Theory §7).
- [ ] **M3.10 [B] Reactions and energy balance.** `post/reactions.py`, `post/energy.py`
  (Theory §4, §7): heat flow per BC and the balance table.
- [ ] **M3.11 [B] Results file, steady.** `solver/results_writer.py` and
  `post/results.py` (Data §9) for a single step; `api.solve` for steady models.
- [ ] **M3.G [C] Gate.** V-01 … V-14, V-32, V-33, V-34 (steady part).

## M4 — Transient solver

- [ ] **M4.1 [A] Capacitance.** `physics/capacitance.py`: consistent and lumped
  (Theory §2, §3 — HRZ for quadratic elements).
  Accept: total of C equals ∫ρc g dA for both forms, all element types; lumped is diagonal
  and positive.
- [ ] **M4.2 [C] θ-method, fixed step.** `solver/transient.py: solve_transient(problem)`
  implementing Theory §6 (residual, tangent, stored g_n, θ = 1 on discontinuity steps,
  factorisation reuse in the linear constant-Δt case).
  Accept: V-16 and V-21.
- [ ] **M4.3 [B] Automatic time stepping.** `solver/timestep.py: StepController`
  (Theory §6.1): error estimate, accept/reject, growth limits, Newton-failure cutback,
  mandatory times (outputs, table breakpoints, end time), `max_dT_per_step`, the Δt₀
  suggestion and the oscillation warning.
  Accept: unit tests of the controller alone with scripted error sequences; V-17, V-18.
- [ ] **M4.4 [B] Streaming output, progress, cancel.** Extendable datasets; output control
  (`all | every_n | times`); `progress` callback (Data §11); flush every 10 steps so a
  crashed or cancelled run leaves a readable file; per-step energy columns.
- [ ] **M4.5 [A] Initial conditions.** All four kinds of `InitialCondition`; prescribed
  nodes take their BC value at t = 0.
- [ ] **M4.6 [A] CLI.** `thermalfea solve model.tfea [-o results.h5]` with a progress line
  per step; exit code 2 on `ConvergenceError`.
- [ ] **M4.G [C] Gate.** V-16 … V-21, V-34 on all transient cases.

## M5 — Post-processing (headless)

All plotting functions take a `Results`, return a Matplotlib `Figure`, optionally save to
`path`, and take `ax=None` so the GUI can draw into its own axes.

- [ ] **M5.1 [B] Contour plot.** `post/plots.py: contour(results, step, field, levels=12,
  vmin=None, vmax=None, smooth=False, show_mesh=False, ax=None)`. Fields: `T`, `qx`, `qy`,
  `qmag`, `gradx`, `grady`, `gradmag`. Build a display triangulation once per mesh
  (T3 as is; Q4 → 2; T6 → 4; Q8 → 6 triangles using mid-side nodes). Flux fields are drawn
  region by region (they are discontinuous at interfaces). Banded by default, colour bar
  with units, min/max markers, time in the title. Temperature shown in the model's
  display unit.
  Accept: image-free tests — the triangulation covers the mesh area exactly; the plotted
  array min/max equal the field's.
- [ ] **M5.2 [A] Vector plot.** `vectors(results, step, density=30, scale=None, ax=None)`:
  heat-flux arrows at element centroids, thinned to about `density` arrows across the
  larger model dimension, coloured by magnitude.
- [ ] **M5.3 [A] History plots.** `history(results, points=[(x, y), …] | nodes=[…])`
  (nearest node); `history_stat(results, selection, stat="min|max|mean")`;
  `heat_flow_history(results, bc_names)`.
- [ ] **M5.4 [B] Path plots.** `post/path.py: sample(results, step, polyline, n=200) ->
  (s, values)`: locate each sample point's element (cKDTree over centroids for candidates,
  then inverse isoparametric mapping by Newton iteration, tolerance 1e-10 in local
  coordinates) and interpolate with the shape functions. `plots.path(...)`.
  Accept: sampling a linear field is exact on distorted quadratic meshes; a point outside
  the mesh returns NaN.
- [ ] **M5.5 [A] Export.** `post/export.py`: nodal CSV (x, y, T, qx, qy per step); history
  CSV; VTU per step plus a `.pvd` index through `meshio`; animation of any contour to GIF
  (Pillow writer) or MP4 if ffmpeg is present.
- [ ] **M5.6 [A] Text summary.** `post/summary.py`: min/max temperature with locations,
  heat flow per BC, energy balance, steps, iterations, warnings. Printed by the CLI.
- [ ] **M5.G [C] Gate.** Produce every plot type for V-10 and V-17; a human looks at them.

## M6 — Convection library

- [ ] **M6.1 [A] Fluid properties.** `convection/fluid_props.py: FluidProps`,
  `Fluid.props(T)` (Data §6): interpolation, β rule, clamping with a single warning.
- [ ] **M6.2 [A] Correlations.** `convection/correlations.py`: one pure function per ID in
  Theory §8 and §8.1 (`nu_*`, `friction_churchill`, `nu_duct`), plus a registry
  `CORRELATIONS: dict[str, CorrelationInfo]` (function, required inputs, validity range,
  description, source). No model or mesh access in this file.
  Accept: V-25, V-26.
- [ ] **M6.3 [B] Evaluator.** `convection/evaluator.py`: turns a `CorrelationConvection`
  into h at every edge integration point, given the lagged wall temperature (Theory §8):
  film properties, local or average wall-temperature mode, automatic characteristic length
  (total length of the selection for plates; required input for cylinders), automatic
  up/down choice for horizontal plates, `plate_forced_local` distance from the leading
  edge, validity warnings (once per BC per solve). The resulting h feeds the ordinary
  convection assembly of M3.3; the problem is flagged nonlinear.
  Accept: V-15.
- [ ] **M6.4 [A] Stand-alone calculator.** `api.htc(correlation, fluid, T_surface, T_inf,
  **inputs) -> HtcResult` (h, Nu, Re or Ra, Pr, regime, warnings) for use by the GUI tool.
- [ ] **M6.G [C] Gate.** V-15, V-25, V-26; check each formula against Theory §8 line by line.

## M7 — Flow solver

- [ ] **M7.1 [C] In-plane stream.** `flow/stream.py`: build cells along the path, assign
  wall edges to cells, create fluid DOFs in the `DofMap`, and assemble the cell matrices of
  Theory §9.1 (inlet node prescribed to `T_inlet`).
  Accept: V-27, V-28; the cell matrix times a uniform temperature vector is zero.
- [ ] **M7.2 [B] Through-plane stream.** h from Theory §8.1 at the specified bulk
  temperature, applied as ordinary convection on the walls.
- [ ] **M7.3 [B] Network hydraulics.** `flow/network.py: solve_network(network, streams,
  fluid_T) -> dict[branch, mass_flow], dict[node, pressure]` (Theory §9.2).
  Accept: V-30, V-31; mass is conserved at every node to 1e-10.
- [ ] **M7.4 [C] Coupling.** `flow/provider.py` (`FlowProvider`, Data §13) and
  `flow/coupling.py: StreamNetworkProvider`; the drivers call only the provider interface.
  Inside each nonlinear iteration update h
  (lagged properties), then hydraulics when needed (Theory §9.2 last paragraph); the matrix
  is unsymmetric — confirm nothing downstream assumes symmetry. Write `/fluid/<stream>`
  results (Data §9); add the stream enthalpy term to the energy balance.
  Accept: V-29; a transient case with a time-varying flow rate runs and conserves energy.
- [ ] **M7.5 [A] Flow post-processing.** Plot fluid and mean wall temperature against s;
  stream summary table (ṁ, Re, regime, mean h, Δp, T_in, T_out, heat picked up).
- [ ] **M7.G [C] Gate.** V-26 … V-31 and a review of M7.1 against Theory §9.1.

## M8 — GUI

Layout modelled on ANSYS Mechanical: model tree on the left, viewport in the centre,
property panel under the tree, message log at the bottom, toolbar with selection-mode
buttons. Tree nodes: Geometry, Materials, Regions, Mesh, Initial Condition, Loads &
Boundary Conditions, Flow (Streams, Network), Enclosures, Analysis Settings, Solution
(Results objects). All long operations (build, mesh, solve) run in a worker thread.

- [ ] **M8.1 [B] Application shell.** `gui/app.py`, `main_window.py`: docks, menus,
  toolbar, status bar, window-state persistence (`QSettings`), a `logging` handler that
  writes to the message panel, a global handler that shows `ThermalFEAError` messages in a
  dialog.
- [ ] **M8.2 [B] Document and undo.** `gui/document.py: Document` owns the `Model`,
  `BuiltGeometry`, `Mesh`, results path, and stale flags (geometry edit → mesh and results
  stale; load edit → results stale). `gui/commands.py: ModelEditCommand(QUndoCommand)`
  stores the model JSON before and after an edit (whole-model snapshot — simple and always
  correct). Signals: `model_changed`, `geometry_built`, `mesh_changed`, `results_changed`.
- [ ] **M8.3 [C] Viewport.** `gui/scene.py`: the `SceneView` interface, `FieldDisplay` and
  `LoadSymbol` (Data §13). `gui/viewport_mpl.py: MplSceneView` implements it; no other GUI
  module may touch the model-view Matplotlib artists (add this to the layer test). The
  implementation: Matplotlib canvas with equal aspect and
  separate artist layers (geometry, mesh, load symbols, results, highlight). Wheel zoom
  about the cursor, middle-drag pan, fit-all, coordinate read-out. Picking for points,
  curves, surfaces (point-in-polygon on the sampled boundary), nodes and elements, with
  hover highlight, click, Ctrl-click to add, and box selection; emits
  `selection_changed(dim, tags)`. Use `LineCollection`/`PolyCollection` and blitting so
  hover stays responsive with 100 000 elements.
- [ ] **M8.4 [B] Tree and property panels.** `gui/tree.py` with context menus (add, rename,
  duplicate, suppress, delete). `gui/property_panels/form.py` generates a form from a
  dataclass using field metadata (label, quantity for unit conversion, limits);
  `FunctionEditor` widget for constant / table (editable grid, paste from Excel, preview
  plot) / expression (validated live); `SelectionEditor` widget ("pick in viewport" then
  Apply). Every edit goes through `ModelEditCommand`. Tree entries, "add" menus and panels
  for loads are generated from the BC registry (`FormSpec`), so a newly registered load
  appears without editing GUI code.
- [ ] **M8.5 [B] Geometry tools.** Dialogs for each op in Data §4 with numeric entry and
  click-to-place with grid snap; booleans and transforms on the current selection; delete;
  STEP/BREP import; editable operation history list (edit parameters, reorder is not
  allowed). Rebuild after each change.
- [ ] **M8.6 [A] Materials and regions.** Material editor, library browser (copy into the
  model), user library; region assignment panel with thickness and material angle.
- [ ] **M8.7 [B] Mesh panel.** All `MeshSettings`, Generate button, statistics, quality
  histogram, colour elements by quality.
- [ ] **M8.8 [B] Load panels.** One panel per class in Data §8 through the form generator;
  load symbols in the viewport (colour per type plus legend); the correlation panel shows
  the formula, validity range and a preview of h from `api.htc`.
- [ ] **M8.9 [B] Solve.** Analysis-settings panel; validation issue list (double-click
  selects the offending object); `gui/worker.py` solve thread with progress dialog showing
  time, Δt, iterations and a live residual plot; Cancel uses the progress callback.
- [ ] **M8.10 [B] Result display.** Contour and vector result objects in the tree with
  controls (field, step slider and time box, range, levels, smooth/banded, mesh overlay);
  click probe showing interpolated values (uses `post/path.py` point location); min/max
  markers; play animation.
- [ ] **M8.11 [B] Charts and export.** Chart window for nodal history (pick nodes in the
  viewport), path plot (pick the polyline), heat-flow history and energy balance; export
  of image, CSV, VTU, GIF.
- [ ] **M8.12 [A] Flow panels.** Stream editor (pick walls, pick path points), network
  table editor, flow results table and plot, HTC calculator tool window.
- [ ] **M8.13 [A] File handling.** New, Open, Save, Save As, recent files, unsaved-changes
  prompt, results reattached on open if the hash matches, Examples menu that loads the
  verification models.
- [ ] **M8.14 [B] GUI tests.** `tests/gui/` with `pytest-qt` and
  `QT_QPA_PLATFORM=offscreen`: start the app, build the V-10 model through the command
  layer, mesh, solve, open a contour, undo/redo ten edits, save and reopen.
- [ ] **M8.G Human gate.** A person builds V-10 and V-17 from scratch in the GUI following
  the tutorial text, and lists every point of friction.

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

- [ ] **M10.1 [C] Thermal contact.** Mesh post-processing step that duplicates the nodes
  along each contact curve (the side with the higher region id gets the new nodes; an end
  point of the curve is duplicated only if it lies on the outer boundary), then
  `physics/contact.py` (Theory §11). Accept: V-35.
- [ ] **M10.2 [B] Phase change.** Theory §12, with the forced settings. Accept: V-36.
- [ ] **M10.3 [B] DXF import.** `ezdxf`: LINE, ARC, CIRCLE, LWPOLYLINE (with bulges),
  SPLINE → curves; join end points within tolerance; closed loops → surfaces, inner loops
  → holes.
- [ ] **M10.4 [B] Unit systems.** Full `UnitSettings` (Data §7) through the form generator
  and all plot labels; SI m, SI mm, US customary presets.
- [ ] **M10.5 [A] Report.** Self-contained HTML report: model summary, materials, mesh
  statistics, load tables, solver log summary, energy balance, chosen plots.
- [ ] **M10.6 [A] Restart.** Continue a transient run from the last stored step to a later
  end time, appending to the same results file.

## M11 — Release hardening

- [ ] **M11.1 Human task.** Spot-check the property tables (Data §6) and every correlation
  (Theory §8) against a heat-transfer reference text; record the source and edition.
- [ ] **M11.2 [B] V&V report.** Script that runs the verification suite and writes a table
  of case, quantity, analytic value, computed value, error and tolerance to
  `docs/vv-report.md`.
- [ ] **M11.3 [B] Performance.** Benchmark test for Plan §6 item 6; profile; cache the
  sparsity pattern and element geometry; reuse factorisations; consider `pypardiso` as an
  optional faster solver behind the `Factorization` wrapper.
- [ ] **M11.4 [B] User guide.** MkDocs site: installation, three tutorials (NAFEMS T4
  steady plate; transient quench of a fin with natural convection and radiation; cold
  plate with a water stream), theory manual generated from `docs/theory.md`, correlation
  reference with validity ranges, stated limitations.
- [ ] **M11.5 [B] Windows build.** PyInstaller spec (gmsh DLL and Qt plugins included);
  smoke test that the built executable opens, solves an example, and exits.
- [ ] **M11.6 [C] Release review.** Check every item of Plan §6; resolve or document every
  entry in `docs/OPEN_QUESTIONS.md`.
