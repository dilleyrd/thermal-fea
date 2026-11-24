# GUI walkthrough: build V-10 and V-17 from scratch

For the M8.G human gate: *a person builds V-10 and V-17 from scratch in the GUI following
the tutorial text, and lists every point of friction.* This file is that text. Follow it
step by step, compare each answer with the number given, and write every place where you
got stuck, guessed, or were surprised into the friction log at the end.

Every menu name, button text, field label and tree node below was read from the source
(tasks M11.49 to M11.63 changed many of them), and both procedures were run end to end by a
script that drives the same widgets (the V-10 run is `tests/gui/test_end_to_end.py`). The
tree blocks and the summary texts below were taken from such a run on 2026-11-24. A page
with the steps, the screenshots of an earlier run and a friction log is at
https://claude.ai/artifact/AVKWHDY1Pa6YZ22go6weAH (it predates the new names). No person
has used the window yet, so ease of use is exactly what the gate is meant to find.

## 0. Starting the GUI

From the project folder in a terminal:

```
.venv\Scripts\python.exe -m thermalfea.gui.app
```

The main window has a model tree ("Model" dock, top left), the property panel ("Properties"
dock, below it), the viewport in the middle, and a "Messages" dock at the bottom (the solver
log is written there; an "Issues" dock is tabbed with it). Menus: File, Edit, View, Geometry,
Mesh, Solve, Results, Tools, Help. The toolbar holds the selection modes (None, Point,
Boundary, Part, Node, Element) and a "Fit view" button. In a 2D model **Boundary** picks
curves and **Part** picks surfaces.

The model tree has two columns. The first column is the name, the second is a summary of the
item (for example the conductivity of a material, or "2 boundaries · convection Convection 1"
for a selection). View > **Summary column** hides and shows the second column. The title of
the Model dock follows the model: "Model — Untitled · planar · K" for a new model, and
"Model — Untitled · planar · t 1 m · K" once the parts have a thickness (the last item is the
temperature unit).

Things to know before you start:

- **Temperatures are entered in kelvin** unless you change the units with Tools > Units...
  (the steps below assume the default, SI with K). 100 degC is 373.15 K and 0 degC is
  273.15 K.
- **Press Enter after typing a number** in a property field. The value is applied when you
  press Enter or leave the field, and each applied change is one undo step (Edit > Undo).
- Property fields that are physical functions (conductivity, temperature, heat-transfer
  coefficient, ...) show a mode box (Constant, Table, Expression) above the value. Leave it
  on "Constant" and type the number.
- **Name every selection yourself.** Each time you pick entities, the "Selection" field has
  a "New name" box that is pre-filled with an unused suggestion such as "Convection 1
  selection". Type a meaningful name over it before you press Apply. A name that is already
  used is refused with a red message under the buttons.
- The View menu has: Fit view, the docks, Summary column, Load symbols, Region names, Load
  values and a "Colour by" submenu (Part, Material, None). The default is Part: each part is
  filled with its own colour in the viewport, and the same colour is the swatch beside the
  part in the tree.
- The example models are also under File > Examples ("V-10 - NAFEMS T4 ..." and
  "V-17 - slab cooled by convection ..."). Open them after your own build to compare.

## 1. V-10: NAFEMS T4 (steady, 2D)

**Problem** (`docs/verification.md`, `examples/v10_nafems_t4.py`): rectangle 0.6 m (x) by
1.0 m (y); conductivity k = 52 W/(m K); bottom edge 100 degC; left edge adiabatic; right and
top edges convection with h = 750 W/(m^2 K) to 0 degC.

**Expected answer:** temperature at the point (0.6, 0.2) = **18.3 degC**, accepted within
**0.15 degC** at element size 0.025 (the script gives 18.206 degC with the default triangles).
The energy balance of a linear steady case must close to better than 1e-8 (V-34).

### 1.1 Geometry: two rectangles

The check point (0.6, 0.2) must be a mesh node. The GUI cannot place a mesh node at a given
point, so draw the plate as two stacked rectangles that meet at y = 0.2; the shared edge puts
a vertex, and so a node, at (0.6, 0.2). This is what the example script does too.

1. Geometry > **Rectangle...** opens a dialog titled "Rectangle".
2. Type x = `0`, y = `0`, Width = `0.6`, Height = `0.2`. Leave "Corner radius" at 0 and "Id"
   empty (an id is generated). Press **OK**.
