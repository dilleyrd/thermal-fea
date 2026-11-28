# Getting started

This page describes the workflow as the program presents it, first in the window and then
from the command line and from Python. The [tutorials](tutorials/t4-plate.md) apply it to
worked problems.

The program has not yet been reviewed on a real screen by its owner (see
[Limitations](limitations.md)). Layout and wording of the window may change.

## The window

Start the program as described in [Installation](installation.md#start-the-program).

- **Model** dock (top left): the model tree. It has two columns, the name and a summary of
  each item. The dock title shows the model, for example "Model — plate · planar · t 1 m · K"
  (name, planar or axisymmetric, the thickness of the parts, the temperature unit).
  View > Summary column hides the second column.
- **Properties** dock (below it): the panel of the item selected in the tree.
- **Viewport** (centre): the geometry, the mesh, load symbols and result plots.
- **Messages** dock (bottom): the solver log. An **Issues** dock is tabbed with it and lists
  the findings of validation. The View menu shows and hides the docks, and switches the
  load symbols on and off ("Load symbols"), the part names on and off ("Region names"), the
  load values on and off ("Load values"), and chooses how the viewport is colored
  ("Color by": Part, Material or None).
- **Toolbar**: the selection modes None, Point, Boundary, Part, Node and Element, and
  "Fit view" (the key F). In a 2D model a boundary is a curve and a part is a surface.

Menus: File, Edit, View, Geometry, Mesh, Solve, Results, Tools, Help.

### Selecting in the viewport

A click selects the item under the pointer (8 pixels of tolerance). Ctrl-click adds to or
removes from the selection. A click on nothing clears it. A drag longer than 4 pixels
selects by a box: boundaries must lie wholly inside the box, parts are chosen by their
bounding box, elements by their centre. Changing the selection mode clears the selection.
The mouse wheel zooms and the middle button pans.

## The workflow

The model tree lists the items of a model in the order you normally fill them in:

| Tree node | What it holds |
|---|---|
| Geometry | the geometry operations, in the order they were applied |
| Parts | which material (and thickness and material angle) each part has; a part is a named selection of surfaces |
| Selections | every named selection, with its count and the objects that use it |
| Materials | the materials used by the model |
| Mesh | mesh settings and the Generate mesh button |
| Initial Condition | the starting temperature of a transient analysis |
| Loads & Boundary Conditions | fixed temperatures, fluxes, convection, radiation, symmetry, ... |
| Contacts · Flow · Enclosures | one dimmed line while the model has no contact, stream, network or enclosure; once one is added it is replaced by the three sections Contacts (thermal contact between parts), Flow (streams and networks) and Enclosures (enclosure radiation, not available in this version) |
| Analysis Settings | steady or transient, time stepping, output, nonlinear controls |
| Results | the result objects (contour plots, vector plots) after a solve |

Right-click a node to see its actions. Loads can be added, renamed, duplicated, suppressed
and deleted. Materials, streams, contacts and enclosures can be renamed, duplicated and
deleted. Parts, selections and geometry steps can be renamed; a part or an unused selection
can be deleted. Right-click the dimmed line "Contacts · Flow · Enclosures" to Add contact,
Add stream or Create network.

The second column of the tree summarises each item, for example "k 52 W/(m K) · custom" for a
material, "2 boundaries · convection Convection 1" for a selection, or "T3 · 0.025 m ·
1 210 nodes · 2 290 elements · current" for the mesh. Temperatures there are shown with
four significant digits.

**Inspecting.** In the Point, Boundary or Part mode, hover over an entity: a tooltip names
it, its selections and the loads on it. A single click (while no "Pick in viewport" is on)
shows the same report in the status bar and puts the items it names in bold in the tree.

### 1. Geometry

The Geometry menu has Point..., Line..., Arc..., Spline..., Rectangle..., Circle...,
Polygon..., Surface from curves..., Union..., Cut..., Intersect..., Translate...,
Rotate..., Mirror..., Scale..., Delete..., Import STEP/BREP/DXF..., Snap to grid and
Rebuild geometry.

Each operation opens a dialog with numeric entry. The geometry is rebuilt by itself after
every OK. Notes:

- Click a step in the tree to highlight what it owns in the viewport. Right-click a step >
  Rename (or edit the name in place) to give it a name of your own; later steps that refer
  to it follow.
- For Union, Cut and Intersect select the shapes in the viewport first. The earliest
  selected shape (in history order) is the object; the others are the tools.
- The parameters of Translate, Rotate, Mirror and Scale follow the display units: lengths
  and angles are shown and typed in the display units, and the scale factor is a plain
  number.
- An operation that later operations refer to cannot be deleted.
- If a rebuild fails, the old geometry stays, is marked out of date, and the error is
  reported. Edit > Undo recovers.
- DXF import needs the `dxf` extra ([Installation](installation.md#optional-extras)). See
  [Limitations](limitations.md#dxf-import) for what it ignores.
- A new model is a planar model. To make it axisymmetric, set "Geometry type" in Analysis
  Settings (step 5); draw the geometry with x as the radius.

### 2. Materials and parts

Right-click Materials and choose Add material. The new material starts with every property at
0, which means "not set yet": Validate refuses a conductivity of 0, and a transient analysis
also refuses a density or specific heat of 0. Each physical property has a mode box
(Constant, Table or Expression) above its value; leave it on Constant for a constant.
Tools > Material library... opens the built-in library ([Materials](materials.md)).
To start from a library material, select the material, type part of a name in the "From
library" box (built-in entries first, then your own marked "(user)"), and press Use library
values: the conductivity, density, specific heat and phase change are copied in one undo step
and the material keeps its name, so its parts stay assigned. The summary of the material
reads "<entry> · library", or "<entry> · edited" after you change a value, or "k ... · custom"
for a material that never came from the library; the panel shows the source, and **Restore
library values** brings an edited material back.

Right-click Parts and choose Add part. A part "Part 1" appears; its panel has the fields
Name, Selection, Material, Thickness and Material angle. Rename the part (for example
"Plate"). In its Selection field press "Pick in viewport", set the toolbar to Part, click
the surfaces (the status line says "2 parts picked"), type a name for the new selection in
the "New name" box (it is pre-filled with an unused suggestion), press Apply, then press
"Pick in viewport" again to switch picking off. A name that is already used is refused with
a red message. To replace the entities of a field's own selection, pick again and type its
name. Choose the Material, and set the Thickness (planar models) and the Material angle if
needed. Parts and materials have a color swatch; the viewport fills use the same colors
(View > Color by).

The Selections section lists every named selection with its users. Click one to highlight
it. Its panel shows Name (renaming it renames it wherever it is used), Kind, Entities,
Bounds parts and Used by (each user is a link), and has the buttons "Add from viewport",
"Remove from viewport" and Delete (not available while the selection is used). With the
focus on the tree, Page Down and Page Up step through the selections.

### 3. Loads and boundary conditions

Right-click Loads & Boundary Conditions, choose Add, then one of:

Add Fixed Temperature, Add Heat Flux, Add Heat Flow, Add Heat Generation,
Add Heat Power, Add Convection, Add Correlation Convection, Add Radiation to Ambient,
Add Symmetry, Add Adiabatic.

Each load has a Selection field that works as described for parts (set the toolbar to
Boundary for edges, and type a name such as "base" or "cooled" in "New name"). Selecting a
load in the tree highlights its boundaries, and the viewport shows load symbols.

- **Press Enter after typing a number.** The value is applied when you press Enter or leave
  the field. Each applied change is one undo step.
- A value may be a Constant, a Table against time, or an Expression of time, position and
  temperature. Expressions are always evaluated in SI units ([Units](units.md)).
- Heat flows count as positive when they enter the body.
- **Add Correlation Convection** and **Add Radiation to Ambient** first open a window
  that asks for the values the load cannot do without: the correlation, the fluid and the
  ambient temperature (convection), or the emissivity and the ambient temperature
  (radiation). The fields start empty, the program fills in nothing, and **OK** is enabled
  only when every field is valid; **Cancel** adds nothing. Temperatures are typed in the
  display unit. The fluid may stay empty for the `power_law` correlation, which needs none.
  A model from a file or a script that still has an empty correlation or fluid fails
  validation, and an ambient temperature of 0 K or an emissivity of 0 gives a warning.
- Correlation Convection takes its heat-transfer coefficient from a
  [correlation](correlations.md). A correlation used outside its validity range still
  gives a value and logs one warning.
- A Contact (right-click Contacts, Add contact; while the model has none, right-click the
  dimmed line "Contacts · Flow · Enclosures") starts with an empty selection ("Interface
  boundaries") and a conductance of 0, which you must set. A temperature-dependent
  conductance is refused.
- Streams are under Flow: right-click the node Streams and choose Add stream (while the
  model has no stream, use the dimmed line "Contacts · Flow · Enclosures"). The Network
  node is also under Flow. Results > Flow results...
  shows the fluid temperature along the stream.
- Tools > HTC calculator... evaluates a correlation at single values without a model.
  For the internal-duct correlation it also asks for the cross-section (default circular).

### 4. Mesh

Click the Mesh node. The panel has, among others, "Global element size", "Element order"
and "Element shape"; "Boundary sizes", "Point sizes", "Boundary divisions" and "Structured
parts" refer to named selections. Press **Generate mesh** (or use Mesh > Generate mesh). The status bar
reports the number of nodes and elements and the mesh is drawn in the viewport.

### 5. Analysis settings and initial condition

Click Analysis Settings. "Geometry type" is `Planar` or `Axisymmetric`. In an axisymmetric
model x is the radius and the axis x = 0 is drawn in the viewport; parts then have no
Thickness. Changing it is one undo step and marks the mesh and the results out of date.
"Analysis type" is `steady` or `transient`. A transient analysis
shows "End time", "Initial time step", "Smallest time step", "Largest time step",
"Adaptive time step", "Time-step tolerance", "Largest temperature change per step",
"Theta", "Lumped capacitance" and the output controls ("Output steps", "Store every n-th
step", "Output times"). The nonlinear controls are "Residual tolerance", "Temperature
tolerance", "Maximum iterations" and "Line search".

Click Initial Condition for a transient analysis. "Kind" is `uniform`, `expression`,
`per_region` or `from_results`. With `per_region` the field "Temperature per part" takes the
selection name of each part and its temperature. The initial state (step 0) is always stored.

### 6. Validate and solve

- Solve > **Validate** checks the model before solving and lists errors and warnings in
  the Issues dock. Errors must be fixed first.
- Solve > **Solve** runs the analysis on its own thread. A window titled "Solving" shows
  the progress and stays open, with a "Finished" state, so you can read the residual chart.
- Solve > **Cancel solve** stops a run. The steps already written are kept.
- Solve > **Continue transient run** continues a transient run (see below).

The Messages dock shows the log, including the heat entering through each load and the
relative imbalance of the energy balance.

### 7. Results

After a solve the Results node holds a temperature contour (for example "Temperature 1").
Its summary in the tree reads "contour · current", or "contour · out of date" when the model
changed since the solve. Its panel starts with a header (Analysis, Mesh, Results written,
Status) and has "Levels", "Banded (otherwise smooth)", "Color scale" and "Mesh overlay",
and, for a transient run, a "Step" slider and spin box, a "Time" box and "Play".

The Results menu has: Add contour, Add vector plot, Probe, Play animation, Nodal
history..., Path plot..., Finish path plot, Cancel path plot, Heat-flow history, Energy
balance and Flow results.... Nodal history and Path plot ask you to pick nodes or path
points in the viewport first. Each path point is drawn as a numbered marker and the points
are joined by a line; Cancel path plot removes them, and after Finish they stay until the
chart window is closed. Probe shows x, y and the value at the pixel you click, and each click inside the model
leaves a marker with its value and unit; the markers follow the displayed step, field and
units, and are cleared when you turn Probe off. It is
a rough check; use the CSV export for exact values.

File > Export has: Viewport image..., Nodal results (CSV)..., ParaView (VTU)...,
Animation (GIF)... and Report (HTML).... The CSV has the columns `step, time, node, x, y, T,
qx, qy` in SI units. Charts have their own export.

The report is one HTML file that opens in any browser and needs no other files. For the
displayed step it shows the model, the materials, the mesh and its quality, every load with
its values, the solver settings and step counts, and the energy balance. It also has a
contour plot of the displayed field, and for a transient run the heat-flow history.

## Which things are out of date

An edit makes parts of the work out of date. What is affected depends on what you changed:

| You changed | Out of date |
|---|---|
| the geometry | geometry, mesh and results |
| the mesh settings, the model type, or a selection the mesh settings use | mesh and results |
| anything else (loads, materials, analysis settings, ...) | results only |

How it shows:

- The summary of each result in the tree reads "contour · out of date", the viewport title
  ends " · out of date", and the result panel shows "These results are out of date: the model
  changed since the solve" followed by the list of changes (for example the old and new value
  of a heat-transfer coefficient). Undoing the change makes the results current again.
- Chart windows are marked "(out of date)" in their title when new results arrive.
  They are not redrawn.
- Solve is not available while the geometry or the mesh is out of date. Press Rebuild
  geometry and Generate mesh first (the status bar says "The mesh is out of date;
  regenerate it before solving").

Changing the display units ([Units](units.md)) makes nothing out of date.

Selection tags and the selection named "all" are caches of the build. A rebuild is not an
undo step and does not make anything out of date by itself.

If you edit the model while a solve is running, the solve uses its own copy. When it
finishes, the results are stored but marked out of date. If the mesh or the build was
replaced meanwhile, the results are discarded (the file stays on disk).

## Undo and redo

Edit > Undo and Edit > Redo (Ctrl+Z, Ctrl+Y). Every applied property change, every geometry
operation, every change of units and every tree action (add, rename, duplicate, delete) is
one undo step.

## Units

Tools > Units... chooses the units numbers are shown and typed in. The default is SI with
temperatures in kelvin. See [Units](units.md). Press Enter after typing, and remember that
100 degC is 373.15 K when the units are K.

## Examples

File > Examples opens ready-made models: the verification cases V-01 to V-21, V-27 to
V-29, V-32 and V-35 ([Verification](verification.md)). They are good starting points: open
one, look at how it is set up, change it.

## Files and where results are stored

- File > New, Open..., Save, Save As... and Recent files work as usual. The model is a
  JSON file (`.tfea`).
- Results are stored in an HDF5 file named after the model with `.h5` added:
  `model.tfea.h5` beside `model.tfea`. A model that was never saved writes its results to a
  temporary folder.
- When you open a saved model, its results file is attached again once a mesh exists, so
  press Generate mesh after opening to see the results.
- The results file also holds a copy of the model it was solved from.

## Continuing a transient run

A transient run can be continued from its last stored step to a later end time. The new
steps are added to the same results file.

1. Raise "End time" in Analysis Settings. (A run that was cancelled can be continued
   without raising it.)
2. Choose Solve > **Continue transient run**.

On the command line: `thermalfea solve model.tfea --restart`. From Python:
`api.solve(model, mesh, path=..., restart=True)`.

What to know:

- The mesh, the materials, thicknesses and material angles of the parts, and the
  streams must be the same as in the results file, or the restart is refused and the file
  is left unchanged. So is a steady solution, a last step that did not converge, and an end
  time the file has already reached.
- Loads and solver settings may change. The continued steps use the current model, which
  replaces the model stored in the results file. A load that you changed takes effect from
  the restart time.
- With a fixed time step the continued run repeats an uninterrupted run (to round-off in
  the linear case). With adaptive stepping the controller's history is not stored, so the
  steps differ from those of an uninterrupted run within the time-stepping tolerance.

## From the command line

Build and save the model in the window (File > Save) or from a script, then:

```
thermalfea info model.tfea
thermalfea solve model.tfea
```

`info` prints counts and a quality line. `solve` prints one progress line per step and a
text summary, and writes `model.tfea.h5` ([Installation](installation.md#the-command-line)
has the options and exit codes). Results can then be read by the Python API or opened in the
window.

## From Python

Everything the window does is available from `thermalfea.api`. This script builds a plate,
solves it, prints the summary and saves the model:

```python
from thermalfea import api
from thermalfea.model.bcs import Convection, FixedTemperature

model = api.new_model("planar", name="plate")
geo = api.Geometry(model)
geo.rectangle(0.0, 0.0, 0.2, 0.1)
built = api.build(model)
api.select_curves(model, built, name="bottom", where=lambda c: abs(c.center[1]) < 1e-9)
api.select_curves(model, built, name="top", where=lambda c: abs(c.center[1] - 0.1) < 1e-9)
api.assign_region(model, "all", material="Aluminum, Alloy 2024-T6")
model.bcs.append(FixedTemperature("base", "bottom", T=373.15))
model.bcs.append(Convection("cooling", "top", h=25.0, T_inf=293.15))
model.mesh_settings.global_size = 0.01
mesh = api.mesh(model, built)
results = api.solve(model, mesh, built=built)
print(api.summary(results))
api.save(model, "plate.tfea")
```

All values are SI, with temperature in kelvin. Other calls: `api.load`, `api.plot_contour`,
`api.plot_vectors`, `api.plot_path`, `api.plot_history`, `api.export_csv`,
`api.export_vtu`, `api.export_animation` and `api.htc`. Without `path=`, `api.solve` writes
the results to a temporary folder; `api.results_path(model_path)` gives the name beside a
model file. Pass `built=` to `api.solve` so that the model is validated first.
