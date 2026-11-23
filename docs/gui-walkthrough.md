# GUI walkthrough: build V-10 and V-17 from scratch

For the M8.G human gate: *a person builds V-10 and V-17 from scratch in the GUI following
the tutorial text, and lists every point of friction.* This file is that text. Follow it
step by step, compare each answer with the number given, and write every place where you
got stuck, guessed, or were surprised into the friction log at the end.

Every menu name, button text, field label and tree node below was read from the source, and
both procedures were run end to end by a script that drives the same widgets (the V-10 run
is `tests/gui/test_end_to_end.py`). On 2026-11-23 a script also followed these steps in the
real window on a real screen: every count and answer below came out as stated (V-10
18.2064 degC; V-17 worst relative error 1.4e-3). A page with the steps, the screenshots
of that run and a friction log is at https://claude.ai/artifact/AVKWHDY1Pa6YZ22go6weAH.
No person has used the window yet, so ease of use is exactly what the gate is meant to
find.

## 0. Starting the GUI

From the project folder in a terminal:

```
.venv\Scripts\python.exe -m thermalfea.gui.app
```

The main window has a model tree ("Model" dock, top left), the property panel ("Properties"
dock, below it), the viewport in the middle, and a "Messages" dock at the bottom (the solver
log is written there; an "Issues" dock is tabbed with it). Menus: File, Edit, View, Geometry,
Mesh, Solve, Results, Tools, Help. The toolbar holds the selection modes (None, Point, Curve,
Surface, Node, Element) and a "Fit view" button.

Things to know before you start:

- **Temperatures are entered in kelvin** unless you change the units with Tools > Units...
  (the steps below assume the default, SI with K). 100 degC is 373.15 K and 0 degC is
  273.15 K.
- **Press Enter after typing a number** in a property field. The value is applied when you
  press Enter or leave the field, and each applied change is one undo step (Edit > Undo).
- Property fields that are physical functions (conductivity, temperature, heat-transfer
  coefficient, ...) show a mode box (Constant, Table, Expression) above the value. Leave it
  on "Constant" and type the number.
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
   `rectangle1` and `rectangle2`.
5. View > **Fit view** (or the key F). The viewport is fitted only when the first shape
   appears, so the second rectangle is partly out of view until you do this.

You should see a 0.6 by 1.0 plate with a line across it at y = 0.2 (two surfaces, seven
curves).

### 1.2 Loads: pick the curves, then set the values

The three conditions need named curve selections. You create each selection from the
condition's own panel.

**Fixed temperature (bottom edge, 100 degC):**

1. In the model tree, right-click **Loads & Boundary Conditions**. Choose **Add** >
   **Add Fixed Temperature**. A node "Fixed Temperature 1" appears and its panel
   ("Fixed Temperature: Fixed Temperature 1") opens in Properties.
2. In the panel's "Selection" field press **Pick in viewport**. In the toolbar choose
   **Curve** (the panel starts in Point mode, because a fixed temperature may also be put on
   points).
3. Click the bottom edge of the plate (y = 0). The status line under the buttons says
   "1 curve(s) picked". Press **Apply**. The field now shows "Fixed Temperature 1 selection".
4. Press **Pick in viewport** again to switch picking off.
5. In "Temperature" type `373.15` and press Enter (unit shown: K).

**Convection (right and top edges, h = 750, 0 degC):**

1. Right-click **Loads & Boundary Conditions** > **Add** > **Add Convection**.
2. Selection: **Pick in viewport**, toolbar **Curve**. The right edge is two curves (split at
   y = 0.2): click the lower right edge, then hold **Ctrl** and click the upper right edge
   and the top edge. The status line says "3 curve(s) picked". Press **Apply**, then switch
   **Pick in viewport** off.
3. "Heat-transfer coefficient": `750`, Enter (unit W/(m^2 K)).
4. "Fluid temperature": `273.15`, Enter (K).

**Adiabatic (left edge):**

1. Right-click **Loads & Boundary Conditions** > **Add** > **Add Adiabatic**.
2. Selection: **Pick in viewport**, toolbar **Curve**, click the lower left edge, Ctrl-click
   the upper left edge (2 curves), **Apply**, switch picking off.

The viewport now shows load symbols for the three conditions. Selecting a condition in the
tree highlights its curves.

### 1.3 Material and region

1. Right-click **Materials** > **Add material**. A material "Material 1" appears; it starts
   as a copy of the first library material (aluminium), so every value must be set.
