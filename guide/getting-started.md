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
  View > Summary column hides the second column. A small warning mark on an item means that
  Validate would complain about it (a load with no selection, a part with no material, a
  material with a property not set); hover over it to read the message. The marks follow
  your edits.
- **Properties** dock (below it): the panel of the item selected in the tree.
- **Viewport** (centre): the geometry, the mesh, load symbols and result plots.
- **Messages** dock (bottom): the solver log. An **Issues** dock is tabbed with it and lists
  the findings of validation. The View menu shows and hides the docks, and switches the
  load symbols on and off ("Load symbols"), the part names on and off ("Part names"), the
  load values on and off ("Load values"), and chooses how the viewport is colored
  ("Color by": Part, Material or None). View > **Stretch** draws a slender model with one
  axis stretched (see below).
- **Toolbar**: the selection modes None, Point, Boundary, Part, Node and Element, and
  "Fit view" (the key F). In a 2D model a boundary is a curve and a part is a surface.

Menus: File, Edit, View, Geometry, Mesh, Solve, Results, Tools, Help.

### Selecting in the viewport

A click selects the item under the pointer (8 pixels of tolerance). Ctrl-click adds to or
removes from the selection. A click on nothing clears it. A drag longer than 4 pixels
selects by a box: boundaries must lie wholly inside the box, parts are chosen by their
bounding box, elements by their centre. Changing the selection mode clears the selection.
The mouse wheel zooms and the middle button pans.

**Stretching the view.** A 1.2 mm wall over 2 m cannot be seen at true scale. Choose View >
Stretch > "Stretch y × 20" (or x, or another factor from 2 to 100) to draw one axis longer;
in an axisymmetric model the axes are called r and z. The view says "Stretched y × 20: not
true scale" in its corner. View > Stretch > True scale goes back. Picking follows what you
see.

### Picking in the view

Every pick in the window works the same way: a selection field's New and Edit icons, the
Selections panel's Add and Remove, a stream's path, the points and nodes of a result item,
the probe (which reports in the status bar), and the geometry dialogs.

