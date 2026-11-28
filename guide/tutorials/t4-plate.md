# Tutorial 1: NAFEMS T4, a steady plate

**What you will build.** A rectangular plate held at 100 °C on one edge and cooled by
convection on two others. It is the NAFEMS "T4" heat-transfer benchmark, and the published
answer is a single temperature at a single point.

**What you will learn.** How to draw the geometry; how to pick edges and faces in the
viewport; how to enter a material, boundary conditions and a mesh size; how to solve a
steady analysis and read a temperature at a point; how to check the energy balance; and how
the answer changes as the mesh is refined.

The finished model is in
[models/t4-plate.tfea](models/t4-plate.tfea); open it with **File > Open...** to compare with
your own.

## The problem

A plate of conductivity k = 52 W/(m K) measures 0.6 m in x and 1.0 m in y. Its bottom edge
is held at 100 °C. Its left edge is insulated. Its right and top edges lose heat by
convection to air at 0 °C. The question is the temperature at the point (0.6, 0.2), on the
right edge, 0.2 m above the hot edge.

| Item | Value |
|---|---|
| Plate | 0.6 m (x) by 1.0 m (y), planar model, thickness 1 m (the default) |
| Conductivity k | 52 W/(m K), constant |
| Bottom edge (y = 0) | fixed temperature 100 °C = 373.15 K |
| Left edge (x = 0) | adiabatic (insulated) |
| Right edge (x = 0.6) and top edge (y = 1) | convection, h = 750 W/(m² K), fluid at 0 °C = 273.15 K |
| Benchmark | T(0.6, 0.2) = 18.3 °C, accepted within 0.15 °C at element size 0.025 |

**Temperature units.** The program works in SI units and shows kelvin by default. This
tutorial uses the defaults, so every temperature you type is in kelvin: 100 °C is 373.15 K
and 0 °C is 273.15 K. (**Tools > Units...** can show degrees Celsius instead; the numbers
below are given in both.)

**A note on the point (0.6, 0.2).** The program cannot place a mesh node at a coordinate
you type, and you want a node exactly at the benchmark point. So you draw the plate as two
stacked rectangles that meet along y = 0.2. A shared edge puts a geometry vertex at
(0.6, 0.2), and the mesher always puts a node on a vertex.

## Before you start

Start the program from the project folder:

```
.venv\Scripts\python.exe -m thermalfea.gui.app
```

The window has the model tree (the **Model** dock, top left), the property panel (the
**Properties** dock, below it), the viewport in the middle, and the **Messages** dock at the
bottom. The solver writes its log to Messages. An **Issues** dock shares that space as a
tab. The toolbar holds the selection modes (None, Point, Boundary, Part, Node, Element) and
**Fit view**.

Three habits save trouble:

- Press **Enter** after typing a number in a property field. The value is applied when you
  press Enter or leave the field. Each applied change is one undo step (**Edit > Undo**).
- A field that holds a physical function (conductivity, temperature, heat-transfer
  coefficient, ...) has a mode box with Constant, Table and Expression. Leave it on
  **Constant** and type the number.