3. Geometry > **Rectangle...** again: x = `0`, y = `0.2`, Width = `0.6`, Height = `0.8`.
   Press **OK**.
4. The geometry is rebuilt by itself after each OK (the status bar says "Building
   geometry..." and then "Geometry rebuilt"). The model tree node "Geometry" now lists
   `rectangle1` and `rectangle2`; their summaries read "rectangle 0.6 × 0.2 m" and
   "rectangle 0.6 × 0.8 m".
5. View > **Fit view** (or the key F). The viewport is fitted only when the first shape
   appears, so the second rectangle is partly out of view until you do this.
6. Click `rectangle1` in the tree: the surface it made is highlighted in the viewport. A
   step highlights what it owns.
7. *Optional.* Rename the steps: right-click `rectangle1` > **Rename** (or edit the name in
   place), type `lower strip`, press Enter; rename `rectangle2` to `upper strip`. The
   geometry is rebuilt, and any later step that refers to the renamed one (a boolean) follows
   the new name. The tree below uses these names; if you skip this step read `rectangle1`
   and `rectangle2`.

You should see a 0.6 by 1.0 plate with a line across it at y = 0.2 (two surfaces, seven
curves). The tree also gets a "Selections" entry "all" ("2 parts · unused"), made by the
program.

### 1.2 Loads: pick the boundaries, then set the values

The three conditions need named boundary selections. You create each selection from the
condition's own panel, and you give it a name.

**Fixed temperature (bottom edge, 100 degC):**

1. In the model tree, right-click **Loads & Boundary Conditions**. Choose **Add** >
   **Add Fixed Temperature**. A node "Fixed Temperature 1" appears and its panel
   ("Fixed Temperature: Fixed Temperature 1") opens in Properties.
2. In the panel's "Selection" field press **Pick in viewport**. In the toolbar choose
   **Boundary** (the panel starts in Point mode, because a fixed temperature may also be put
   on points).
3. Click the bottom edge of the plate (y = 0). The status line under the buttons says
   "1 boundary picked". The "New name" box holds "Fixed Temperature 1 selection". Replace
   it with `base` and press **Apply**. The field now shows "base".
4. Press **Pick in viewport** again to switch picking off.
5. In "Temperature" type `373.15` and press Enter (unit shown: K).

**Convection (right and top edges, h = 750, 0 degC):**

1. Right-click **Loads & Boundary Conditions** > **Add** > **Add Convection**.
2. Selection: **Pick in viewport**, toolbar **Boundary**. The right edge is two curves (split
   at y = 0.2): click the lower right edge, then hold **Ctrl** and click the upper right edge
   and the top edge. The status line says "3 boundaries picked". Type the name `cooled`
   in "New name", press **Apply**, then switch **Pick in viewport** off.
3. "Heat-transfer coefficient": `750`, Enter (unit W/(m^2 K)).
4. "Fluid temperature": `273.15`, Enter (K).

**Adiabatic (left edge):**

1. Right-click **Loads & Boundary Conditions** > **Add** > **Add Adiabatic**.
2. Selection: **Pick in viewport**, toolbar **Boundary**, click the lower left edge, Ctrl-click
   the upper left edge ("2 boundaries picked"), name `left side`, **Apply**, switch picking
   off.

The viewport now shows load symbols for the three conditions. Selecting a condition in the
tree highlights its boundaries.

**A name that is used is refused.** Try it once: add another Adiabatic, pick any edge, type
`base` in "New name" and press **Apply**. A red message under the buttons says "the selection
name 'base' is already used" and nothing is stored (no undo step). Then press Edit > Undo
once to remove the extra Adiabatic condition (the "Add Adiabatic" step). To give a field a
different set of entities later, pick again and type the field's own selection name in
"New name": it is replaced as long as nothing else uses it.

### 1.3 Material and part

1. Right-click **Materials** > **Add material**. A material "Material 1" appears; all its
   properties start at 0, which means "not set yet". It has a colour swatch beside it.
2. In its panel set "Thermal conductivity" (mode Constant) to `52` and press Enter. Density
   and specific heat do not affect a steady answer; they may stay at 0. (A conductivity left
   at 0 is refused by Validate: "has a conductivity that is not positive".) The summary
   column of the tree now reads "k 52 W/(m K) · custom".
3. Right-click **Parts** > **Add part**. A part "Part 1" appears and its panel ("Part")
   opens. Its fields are "Name", "Selection", "Material", "Thickness" and "Material angle".
   "Material" already holds "Material 1". Replace "Name" with `Plate` and press Enter (or
   right-click the part in the tree > **Rename**).
4. In the "Selection" field: **Pick in viewport**, toolbar **Part**, click inside the lower
   rectangle, Ctrl-click inside the upper one ("2 parts picked"). The "New name" box holds
   "Plate selection"; type `plate` and press **Apply**, then switch picking off.
   "Thickness" stays 1 and "Material angle" 0.
5. The part's swatch colour is the colour of its surfaces in the viewport. Switch View >
   **Colour by** to Material and back to Part to see the viewport follow.

### 1.4 Mesh

1. Click the **Mesh** node in the tree. The panel "Mesh" opens.
2. "Global element size": `0.025`, Enter. Leave "Element order" 1, "Element shape" tri.
3. Press **Generate mesh** (or Mesh > **Generate mesh**). The status bar reports about
   "Mesh generated: 1210 nodes, 2290 elements". The mesh is drawn in the viewport.

### 1.5 Expected model tree (before the solve)

The tree should read like this. The first column is the item and the second, after the
bar, is its summary (the bar is only drawn here to separate the columns). Selections are
listed in alphabetical order, with "all" last. Geometry names are those of the optional
rename.

```
Model — Untitled · planar · t 1 m · K          (title of the Model dock)

Geometry                       | 2 steps
  lower strip                  | rectangle 0.6 × 0.2 m
  upper strip                  | rectangle 0.6 × 0.8 m
Parts                          | 1
  Plate                        | Material 1 · 2 surfaces · t 1 m
Selections                     | 5
  base                         | 1 boundary · fixed temperature Fixed Temperature 1
  cooled                       | 3 boundaries · convection Convection 1
  left side                    | 2 boundaries · adiabatic Adiabatic 1
  plate                        | 2 parts · part Plate
  all                          | 2 parts · unused
Materials                      | 1
  Material 1                   | k 52 W/(m K) · custom
Mesh                           | T3 · 0.025 m · 1 210 nodes · 2 290 elements · current
Initial Condition              | uniform 293.15 K
Loads & Boundary Conditions    | 3
  Fixed Temperature 1          | Fixed Temperature · T 373.15 K → base
  Convection 1                 | Convection · h 750 W/(m^2 K), T_inf 273.15 K → cooled
  Adiabatic 1                  | Adiabatic → left side
Contacts · Flow · Enclosures   | none          (one dimmed line)
Analysis Settings              | steady
Results
```

The order of the top-level sections is: Geometry, Parts, Selections, Materials, Mesh,
Initial Condition, Loads & Boundary Conditions, then "Contacts · Flow · Enclosures" (one
dimmed, italic line while the model has no contact, stream, network or enclosure), then
Analysis Settings and Results. Right-click the dimmed line: the menu offers **Add contact**,
**Add stream** and **Create network**. (Do not use it here.) After one of these is added the
line is replaced by the three sections Contacts, Flow and Enclosures.

The Selections section (described under "Selections" in 1.8) shows every named selection
with its count and its users. The "plate" selection shows "part Plate" because the part
uses it.

### 1.6 Solve

1. Solve > **Validate**. The status bar must say "Validation: no issues" (or list only
   warnings; any error must be fixed first).
2. Solve > **Solve**. A window titled "Solving" shows the progress and ends with a
   "Finished" state; it stays open until you close it. A linear steady case takes a moment.
3. A node "Temperature 1" appears under **Results** in the tree, with the summary
   "contour · current", and the temperature contour is drawn in the viewport. (The contour
   starts banded with 12 levels. Click the node to see its panel. It starts with a header of
   four lines: "Analysis: steady", "Mesh: T3 · 1 210 nodes · 2 290 elements", "Results
   written <date and time>" and "Status: current". Then "Field", "Levels", "Banded
   (otherwise smooth)", "Colour scale" and "Mesh overlay".)

### 1.7 Compare with the benchmark

- **The number.** File > Export > **Nodal results (CSV)...**, choose a file name. Open the
  CSV in a spreadsheet. Columns are `step,time,node,x,y,T,qx,qy` with T in kelvin. Find the
  row with x = 0.6 and y = 0.2. T minus 273.15 must be between 18.15 and 18.45 degC (target
  18.3, tolerance 0.15). Expect about 291.356 K (18.206 degC).
- **A quick look.** Results > **Probe**, then click the viewport as close as you can to the
  right edge at the line y = 0.2. The status bar shows x, y and the temperature in K, and
  each click leaves a marker with its value (cleared when the probe is turned off). This is
  limited by the pixel you hit and by the point lying on the boundary, so use it only as a
  rough check; the CSV is the exact one.
- **Energy balance.** The "Messages" dock shows the solver log. It lists the heat entering
  through each condition (Fixed Temperature 1 about +10396 W, Convection 1 about -10396 W)
  and "relative imbalance". The value must be below 1e-8; it is about 1e-14.
  Results > **Energy balance** plots the heat flows against time and lists every stored step
  in a table (with the imbalance; select cells and press Ctrl+C to copy them). A steady
  result shows the table only.

### 1.8 What to check in this review (V-10)

Do these after the solve; none of them changes the answer.

1. **Toolbar.** The buttons read None, Point, Boundary, Part, Node, Element. There is no
   "Curve" or "Surface" button.
2. **Tree and dock title.** The section order and the summaries are as in 1.5. The dock
   title reads "Model — Untitled · planar · t 1 m · K". View > **Summary column** hides the
   second column and shows it again. The dimmed "Contacts · Flow · Enclosures" line has the
   three menu entries named in 1.5.
3. **Geometry.** Clicking a step highlights what it owns. Renaming a step (right-click >
   **Rename**, or in place) keeps the model valid. Undo restores the old name.
4. **Parts.** The part is called "Plate"; the panel fields are Name, Selection, Material,
   Thickness, Material angle. The part and the material have colour swatches. View >
   **Colour by** Part, Material and None change the viewport fills.
5. **Selection field.** After picking, the status line reads "1 boundary picked" or
   "3 boundaries picked" (and "2 parts picked" for the part). The "New name" box is
   pre-filled with a suggestion. A used name is refused in red. Repeating the field's own
   name replaces its entities.
6. **Selections section.** Click "cooled" in the tree: its boundaries are highlighted. Its
   panel shows "Name" (`cooled`), "Kind" ("Boundary · 3 curves"), "Entities" (tag numbers
   and "total length 1.6 m"), "Bounds parts" ("Plate"), "Used by" (a button
   "convection Convection 1": press it and the tree jumps to that load), the buttons "Add
   from viewport" and "Remove from viewport", and "Delete" (greyed out while the selection
   is used; the tooltip names the users). Rename it to `cooled sides` in the panel: the
   load summary then reads "→ cooled sides" (users follow). Undo it. With the focus on the
   tree, Page Down and Page Up step to the next and previous selection.
7. **Materials.** The summary is "k 52 W/(m K) · custom" and the source line in the panel
   reads "Custom values". Optional: add a second material, type part of a name in "From
   library", press **Use library values**: the summary reads "<entry> · library" and the
   source line "Values from the built-in library: <entry>". Change its conductivity: the
   summary reads "· edited", and **Restore library values** is enabled and brings it back.
   Then Edit > Undo until "Material 2" is gone.
8. **Form labels.** Nothing in V-10 uses them (see V-17 for "Boundary divisions" and
   "Structured parts"); open the Initial Condition panel and read "Temperature per part" if
   you set its kind to `per_region`, then set it back to `uniform`.
9. **Results.** The result node reads "contour · current" and its panel has the four-line
   header of 1.6. The viewport title reads "Temperature, steady state". Do 1.9 below to see
   the out-of-date state.
10. **Hover and inspect.** Choose **Boundary** in the toolbar (nothing may be picking: all
    "Pick in viewport" buttons off) and move the pointer over the bottom edge. A tooltip
    shows, for example, "Boundary 1", "part: Plate", "in: base" and "fixed temperature Fixed
    Temperature 1" (the tag number may differ). Click the edge once: the same report appears
    in the status bar (for 30 seconds), and the tree items it names (Plate, base, Fixed
    Temperature 1) are shown in bold. Click empty space to clear it. In **Part** mode the
    tooltip names the part and its selection ("in: plate"); in **Point** mode the vertices.
    While a "Pick in viewport" button is on, a plain click picks and does not inspect.
11. **View menu.** "Region names" toggles labels with the part names ("Plate") in the
    viewport; "Load values" toggles the values next to the load symbols (on by default).

### 1.9 Extra checks (optional, they test the editing machinery)

- Change "Heat-transfer coefficient" of the convection to `800`. The status of the results
  becomes "out of date": the summary of "Temperature 1" reads "contour · out of date", the
  viewport title reads "Temperature, steady state · out of date", and the panel of the
  result shows "Status: out of date (1 change)" and a yellow box: "These results are out of
  date: the model changed since the solve (1)." and the line "Load Convection 1:
  Heat-transfer coefficient 750 W/(m^2 K) → 800 W/(m^2 K)". The mesh stays valid (its
  summary still ends "current"). Edit > **Undo** returns it to 750 and the results are
  "current" again.
