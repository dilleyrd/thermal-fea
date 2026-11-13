# ThermalFEA — Master Plan

A desktop application for 2D steady-state and transient thermal finite-element analysis:
geometry, meshing, loads, a 1D flow solver for convection, solution, and post-processing.
Reference products: ANSYS Mechanical/APDL thermal (PLANE55/PLANE77, SURF151, FLUID116),
Elmer (HeatSolve), SimScale.

**This file is the entry point for every work session.** Read it first, then read only the
documents the task you pick tells you to read.

| Document | Contents | Read when |
|---|---|---|
| `PLAN.md` (this file) | Scope, stack, architecture, rules, milestone status | Always |
| [docs/theory.md](docs/theory.md) | Every equation the code implements | Task says "Theory §n" |
| [docs/data-model.md](docs/data-model.md) | Model classes, file formats, public API | Task says "Data §n" |
| [docs/tasks.md](docs/tasks.md) | Every task, in order, with acceptance tests | To pick and do a task |
| [docs/verification.md](docs/verification.md) | Benchmark problems with analytic answers | Task says "V-nn" |

---

## 1. Scope

### In scope
- **Analysis types:** steady-state and transient; linear and nonlinear.
- **Geometry types:** 2D planar (with thickness per region) and 2D axisymmetric (x = r, y = z).
- **Elements:** 3-node triangle, 4-node quad, 6-node triangle, 8-node quad.
- **Materials:** isotropic or orthotropic conductivity, density, specific heat; each constant
  or a table against temperature. Built-in library of solids and fluids.
- **Geometry:** points, lines, arcs, circles, rectangles, polygons, splines; boolean union,
  cut, intersect; translate, rotate, mirror, copy; STEP/BREP/DXF import.
- **Meshing:** triangle and quad-dominant free meshing, structured (transfinite) meshing,
  global/curve/point size control, refinement fields, linear or quadratic order, quality report.
- **Loads and boundary conditions:** fixed temperature, heat flux, heat flow (W), volumetric
  heat generation, convection (specified h, or h from a correlation), radiation to ambient,
  surface-to-surface radiation in enclosures, thermal contact resistance, initial conditions.
  Every load value may be a constant, a table against time, or an expression of
  time, position and temperature.
- **Convection library:** forced and natural convection correlations for plates, cylinders
  and internal ducts, evaluated with temperature-dependent fluid properties.
- **Flow solver:** 1D streams and pipe networks. From a specified flow rate (or pressure
  drop) it computes velocity, Reynolds number, the heat-transfer coefficient, the pressure
  drop, and the fluid temperature rise along the wall, coupled to the solid solution.
- **Post-processing:** contour plots (temperature, flux magnitude and components, gradient),
  vector plots of heat flux, nodal temperature against time, plots along a path, probes,
  min/max, reaction heat flows, energy balance, animation, export to CSV, VTK and PNG.
- **Files:** save and load models; results stored beside the model.
- **Scripting:** everything the GUI does is available from a Python API and a command line.

### Not in this version (do not build now, but do not block — see §7)
3D analysis, CFD (Navier–Stokes), structural or thermal-stress coupling, other physics,
a 3D graphics viewport, participating-media radiation, parallel/distributed solving.
These are expected future extensions. §7 lists the design rules that keep them possible.

### Never in scope
A custom mesher or CAD kernel (gmsh/OpenCASCADE already handles 3D).

### Known limitation to state in the user documentation
Surface-to-surface radiation is planned for planar models first. The axisymmetric version
(task M9.5) is the hardest single task in the plan and may ship after version 1.

---

## 2. Technology stack (fixed — do not substitute)