2. In its panel set "Thermal conductivity" (mode Constant) to `52` and press Enter. Density
   and specific heat do not affect a steady answer; leave them.
3. Right-click **Regions** > **Add region**. A region node appears and its panel
   ("Region") opens. Its "Material" box already holds "Material 1".
4. In the "Selection" field: **Pick in viewport**, toolbar **Surface**, click inside the
   lower rectangle, Ctrl-click inside the upper one ("2 surface(s) picked"), **Apply**,
   switch picking off. (The new selection is named "Region selection"; see the notes at the
   end.) "Thickness" stays 1 and "Material angle (rad)" 0.

### 1.4 Mesh

1. Click the **Mesh** node in the tree. The panel "Mesh" opens.
2. "Global element size": `0.025`, Enter. Leave "Element order" 1, "Element shape" tri.
3. Press **Generate mesh** (or Mesh > **Generate mesh**). The status bar reports about
   "Mesh generated: 1210 nodes, 2290 elements". The mesh is drawn in the viewport.

### 1.5 Solve

1. Solve > **Validate**. The status bar must say "Validation: no issues" (or list only
   warnings; any error must be fixed first).
2. Solve > **Solve**. A window titled "Solving" shows the progress and ends with a
   "Finished" state; it stays open until you close it. A linear steady case takes a moment.
3. A node "Temperature 1" appears under **Solution** in the tree and the temperature contour
   is drawn in the viewport. (The contour starts banded with 12 levels. Click the node to see
   its panel: "Levels", "Banded (otherwise smooth)", "Colour scale", "Mesh overlay".)

### 1.6 Compare with the benchmark

- **The number.** File > Export > **Nodal results (CSV)...**, choose a file name. Open the
  CSV in a spreadsheet. Columns are `step,time,node,x,y,T,qx,qy` with T in kelvin. Find the
  row with x = 0.6 and y = 0.2. T minus 273.15 must be between 18.15 and 18.45 degC (target
  18.3, tolerance 0.15). Expect about 291.356 K (18.206 degC).
- **A quick look.** Results > **Probe**, then click the viewport as close as you can to the
  right edge at the line y = 0.2. The status bar shows x, y and the temperature in K. This is
  limited by the pixel you hit and by the point lying on the boundary, so use it only as a
  rough check; the CSV is the exact one.
- **Energy balance.** The "Messages" dock shows the solver log. It lists the heat entering
  through each condition (Fixed Temperature 1 about +10396 W, Convection 1 about -10396 W)
  and "relative imbalance". The value must be below 1e-8; it is about 1e-14.
  Results > **Energy balance** plots it.

### 1.7 Extra checks (optional, they test the editing machinery)

- Change "Heat-transfer coefficient" of the convection to `800`. The status of the results
  becomes "out of date" (a note appears in the result panel); the mesh stays valid. Edit >
  **Undo** returns it to 750.
- Change "Global element size" to `0.03`: now the mesh is out of date and Solve is greyed out
  until you press **Generate mesh** again.
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

File > **New** (or start the program afresh). A new model is a planar analysis; the GUI has
no control to change that, which V-17 does not need.

### 2.2 Geometry

1. Geometry > **Rectangle...**: x = `0`, y = `0`, Width = `0.05`, Height = `0.005`. **OK**.
2. View > **Fit view** (F) if the strip is not centred.

The strip is 10 times longer than high, so on screen it is a thin band; zoom with the mouse
wheel if you cannot hit the edges (middle-button drag pans).

### 2.3 Loads and selections

The mesh needs one selection per group of curves that get an element count, and the loads
create them. Use three conditions, as for V-10 (right-click **Loads & Boundary Conditions**
> **Add** > ...; for each, **Pick in viewport**, toolbar **Curve**, click, **Apply**, switch
picking off):

1. **Add Convection**: pick the right edge (x = 0.05). "Heat-transfer coefficient" `500`,
   "Fluid temperature" `300`. The selection is named "Convection 1 selection".
2. **Add Symmetry**: pick the left edge (x = 0). The selection is named
   "Symmetry 1 selection". (A symmetry or an adiabatic edge has the same effect; the model
   asks for symmetry at x = 0.)
3. **Add Adiabatic**: pick the bottom edge, Ctrl-click the top edge (2 curves). The
   selection is named "Adiabatic 1 selection". This condition changes nothing physically; it
   exists to give the mesh settings a selection for the two long sides.