- Change "Global element size" to `0.03`: now the mesh is out of date (its summary ends
  "out of date") and Solve is greyed out until you press **Generate mesh** again. Undo it.
- File > **Save As...** `v10.tfea`; File > **New**; File > **Open...** `v10.tfea`. The
  geometry is rebuilt by itself. After you press **Generate mesh**, the results saved beside
  the model (`v10.tfea.h5`) are attached again, if you solved after saving.

## 2. V-17: slab cooled by convection (transient, 1D)

**Problem** (`docs/verification.md`, `examples/v17_slab_convection.py`): a slab of half
thickness L = 0.05 m, symmetric about x = 0, initial temperature 400 K, convection at
x = L with h = 500 W/(m^2 K) to 300 K. Material: k = 50 W/(m K), density 7800 kg/m^3,
specific heat 500 J/(kg K) (the defaults of the verification document). It is modelled as a
strip 0.05 m long and 0.005 m high (L/10); the top and bottom are insulated, the left side is
the symmetry plane.

**Expected answer.** The series solution in `docs/verification.md` (diffusivity
alpha = 50/(7800 x 500) = 1.282e-5 m^2/s, Bi = hL/k = 0.5) gives at the two Fourier numbers:

| Fo | Time [s] | Centre x = 0 [K] | Surface x = L [K] |
|---|---|---|---|
| 0.2 | 39 | 397.2600 | 379.0147 |
| 1.0 | 195 | 369.8383 | 355.4589 |