| Purpose | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ (3.13 is installed on the dev machine) | Type hints everywhere |
| Numerics | NumPy, SciPy (`scipy.sparse`, SuperLU through `splu`) | Unsymmetric matrices occur (flow) |
| Geometry + mesh | `gmsh` Python package, OpenCASCADE kernel | The only CAD/mesh engine |
| GUI | PySide6 (Qt 6) | |
| Plots, viewport | Matplotlib embedded in Qt (`FigureCanvasQTAgg`) | One renderer for screen and export |
| Results storage | HDF5 through `h5py` | |
| Model file | JSON (`.tfea`) | Human-readable, diffable |
| Export | `meshio` (VTK/VTU), CSV | |
| DXF import | `ezdxf` | Optional dependency |
| Tests | `pytest` | |
| Packaging | `pyproject.toml`, src layout; PyInstaller for the Windows build | |

**Internal units are SI with temperature in kelvin, always.** The GUI and the file format
convert at the boundary (Data §7). Radiation needs absolute temperature; keeping kelvin
internally removes a whole class of bugs.

---

## 3. Architecture

```
src/thermalfea/
  core/        elements.py quadrature.py mesh.py functions.py units.py errors.py
               registry.py (element types, BC types, terms, correlations, result fields)
  materials/   material.py library.py data/solids.json data/fluids.json
  model/       model.py geometry_ops.py selections.py bcs.py settings.py serialize.py
  geometry/    gmsh_session.py builder.py importers.py
  meshing/     mesher.py quality.py
  physics/     conduction.py capacitance.py surface_loads.py body_loads.py
               radiation_ambient.py enclosure.py viewfactors.py contact.py
  convection/  correlations.py fluid_props.py evaluator.py
  flow/        network.py stream.py coupling.py
  solver/      dofs.py terms.py assembler.py linear.py nonlinear.py steady.py transient.py
               timestep.py results_writer.py
  post/        results.py recovery.py reactions.py energy.py path.py plots.py export.py
  gui/         app.py main_window.py tree.py scene.py (viewport interface)
               viewport_mpl.py (Matplotlib implementation) property_panels/ dialogs/
               commands.py worker.py
  api.py       the public scripting facade
  cli.py       `thermalfea solve model.tfea`, `thermalfea info`, `thermalfea export`
tests/
  unit/  verification/  gui/
examples/      one runnable script per verification case
```

### Layer rules (enforced by a test in M0)
1. `core`, `materials`, `physics`, `convection`, `flow`, `solver`, `post` **never import**
   `gmsh`, `PySide6`, or `thermalfea.gui`. They operate on a plain `Mesh` (Data §2).
2. Only `geometry/` and `meshing/` import `gmsh`. All gmsh calls go through `GmshSession`.
3. `gui/` contains no numerics. It calls `api.py` and edits the `Model` through undoable
   commands.
4. The solver takes a `Model` and a `Mesh` and returns a `Results` handle. It can always be
   run without a GUI. Every feature gets a headless test before it gets a dialog.

### Data flow
`Model` (JSON) → `geometry.builder` replays the geometry operations in gmsh → `meshing.mesher`
produces a `Mesh` (NumPy arrays plus boundary sets) → `solver` assembles and solves →
`results_writer` streams to HDF5 → `post` reads HDF5 → `plots`/`gui` display.

---

## 4. Rules for whoever executes this plan

1. **One task per session.** Open [docs/tasks.md](docs/tasks.md), take the first unchecked
   task whose dependencies are checked. Read the sections it names. Do nothing else.
2. **Never derive an equation.** Every formula is in `docs/theory.md`. If a formula seems
   missing or wrong, stop and write the question in `docs/OPEN_QUESTIONS.md`; do not guess.
3. **Never invent a material property, correlation constant, or benchmark target.** Use the
   numbers in the plan documents. If a number is missing, record it in `OPEN_QUESTIONS.md`.
4. **A task is done only when** its acceptance tests exist, they pass, the whole suite
   passes (`pytest -q`), and the task box is ticked in `docs/tasks.md`.
5. **Never weaken a test to make it pass.** Tolerances are part of the specification. A
   failing verification test means the code is wrong.