- Edges and faces are chosen from the panel of the object that needs them, in its selection
  field (a row labeled "Boundary" for edges, "Selection" in a part's panel for faces). Press
  the crosshair icon (**New selection**); the toolbar switches to the right mode by itself
  and a yellow strip tells you what to click. Click, hold **Ctrl** to add more items, type a
  name for the selection in the **Name** box (it starts empty) and press **Create and use**
  (or Enter). **Esc** cancels the pick. The selection is created and used by the object in
  one step.
- A choice made in the dropdown of a selection field, by contrast, waits: the dropdown gets
  a colored border and a check mark (**Update**) and an arrow (**Revert**) appear. Press
  the check mark to apply the choice.
- The tree has a second column that summarises each item, for example the conductivity of a
  material or the number of nodes of the mesh. **View > Summary column** hides it.

## Steps

### 1. Draw the geometry

1. Choose **Geometry > Rectangle...**. A dialog titled "Rectangle" opens.
2. Type x = `0`, y = `0`, Width = `0.6`, Height = `0.2`. Leave "Corner radius" at 0 and "Id"
   empty (an id is made for you). Press **OK**.
3. Choose **Geometry > Rectangle...** again and type x = `0`, y = `0.2`, Width = `0.6`,
   Height = `0.8`. Press **OK**.
4. After each OK the geometry is rebuilt by itself: the status bar shows "Building
   geometry..." and then "Geometry rebuilt". The tree node **Geometry** now lists
   `rectangle1` and `rectangle2`.
5. Choose **View > Fit view** (or press **F**). The view is fitted only when the first shape
   appears, so the second rectangle may be partly out of sight until you do this.

You should see a 0.6 by 1.0 plate with a line across it at y = 0.2: two surfaces and seven
curves.

### 2. Enter the material

1. Right-click **Materials** and choose **Add material**. A node "Material 1" appears and its
   panel opens. A new material starts with every property at 0, which means "not set
   yet".
2. In "Conductivity (along axis)" (mode Constant) type `52` and press Enter. Leave
   "Conductivity (across axis)" on its mode "Isotropic": the plate has the same conductivity
   in every direction. Density and specific heat do not affect a steady answer; they may
   stay at 0. (Before you type the conductivity, the tree marks the material with a small
   warning sign; hover over it to read why.)

### 3. Assign it to the plate

1. Right-click **Parts** and choose **Add part**. A part "Part 1" appears under **Parts** and
   its panel ("Part") opens, with the fields "Name", "Selection", "Material" and
   "Thickness". Its "Material" box already shows "Material 1". Type `Plate` in "Name" and
   press Enter.
2. In the "Selection" field press the crosshair icon (**New selection**). The toolbar
   switches to **Part** by itself. Click inside the lower rectangle, **Ctrl**-click inside
   the upper one (the strip says "2 parts picked"). Type `plate` in the **Name** box and
   press **Create and use**. The field now reads "plate · 2 parts".
3. Leave "Thickness" at 1. ("Material angle" is hidden: the material is isotropic.)

A part ties a material to some faces and, in a planar model, gives the depth of the plate
perpendicular to the drawing. Every heat flow the program reports is for that depth: here, per
metre.

### 4. Enter the boundary conditions

There are three. Each is added from the node **Loads & Boundary Conditions**.

**Fixed temperature on the bottom edge.**

1. Right-click **Loads & Boundary Conditions** and choose **Add > Add Fixed Temperature**. A
   node "Fixed Temperature 1" appears and its panel opens.
2. In the field labeled "Boundary or point" (a fixed temperature may also be put on points)
   press the crosshair icon (**New selection**). The toolbar switches to **Boundary** by
   itself. Click the bottom edge of the plate. The strip says "1 boundary picked". Type
   `base` in the **Name** box and press **Create and use**. The field now reads
   "base · 1 boundary".
3. In "Temperature T" type `373.15` and press Enter (the unit shown is K).

**Convection on the right and top edges.**

1. Right-click **Loads & Boundary Conditions** and choose **Add > Add Convection**.
2. In the field labeled "Boundary" press the crosshair icon. The right edge is two
   boundaries (it is split at y = 0.2). Click the lower right edge, then hold **Ctrl** and
   click the upper right edge and the top edge. The strip says "3 boundaries picked".
   Type `cooled` in the **Name** box and press **Create and use**.
3. In "Heat-transfer coefficient h" type `750` and press Enter (W/(m² K)).
4. In "Fluid temperature T∞" type `273.15` and press Enter (K).

**Adiabatic on the left edge.**

1. Right-click **Loads & Boundary Conditions** and choose **Add > Add Adiabatic**.
2. In "Boundary" pick the lower left edge, **Ctrl**-click the upper left edge ("2 boundaries
   picked"), type `left side` in the **Name** box and press **Create and use**.

An adiabatic edge changes nothing: every edge without a condition is already insulated. The
condition is there so that the model says what you meant, and so that the edge has a name.

The viewport now draws a symbol for each condition. Click a condition in the tree and its
boundaries are highlighted. The **Selections** section lists `base`, `cooled`, `left side`
and `plate`, each with the objects that use it, for example "3 boundaries · convection
Convection 1".

### 5. Mesh

1. Click the node **Mesh**. The panel "Mesh" opens.
2. In "Global element size" (the **Element size** box) type `0.025` and press Enter. Leave
   "Element order" at "Linear (1)" and "Element shape" at "Triangles" (the **Element type**
   box): linear triangles. The boxes below (Structured mesh, Refinements) stay empty.
3. Press **Generate mesh** (or choose **Mesh > Generate mesh**). The status bar reports
   "Mesh generated: 1210 nodes, 2290 elements", and the mesh panel lists the same counts. The
   mesh is drawn in the viewport.

### 6. Solve

1. Choose **Solve > Validate**. The status bar must say "Validation: no issues". If it lists
   errors, fix them first; warnings alone do not stop a solve.
2. Choose **Solve > Solve**. A window titled "Solving" shows progress and ends in the state
   "Finished". It stays open until you close it. A linear steady case takes a moment.
   (The **Analysis Settings** node has the same Validate and Solve buttons.)
3. A node "Temperature 1" appears under **Results** in the tree, with the summary "contour ·
   current", and the temperature contour is drawn in the viewport. Click the node to see its
   panel: a header ("Analysis", "Mesh", "Results written", "Status"), then "Field", "Levels",
   "Banded (otherwise smooth)", "Color scale", "Mesh overlay".

The analysis type was never changed: a new model is steady, which is what this problem is.

### 7. Read the answer at (0.6, 0.2)

- **The exact value.** Choose **File > Export > Nodal results (CSV)...** and give a file
  name. Open the CSV in a spreadsheet. The columns are `step,time,node,x,y,T,qx,qy`, with T in
  kelvin. Find the row with x = 0.6 and y = 0.2. It reads T = 291.356 K, which is 18.206 °C.
- **A quick look.** Choose **Results > Probe**, then click in the viewport as close as you can
  to the right edge at the line y = 0.2. The status bar shows x, y and the temperature. A
  click lands on a pixel and the point lies on the boundary, so use this only as a rough check.
  The CSV is the exact one.
- **Energy balance.** The **Messages** dock lists the heat entering through each condition.
  Fixed Temperature 1 gives about +10396 W and Convection 1 about -10396 W (a positive value
  is heat entering the plate). Below them, "relative imbalance" is the part of the heat flow
  that the balance fails to account for. **Results > Energy balance** plots it.

## Results

![Temperature of the T4 plate, mesh size 0.025](img/t4-contour.png)

The plate is hottest along the bottom edge (373.15 K) and coldest at the top right corner
(273.7 K, a little above the fluid at 273.15 K). Heat leaves mainly through the lower part of
the right edge, where the plate is hottest and the difference to the fluid is largest. The title says "steady state", because a steady
result has no time.

![Temperature along the right edge, from y = 0 to y = 1](img/t4-right-edge.png)

| Quantity | Value |
|---|---|
| Mesh | 1210 nodes, 2290 elements (linear triangles, size 0.025) |
| T at (0.6, 0.2) | 291.356 K = 18.206 °C |
| Benchmark | 18.3 °C, tolerance 0.15 °C |
| Difference | 0.094 °C, inside the tolerance |
| Heat entering at the bottom edge | 10 396 W (for 1 m depth) |
| Heat leaving by convection | 10 396 W |

## Checking the answer

**Against the benchmark.** The answer is 0.094 °C below 18.3 °C and the tolerance is
0.15 °C, so the benchmark is met.

**Energy balance.** Every solve checks that the heat in equals the heat out. For a linear
steady case the relative imbalance must be below 1e-8. Here it is about 1e-14; the two
heat flows above match to every digit shown.

**Mesh refinement.** Change "Global element size" and solve again, as in steps 5 to 7. After
you change the size the mesh is out of date and **Solve > Solve** is greyed out until you
press **Generate mesh** again. After you solve, the old contour is replaced. Read the
temperature at (0.6, 0.2) from the CSV each time.

| Global element size | Nodes | Elements | T, linear triangles [°C] | T, quadratic triangles [°C] |
|---|---|---|---|---|
| 0.1 | 93 | 152 | 17.79 | 18.34 |
| 0.05 | 328 | 590 | 18.09 | 18.26 |
| 0.025 | 1210 | 2290 | 18.21 | 18.25 |
| 0.0125 | 4629 | 9000 | 18.24 | 18.25 |

(The quadratic column needs "Element order" "Quadratic (2)"; the node counts for those meshes are 337,
1245, 4709 and 18 257.)

![Temperature at (0.6, 0.2) against element size](img/t4-convergence.png)

Read the table like this:

- With linear triangles the answer rises towards the limit from below at every refinement:
  0.51, 0.21, 0.094 and 0.058 °C below 18.3. The steepest gradients are at the lower right
  corner, where the hot edge meets the cooled one, and a coarse mesh resolves them poorly. On
  the 0.1 mesh the answer is 0.5 °C off, outside the benchmark tolerance.
- With quadratic triangles the answer is already 18.34 °C on the coarsest mesh and settles at
  18.25 °C. The last two refinements differ by less than 0.002 °C.
- So the mesh-converged answer is about 18.25 °C, not 18.3 °C. It lies 0.05 °C from the
  benchmark value, well inside the 0.15 °C the benchmark accepts. Refining further would not
  close that gap.

![The 0.1 mesh drawn over the temperature](img/t4-mesh.png)

The picture shows the 0.1 mesh so that the triangles can be seen. At size 0.025 the plate
has about 2300 triangles and no local refinement.

## Things to try

- Select the Convection 1 node and change "Heat-transfer coefficient h" to `800`. The tree
  shows "contour · out of date" for the result, the viewport title ends " · out of date", and
  the results panel shows "These results are out of date: the model changed since the
  solve." with the change listed beneath it. The mesh is still valid, so you can solve again
  at once. **Edit > Undo** returns the value to 750 and the results are current again.
- In **Boundary** mode, hover over an edge of the plate: a tooltip names the boundary, its
  selections and the loads on it. Click it once to see the same report in the status bar.
- Set "Element shape" to "Quadrilaterals (quad-dominant)" and compare. Set "Element order"
  to "Quadratic (2)" and compare with the table.
- Choose **View > Part names** to write the part's name in the view, and **View > Load
  values** to switch the load labels off and on.
- Save the model (**File > Save As...**), choose **File > New**, then **File > Open...** the
  file. The geometry is rebuilt by itself. The results saved beside the model are attached
  again after you press **Generate mesh**.
- Use **Results > Add contour** and choose another entry in the "Field" box of its panel, for
  example the heat flux, and look at where it is largest.

## The same model as a script

The same plate is built through the Python API in `examples/v10_nafems_t4.py`, and the mesh
table above is produced by `examples/tutorial_t4_plate.py`.