Tolerance: relative error 2e-3 (V-17) at the nodes (0, 0) and (0.05, 0), with 40 elements
along the slab and the automatic time step. Using the procedure below the scripted run gave
397.096 / 379.248 K at 39 s and 370.352 / 355.882 K at 195 s, worst relative error 1.4e-3.

### 2.1 Start a new model

File > **New** (or start the program afresh). A new model is a planar analysis, which V-17
needs. (Analysis Settings > "Geometry type" changes it to axisymmetric.) The Model dock
title reads "Model — Untitled · planar · K" and the tree is the empty one: every section
shows "0" or its default, and "Contacts · Flow · Enclosures" is one dimmed line.

### 2.2 Geometry

1. Geometry > **Rectangle...**: x = `0`, y = `0`, Width = `0.05`, Height = `0.005`. **OK**.
2. View > **Fit view** (F) if the strip is not centred.

The strip is 10 times longer than high, so on screen it is a thin band; zoom with the mouse
wheel if you cannot hit the edges (middle-button drag pans).

### 2.3 Loads and selections

The mesh needs one selection per group of boundaries that get an element count, and the
loads create them. Use three conditions, as for V-10 (right-click **Loads & Boundary
Conditions** > **Add** > ...; for each, **Pick in viewport**, toolbar **Boundary**, click, type
the name in "New name", **Apply**, switch picking off):