- A yellow strip in the panel shows what to click and counts what you have picked ("2
  boundaries picked"). It is there only while you pick.
- What you have picked is marked in the view.
- The toolbar switches itself to the kind of entity the pick needs (a field that accepts
  boundaries or points starts in Boundary) and switches back afterwards. You do not choose
  the mode.
- Ctrl-click adds or removes one entity. **Enter** confirms (the strip's button, for example
  "Create and use"), **Esc** cancels and changes nothing. Starting another pick cancels the
  running one: only one pick runs at a time.

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
| Results | the result items: contour plots and vector plots after a solve, and the nodal histories and path plots you add |

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
it, its selections and the loads on it. A single click (while no pick is running)
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
(Constant, Table or Expression) above its value; leave it on Constant for a constant. The
conductivity is two fields: "Conductivity (along axis)" is the conductivity of an isotropic
material, or along the material axis of a directional one; "Conductivity (across axis)" is
the conductivity at right angles to it and its mode box starts at "Isotropic", which means
the material has the same conductivity in every direction. Choose Constant and type a value
only for a directional material (laminations, fibers); each part that uses it then sets
the direction of the axis with its Material angle.
Tools > Material library... opens the built-in library ([Materials](materials.md)).
To start from a library material, select the material, type part of a name in the "From
library" box (built-in entries first, then your own marked "(user)"), and press Use library
values: the conductivity, density, specific heat and phase change are copied in one undo step
and the material keeps its name, so its parts stay assigned. The summary of the material
reads "<entry> · library", or "<entry> · edited" after you change a value, or "k ... · custom"
for a material that never came from the library; the panel shows the source, and **Restore
library values** brings an edited material back.

Right-click Parts and choose Add part. A part "Part 1" appears; its panel has the fields
Name, Selection, Material, Thickness and, only for a material with a conductivity across the
axis, Material angle. Rename the part (for example "Plate").

**The selection field.** Every load, part, contact, stream and mesh setting that applies to
geometry does so through a named selection, and every such field looks the same: one row
with the role as its label ("Boundary", "Part", "Point"; "Selection" in a part's own panel),
a dropdown of the model's selections that fit with their sizes ("cooled · 1 boundary",
"plate · 2 parts"), and the icons below. A new field shows "(none)".

- **Choosing another selection from the dropdown does not change the object yet.** The
  dropdown gets a colored border, a note says "Not applied", and two icons appear: the
  check mark **Update** (apply the choice; one undo step) and the arrow **Revert** (go
  back to the stored selection). Leaving the panel with a change waiting drops it, and the
  status bar says "Selection change not applied".
- **The crosshair icon (New selection)** picks a new selection in the view, as described
  under "Picking in the view". The toolbar goes to the right mode by itself (Boundary for
  a load, Part for a part). Click the entities (Ctrl-click for more), type a name in the
  Name box (it starts empty; the button stays disabled until something is picked and the
  name is valid and unused) and press **Create and use** (or Enter). The selection is made
  and the field uses it in one undo step. A name that is already used is refused with a red
  message under the box.
- **The pencil icon (Edit)** changes the entities of the field's current selection. The strip
  says which other objects also use it. **Save** rewrites the selection; **Save as new**
  stores the picked entities under the name you type and uses that instead, leaving the
  other users alone.
- A field that holds several selections (a stream's walls, the mesh's structured parts)
  lists them, each with a pencil and a cross to remove it, above the same row. The dropdown
  there reads "(add a selection…)"; adding or removing waits for Update too.

Choose the Material, and set the Thickness (planar models) and the Material angle if
needed. Parts and materials have a color swatch; the viewport fills use the same colors
(View > Color by). View > Part names writes the part names in the view.

The Selections section lists every named selection with its users. Click one to highlight
it. Its panel shows Name (renaming it renames it wherever it is used), Kind, Entities,
Bounds parts and Used by (each user is a link), and has the buttons "Add from viewport",
"Remove from viewport" and Delete (not available while the selection is used). The first
two start a pick like the others, with the strip buttons "Add" or "Remove". With the
focus on the tree, Page Down and Page Up step through the selections.

### 3. Loads and boundary conditions

Right-click Loads & Boundary Conditions, choose Add, then one of:

Add Fixed Temperature, Add Heat Flux, Add Heat Flow, Add Heat Generation,
Add Heat Power, Add Convection, Add Correlation Convection, Add Radiation to Ambient,
Add Symmetry, Add Adiabatic.

Each load has a selection field that works as described for parts. Its label is the role:
"Boundary" (a Fixed Temperature says "Boundary or point"; Heat Generation and Heat Power
say "Part"). Press the crosshair icon, click the boundaries, type a name such as "base" or
"cooled" and press Create and use. Selecting a load in the tree highlights its boundaries,
and the viewport shows load symbols. The labels of the fields carry their symbols:
"Fluid temperature T∞", "Heat-transfer coefficient h", "Emissivity ε", "Temperature T".

- **Press Enter after typing a number.** The value is applied when you press Enter or leave
  the field. Each applied change is one undo step. (A change of selection is the exception:
  it waits for the Update icon, as above.)
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
  gives a value and logs one warning. The correlations are listed by their readable names
  (for example "Vertical plate (Churchill–Chu)"), not by their identifiers. The panel keeps the
  correlation, fluid, fluid temperature T∞, velocity and extra inputs in its main box;
  the characteristic length, face direction, wall temperature and multiplier are under the
  collapsed line "More" (its title counts the values you changed).
- A Contact (right-click Contacts, Add contact; while the model has none, right-click the
  dimmed line "Contacts · Flow · Enclosures") starts with an empty selection ("Interface
  boundaries") and a conductance of 0, which you must set. A temperature-dependent
  conductance is refused.
- Streams are under Flow: right-click the node Streams and choose Add stream (while the
  model has no stream, use the dimmed line "Contacts · Flow · Enclosures"). The Network
  node is also under Flow. Results > Flow results...
  shows the fluid temperature along the stream. A stream's panel has four boxes: "Fluid and
  flow" (fluid, mode, walls, inlet temperature, mass flow), "Cross-section", "Path" and
  "Heat-transfer coefficient". The last one is collapsed: under its "More" line are the wall
  roughness, the number of cells, the Nusselt option, the coefficient multiplier and the
  coefficient override. The walls are a list of boundary selections, handled like the
  selection fields above. The Path box has "Pick path", which starts a pick: click the
  points from the inlet to the outlet (each is drawn as a numbered marker), then press
  "Use path" (Enter) when you have at least two. "Clear path" empties it. A new stream's
  mass flow box starts at its empty mode "From network" with the number box disabled; choose
  **Constant** in the mode box, then type the value and press Enter (leave it on "From
  network" only when a flow network supplies the flow).
- Tools > HTC calculator... evaluates a correlation at single values without a model.
  For the internal-duct correlation it also asks for the cross-section (default circular).

### 4. Mesh

Click the Mesh node. The panel is a column of framed boxes, each with a title and a
one-line description:

- **Element size:** "Global element size", and the tables "Boundary sizes" and "Point sizes".
- **Element type:** "Element order" (Linear (1) or Quadratic (2)) and "Element shape"
  (Triangles or Quadrilaterals (quad-dominant)). Under the collapsed line "More" are the
  "Algorithm" and the "Smoothing passes"; the title counts the values you changed.
- **Structured mesh:** the list "Structured parts" and the table "Boundary divisions".
- **Refinements:** a table of smaller elements near a boundary or point.
- **Statistics and quality** (after meshing).

Boundary sizes, point sizes, boundary divisions and the refinements are small tables, not
typed text. Each row has a dropdown of the model's selections that fit (boundaries or
points, with their sizes), the value box with its unit ("Element size [m]", or "Elements"
for a count), and a cross to remove it. Press **+ Add** below the table to add a row: choose
the selection, type the value and press Enter (or the check mark). Press **New…** to pick a
new selection in the view (as for a selection field, ending with "Create and use"); a row
for it is added and you type its value. Choosing another selection in an existing row waits
for the check mark (Update) or Enter in the row's value box, which applies the whole row;
the arrow (Revert) drops the change. The row you are editing is highlighted in the view.
Press **Generate mesh** (or use Mesh > Generate mesh). The status bar
reports the number of nodes and elements and the mesh is drawn in the viewport.

### 5. Analysis settings and initial condition

Click Analysis Settings. "Geometry type" is `Planar` or `Axisymmetric`. In an axisymmetric
model x is the radius and the axis x = 0 is drawn in the viewport; parts then have no
Thickness. Changing it is one undo step and marks the mesh and the results out of date.
"Analysis type" is Steady or Transient. The panel is a column of framed boxes:

- **Analysis:** "Geometry type" and "Analysis type". A steady analysis shows only this box
  and the Convergence box.
- **Time** (transient): "End time".
- **Time stepping** (transient): "Adaptive time step" and "Largest time step". Under the
  collapsed line "More" are "Initial time step", "Smallest time step", "Time-step
  tolerance" (shown only with an adaptive step) and "Largest temperature change per
  step". An empty optional box says what empty means in grey: the initial step is
  "suggested from the mesh", the largest step and the largest temperature change are "no
  limit".
- **Integration (advanced)** (transient, collapsed; its title names the method): "Time
  integration" is a choice of Backward Euler (θ = 1, default), Galerkin (θ = 2/3) and
  Crank-Nicolson (θ = 1/2), and "Lumped capacitance". The model stores the number θ; a
  value set elsewhere, from a script, shows as "Custom (θ = …)". Open the box to change it.
- **Results to store** (transient): "Output steps" (All steps, Every n-th step, At given
  times), and then "Store every n-th step" or "Output times" as the choice needs.
- **Convergence (advanced)** (collapsed): "Residual tolerance", "Temperature tolerance",
  "Maximum iterations" and "Line search". Its title counts the values that are not the
  default, for example "Convergence (advanced) · 2 changed".

Validate and Solve are below the boxes.

Click Initial Condition for a transient analysis. "Kind" is Uniform, Expression of x and y,
Per part, or From a results file, and the panel shows only the rows of the chosen kind.
Uniform and Expression show "Temperature". Per part shows "Temperature per part", a table
like those of the Mesh panel: one row per part selection (the dropdown lists the part
selections, "plate · 2 parts"), the temperature, and the same **+ Add**, **New…**, check
mark, arrow and cross. From a results file shows "Results file", a box with a folder icon
beside it that opens a file chooser for an `.h5` file; the box can also be typed in. The
initial state (step 0) is always stored. Validate refuses a results file that is the one the
solve will write (see "Files and where results are stored" below).

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

**Result items.** Contour plots, vector plots, nodal histories and path plots are items
under Results, saved with the model. Each has its own panel, and right-click > Rename,
Duplicate and Delete work on all of them (adding, deleting and changing one is an undo step).
A contour or vector plot says "current" or "out of date" in the tree. Each item has a toggle that hides what it draws
without deleting it and keeps its settings: the checkbox **Show in the view** in the Display
box of a contour or vector plot, "Show the nodes in the view" for a nodal history and "Show
the path in the view" for a path plot. A new solve redraws the items and their charts. The
panel of a contour also has "Banded", "Mesh overlay", "Mark minimum and maximum", the
animation controls and a "Probe" box.

The Results menu has: Add contour, Add vector plot, Probe, Play animation, Nodal
history..., Path plot..., Heat-flow history, Contact-heat history, Mean-h history, Energy
balance and Flow results.... The heat-flow and energy charts need no input and are windows,
which redraw after a new solve.

- **Nodal history...** adds an item "Nodal history 1" with the nodes that are selected in the
  view. If none are, its panel starts the pick at once. The panel lists the nodes ("node 412
  · (0.6, 0.2) m", each with a cross), the button **Pick nodes** (a pick in Node mode that
  starts from the item's nodes; Ctrl-click adds or removes one; **Use nodes** or Enter
  stores them), the quantity and **Plot**. The nodes are marked in the view with their
  numbers ("node 412"), the same numbers as the chart's legend.
- **Path plot...** adds an item "Path 1" whose panel has two boxes. **Path** ("Where
  the values are taken, from A to B"): "Defined by" Two points (type A and B or press the
  crosshair beside each; "Snap A and B to the nearest nodes"; "Samples"), Along boundaries
  (a Boundary selection field whose curves join end to end; the samples are the mesh nodes
  on them) or Points (a list of points typed or picked with "Add points"); and "Run from B
  to A". **Plot**: "Quantity", "Times" (empty: the displayed step; several times are
  overlaid on one chart), "Horizontal axis" (distance along the path, x or y; r or z in an
  axisymmetric model), "Show the path in the view" and **Plot**. A selected path is drawn in
  the view with its ends labeled A and B. There is no longer a Finish path plot or Cancel
  path plot in the menu.
- **Probe** shows x, y and the value at the pixel you click, and each click inside the model
  leaves a marker with its value and unit; the markers follow the displayed step, field and
  units, and are cleared when you turn Probe off. While it is on, the status bar says
  "Probe: click in the view to read values · Esc to stop". It is a rough check; use the CSV export
  for exact values.

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
- The charts of nodal histories and path plots, and the heat-flow and energy-balance
  charts, are drawn again when new results arrive. Other chart windows are marked "(out of
  date)" in their title and are not redrawn.
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