### 2.4 Material and region

1. **Materials** > **Add material**. In its panel set "Thermal conductivity" `50`, "Density"
   `7800`, "Specific heat" `500` (each: mode Constant, type, Enter).
2. **Regions** > **Add region**. In "Selection": **Pick in viewport**, toolbar **Surface**,
   click inside the strip, **Apply**, switch picking off. "Material" is "Material 1".

### 2.5 Mesh: 40 elements along the slab, structured

1. Click the **Mesh** node. "Global element size": `0.005`, Enter.
2. "Curve divisions": type
   `Adiabatic 1 selection=40, Symmetry 1 selection=1, Convection 1 selection=1`
   and press Enter. (Format: selection name, `=`, number of elements; commas separate
   entries. If the names in your model differ, use the names shown in the "Selection" field of
   each condition.)
3. "Structured surfaces": open the box showing "(add existing...)" and choose the surface
   selection of the region ("Region selection"). It appears in the list above the box.
4. **Generate mesh**. The status bar should report 82 nodes, 80 elements (a 40 by 1 grid of
   cells, each split into two triangles).

### 2.6 Transient settings

1. Click **Analysis Settings** in the tree. In "Analysis type" choose `transient`. More
   fields appear.
2. "End time" `195`, Enter.
3. "Output steps": choose `times`. "Output times [s]": `39, 195`, Enter. (The step at 0 s,
   the initial state, is always stored.) Leave "Adaptive time step" on and the other time
   settings at their defaults.
4. Click **Initial Condition**. "Kind" is `uniform`. "Temperature" `400` (K), Enter.

### 2.7 Solve and compare

1. Solve > **Validate** (no errors), then Solve > **Solve**. The progress window shows time
   and step size.
2. The viewport shows the temperature at the last step (195 s). In the "Temperature 1" panel
   the "Step" slider and spin box, and the "Time" box (type `39`, Enter), move between the
   stored steps 0, 39 and 195 s. "Play" animates.
3. **The numbers.** File > Export > **Nodal results (CSV)...**. In the CSV (columns
   `step,time,node,x,y,T,qx,qy`) take the rows with y = 0 and x = 0 or x = 0.05 at time 39
   and time 195. Compare T [K] with the table above: the relative error
   |T - T_exact| / T_exact must be below 2e-3.
4. **Charts.** Results > **Nodal history...** first asks you to pick nodes in the viewport
   (it switches to node picking itself); pick, then choose the action again to plot their
   temperature against time. Results > **Energy balance** shows the energy balance
   per step; the transient limit is 1e-3 (V-34). Results > **Heat-flow history** plots the
   heat entering through each condition.

## 3. What the GUI cannot do that the example scripts do

- **Place a mesh node at a given point.** The scripts look the node up (`node_at`) because they
  drew two rectangles. In the GUI do the same (V-10 section 1.1) and read the value from the CSV
  export. There is no "node probe by coordinates"; Results > Probe is a click.
- **Name a selection.** Scripts name curves `left`, `right`, ... The GUI names each selection
  after the field that created it ("Convection 1 selection"; for a region "selection
  selection"). Renaming selections is not offered in the tree.
- **Enter temperatures in degC.** Scripts use `100.0 + 273.15`; in the GUI choose degC with
  Tools > Units... first (added in M10.4), otherwise enter kelvin.
- **Set per-curve element counts without a load.** "Curve divisions" takes names of existing
  selections, and the only way to make a curve selection is a field that picks one, hence the
  extra Adiabatic condition in V-17.

## 4. Friction found while writing this (so you can confirm or dismiss)

Found by the scripted runs and by reading the code; none confirmed on a real screen.

1. (Resolved in M10.4: Tools > Units... sets the temperature and all other units.)
2. "Pick in viewport" starts in the first dimension the field allows (Point for a fixed
   temperature), not Curve; the toolbar mode has to be set by hand. After picking is
   switched off the toolbar still shows the last mode as checked while the viewport no longer
   picks (from the code, check on screen).
3. The viewport is fitted only when the first shape appears; later shapes may lie outside
   the view until "Fit view".
4. A region's selection is named "Region selection"; load selections are named
   "<load name> selection". No rename in the tree.
5. File > New builds the empty geometry on the gmsh thread; harmless but visible as
   "Building geometry..." in the status bar.
6. A new material is a copy of a library aluminium; all three properties have to be set.
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