1. **Add Convection**: pick the right edge (x = 0.05), name it `cooled end`.
   "Heat-transfer coefficient" `500`, "Fluid temperature" `300`.
2. **Add Symmetry**: pick the left edge (x = 0), name it `symmetry plane`. (A symmetry or an
   adiabatic edge has the same effect; the model asks for symmetry at x = 0.)
3. **Add Adiabatic**: pick the bottom edge, Ctrl-click the top edge ("2 boundaries picked"),
   name them `long sides`. This condition changes nothing physically; it exists to give the
   mesh settings a selection for the two long sides.

### 2.4 Material and part

1. **Materials** > **Add material**. In its panel set "Thermal conductivity" `50`, "Density"
   `7800`, "Specific heat" `500` (each: mode Constant, type, Enter).
2. **Parts** > **Add part**. Rename it `Slab` (the "Name" field, or right-click > **Rename**).
   In "Selection": **Pick in viewport**, toolbar **Part**, click inside the strip
   ("1 part picked"), type the name `slab` in "New name", **Apply**, switch picking off.
   "Material" is "Material 1".

### 2.5 Mesh: 40 elements along the slab, structured

1. Click the **Mesh** node. "Global element size": `0.005`, Enter.
2. "Boundary divisions": type
   `long sides=40, symmetry plane=1, cooled end=1`
   and press Enter. (Format: selection name, `=`, number of elements; commas separate
   entries. Use the names you gave in 2.3.)