6. **Do not change public signatures** given in `docs/data-model.md` or the task text. If a
   signature cannot work, record why in `OPEN_QUESTIONS.md` and stop.
7. **Style:** type hints, NumPy-style docstrings stating units for every physical argument,
   no global state apart from `GmshSession`, no `print` (use `logging`), `ruff` clean.
8. **Vectorise over elements.** No Python loop over elements or nodes in assembly or
   recovery code; loop over element *types* and quadrature points only.
9. **Commit after each task** with the message `M<n>.<k>: <task title>`, then push to
   `origin` (https://github.com/dilleyrd/thermal-fea). If the push fails, keep working and
   note it in `docs/OPEN_QUESTIONS.md`; never force-push.
10. **Use the project virtual environment** for everything: `.venv\Scripts\python.exe -m pip`,
    `.venv\Scripts\python.exe -m pytest`, `.venv\Scripts\ruff.exe`. Never install into the
    system Python.
11. **Unattended runs:** when told to work through the list, do tasks one after another.
    Stop and report at any task marked "Human", at a gate you cannot pass, or after the
    same task has failed its acceptance tests three times (record why in
    `docs/OPEN_QUESTIONS.md`, then move to the next task that does not depend on it).

### Task tiers
Each task is tagged with the least capable model that should attempt it.
- **[A]** small model: mechanical work with exact formulas and signatures given.
- **[B]** mid model: several interacting pieces, or GUI wiring.
- **[C]** strongest model, or a human review afterwards: numerical subtleties where a
  plausible-looking wrong answer is likely.

About 70% of tasks are [A] or [B]. Each milestone ends in a **gate**: a [C] review that
runs the verification cases listed for that milestone and reads the diff.

---

## 5. Milestones

Details and acceptance tests are in [docs/tasks.md](docs/tasks.md).

| # | Milestone | Result | Depends on | Status |
|---|---|---|---|---|
| M0 | Scaffolding | Installable package, CI script, layer test | — | ☑ |
| M1 | FE kernel | Steady linear conduction on hand-built meshes | M0 | ☑ |
| M2 | Model, geometry, meshing | Build and mesh any 2D shape from a script; save/load | M0 | ☐ |
| M3 | Loads, nonlinear steady solver, recovery | All loads except flow and enclosure radiation; flux, reactions, energy balance | M1, M2 | ☐ |
| M4 | Transient solver | Adaptive time stepping, HDF5 results | M3 | ☐ |
| M5 | Post-processing (headless) | Contour, vector, history and path plots; export; animation | M4 | ☐ |
| M6 | Convection library | Correlations and fluid properties as boundary conditions | M3 | ☐ |
| M7 | Flow solver | Streams and networks coupled to the solid | M6 | ☐ |
| M8 | GUI | Full interactive application | M5 (M6, M7 for their panels) | ☐ |
| M9 | Enclosure radiation | View factors and radiosity | M3 | ☐ |
| M10 | Extended features | Contact resistance, phase change, DXF, unit systems, report | M5 | ☐ |
| M11 | Release hardening | V&V report, performance, user guide, installer | all | ☐ |

M2 can proceed in parallel with M1. M6, M7 and M9 can proceed in parallel with M8.
**First usable release = M0–M8.** At that point the tool does everything in the original
request except surface-to-surface radiation.

---

## 6. What "adequate for real engineering work" means here

The release criteria, checked in M11:
1. Every case in `docs/verification.md` passes at its stated tolerance.
2. Mesh-convergence tests show the theoretical order (2 for linear, 3 for quadratic elements
   in the L2 norm) on a smooth manufactured solution.
3. Every solve prints an energy balance, and the imbalance is below 0.1% of the heat
   throughput on every verification case.
4. The solver refuses to return an answer silently when it has not converged: it raises, or
   stores the step flagged as unconverged and says so in the log and the GUI.
5. Input is validated before solving (Data §8): missing material, region without property,
   no temperature reference in a steady problem, radiation with a non-absolute temperature,
   correlation used outside its validity range (warning), and so on.
6. A 100 000-node linear transient model runs 100 steps in under 60 s on a laptop.
7. A user guide documents every formula, correlation, its source and its validity range.

---

## 7. Designing for future extension

Planned future directions: 3D analysis, more physics (structural, thermal stress, species,
electrical), more capable fluid flow (2D/3D CFD or coupling to an external CFD code), and a
3D graphics viewport. None of this is built now. The rules below cost little today and
avoid a rewrite later. **They are binding on every task**; where a task description and
this section disagree, this section wins. Interfaces are in Data §13.

1. **No hard-coded dimension.** Code never writes the literal 2 for the space dimension.
   It uses `mesh.dim` and `ElementType.dim`. Arrays are shaped `(…, dim)` and `(…, dim, dim)`.
   Planar thickness and the axisymmetric 2πr factor live in one function (`gfactor`), which
   returns 1 for a future 3D model.
2. **Elements are registered, not enumerated.** Shape functions, quadrature, gmsh type
   code, facet type and display subdivision for each element live in one `ElementType`
   record in `core/registry.py`. No `if etype == "T3"` anywhere outside that registration.
   Adding a tetrahedron later means adding one record.
3. **Boundaries are facets.** Boundary elements are "facets" (dimension = dim − 1): lines
   today, triangles and quads in 3D. Their measure uses the general formula
   √det(JᵀJ), which is correct for a line in 2D and a surface in 3D. In `docs/theory.md`,
   read "edge" as "facet".
4. **Unknowns are named fields.** The `DofMap` holds named fields (`"T"` today), each with
   a number of components per node, plus named extra DOF groups (fluid nodes). Nothing
   assumes "one DOF per node" or that DOF index = node index; always go through the map.
5. **Physics are terms.** Every contribution to the equations (conduction, capacitance,
   each load type, streams, enclosure radiation, contact) implements the `Term` interface.
   The steady and transient drivers know only about terms, never about heat transfer.
   New physics = new terms and fields, with the drivers unchanged.
6. **Loads, correlations and result fields are registered.** A boundary-condition class
   registers its JSON tag, its term factory and its GUI form metadata. The serializer, the
   solver and the GUI find it through the registry. Adding a load must not require editing
   the serializer, the driver or the main window.
7. **The flow solver is a replaceable provider.** The solid solver talks to flow through
   the `FlowProvider` interface (supplies terms and results). The 1D stream/network solver
   is the first implementation; a CFD solver or an external-code coupling can be another.
8. **The viewport is an interface.** GUI code talks to `SceneView` (Data §13), never to
   Matplotlib directly. `viewport_mpl.py` is the only GUI file that imports Matplotlib
   artists for the model view. A VTK/PyVista implementation can be added for 3D without
   touching panels, tree or tools. (Charts — history, path — may use Matplotlib directly.)
9. **Results are generic.** The results file stores any number of named fields, each with a
   location (node, element, facet, extra DOF group) and component count.
10. **Files are versioned and migratable.** `schema_version` on the model and results;
    `model/migrations.py` holds one function per version step; loading an older file
    migrates it. Never change the meaning of an existing field without a version bump.
11. **Linear solver behind an interface.** Only `solver/linear.py` calls SciPy's solvers,
    so iterative or parallel solvers can be added for large 3D systems.
12. **Geometry and selections carry a dimension.** Selections and fingerprints already
    store `dim` (0–3) and 3-component coordinates (z = 0 today). Geometry operations are
    plain records replayed by the builder, so 3D operations (extrude, revolve, box) are
    new records, not a redesign.

A guard test keeps rules 1–5 honest: verification case V-37 registers a 4-node tetrahedron
inside the test and runs a 3D patch test through the unmodified kernel and steady driver.