3. "Structured parts": open the box showing "(add existing...)" and choose the part
   selection `slab`. It appears in the list above the box.
4. **Generate mesh**. The status bar should report 82 nodes, 80 elements (a 40 by 1 grid of
   cells, each split into two triangles).

### 2.6 Transient settings

1. Click **Analysis Settings** in the tree. In "Analysis type" choose `transient`. More
   fields appear.
2. "End time" `195`, Enter.
3. "Output steps": choose `times`. "Output times [s]": `39, 195`, Enter. (The step at 0 s,
   the initial state, is always stored.) Leave "Adaptive time step" on and the other time
   settings at their defaults.
4. Click **Initial Condition**. "Kind" is `uniform`. "Temperature" `400` (K), Enter. (The
   other kind, `per_region`, shows the field "Temperature per part"; its keys are the
   selection names of the parts.)

### 2.7 Expected model tree (before the solve)

```
Model — Untitled · planar · t 1 m · K          (title of the Model dock)

Geometry                       | 1 steps
  rectangle1                   | rectangle 0.05 × 0.005 m
Parts                          | 1
  Slab                         | Material 1 · 1 surface · t 1 m
Selections                     | 5
  cooled end                   | 1 boundary · convection Convection 1, mesh: divisions
  long sides                   | 2 boundaries · adiabatic Adiabatic 1, mesh: divisions
  slab                         | 1 part · part Slab, mesh: structured parts
  symmetry plane               | 1 boundary · symmetry Symmetry 1, mesh: divisions
  all                          | 1 part · unused
Materials                      | 1
  Material 1                   | k 50 W/(m K) · custom
Mesh                           | T3 · 0.005 m · 82 nodes · 80 elements · current
Initial Condition              | uniform 400 K
Loads & Boundary Conditions    | 3
  Convection 1                 | Convection · h 500 W/(m^2 K), T_inf 300 K → cooled end
  Symmetry 1                   | Symmetry → symmetry plane
  Adiabatic 1                  | Adiabatic → long sides
Contacts · Flow · Enclosures   | none          (one dimmed line)
Analysis Settings              | transient 0–195 s
Results
```

After the solve, "Results" holds "Temperature 1 | contour · current".

### 2.8 Solve and compare

1. Solve > **Validate** (no errors), then Solve > **Solve**. The progress window shows time
   and step size.
2. The viewport shows the temperature at the last step (195 s). In the "Temperature 1" panel
   the "Step" slider and spin box, and the "Time" box (type `39`, Enter), move between the
   stored steps 0, 39 and 195 s. "Play" animates. The header at the top of the panel reads
   "Analysis: transient 0–195 s", the mesh line, "Results written ..." and "Status: current".
3. **The numbers.** File > Export > **Nodal results (CSV)...**. In the CSV (columns
   `step,time,node,x,y,T,qx,qy`) take the rows with y = 0 and x = 0 or x = 0.05 at time 39
   and time 195. Compare T [K] with the table above: the relative error
   |T - T_exact| / T_exact must be below 2e-3.
4. **Charts.** Results > **Nodal history...** first asks you to pick nodes in the viewport
   (it switches to node picking itself); pick, then choose the action again to plot their
   temperature against time. Results > **Energy balance** shows the energy balance
   per step; the transient limit is 1e-3 (V-34). Results > **Heat-flow history** plots the
   heat entering through each condition.

### 2.9 What to check in this review (V-17)

1. **Toolbar.** None, Point, Boundary, Part, Node, Element. The mesh and load steps above
   use Boundary and Part.
2. **Tree and dock title.** The tree is as in 2.7. The "Analysis Settings" summary reads
   "transient 0–195 s" after step 2.6, and the "Initial Condition" summary "uniform 400 K".
   The "Mesh" summary reads "T3 · 0.005 m · 82 nodes · 80 elements · current" and turns
   "out of date" when you change a mesh setting.
3. **Geometry.** Click `rectangle1`: the strip is highlighted. Rename it (for example
   `strip`) and undo.
4. **Parts.** "Slab" with a swatch; summary "Material 1 · 1 surface · t 1 m". Try View >
   **Colour by** > Material and None.
5. **Selection field.** "1 boundary picked", "2 boundaries picked", "1 part picked". The
   suggested names are "Convection 1 selection", "Symmetry 1 selection", "Adiabatic 1
   selection" and "Slab selection"; you replaced them by typing.
6. **Selections section.** Each selection lists its users, including the mesh settings:
   `long sides` reads "2 boundaries · adiabatic Adiabatic 1, mesh: divisions". Click
   `long sides`: its two boundaries are highlighted. In its panel "Used by" lists the load
   and "mesh: divisions"; "Delete" is greyed out. Rename `long sides` to `sides` in the
   panel: the "Boundary divisions" entry of the mesh panel and the load summary follow.
   Undo it. Page Down and Page Up step through the selections.
7. **Materials.** "k 50 W/(m K) · custom".
8. **Form labels.** The mesh panel has "Boundary sizes", "Point sizes", "Boundary
   divisions" and "Structured parts"; the initial condition panel has "Temperature per
   part". (A contact would have "Interface boundaries"; V-17 has no contact.)
9. **Results.** After the solve, "Temperature 1" reads "contour · current". Change "End
   time" to `200` and press Enter: the summary reads "contour · out of date", the viewport
   title ends " · out of date", and the result panel lists "Analysis settings: End time ..."
   in the yellow box (read the exact wording and note it in the friction log). Undo makes it
   current again.
10. **Hover and inspect.** In **Boundary** mode, hover the long edges: the tooltip reads
    "in: long sides" and "adiabatic Adiabatic 1". The right edge reads "in: cooled end" and
    "convection Convection 1". A single click shows the report in the status bar and
    puts the related tree items in bold.
11. **View menu.** Summary column, Colour by, Region names (the label is "Slab") and Load
    values.

## 3. What the GUI cannot do that the example scripts do

- **Place a mesh node at a given point.** The scripts look the node up (`node_at`) because they
  drew two rectangles. In the GUI do the same (V-10 section 1.1) and read the value from the CSV
  export. There is no "node probe by coordinates"; Results > Probe is a click.
- **Enter temperatures in degC.** Scripts use `100.0 + 273.15`; in the GUI choose degC with
  Tools > Units... first (added in M10.4), otherwise enter kelvin.
- **Set per-boundary element counts without a load.** "Boundary divisions" takes names of
  existing selections. You can also make a selection without a load: select it in the
  Selections section and use "Add from viewport", or pick from any selection field. The
  extra Adiabatic condition in V-17 is the simplest way to name the long sides.

## 4. Friction found while writing this (so you can confirm or dismiss)

Found by the scripted runs and by reading the code; none confirmed on a real screen.

1. (Resolved in M10.4: Tools > Units... sets the temperature and all other units.)
2. "Pick in viewport" starts in the first dimension the field allows (Point for a fixed
   temperature), not Boundary; the toolbar mode has to be set by hand. After picking is
   switched off the toolbar still shows the last mode as checked while the viewport no longer
   picks (from the code, check on screen).
3. The viewport is fitted only when the first shape appears; later shapes may lie outside
   the view until "Fit view".
4. The "New name" box is pre-filled, so a user who does not read it keeps a name such as
   "Convection 1 selection". Check whether typing a name is natural.
5. File > New builds the empty geometry on the gmsh thread; harmless but visible as
   "Building geometry..." in the status bar.
6. A new material starts with every property at 0 (owner's decision, 2026-11-24); a steady
   solve needs the conductivity, a transient one all three.
7. Results > Probe reads a pixel, not a coordinate.
8. Opening a saved model attaches its results file only after a mesh exists, so the
   results appear only after you press "Generate mesh" again.

## 5. Friction log (fill in)

| # | Walkthrough step | What I did | What happened / what I expected | Severity (blocker / slows me down / cosmetic) | Suggested change |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

Also record: total time to build V-10 from scratch; total time to build V-17; and whether
each answer was inside its tolerance (V-10 within 0.15 degC; V-17 within 2e-3).

| Case | Minutes | Answer | Inside tolerance? |
|---|---|---|---|
| V-10 | | | |
| V-17 | | | |
