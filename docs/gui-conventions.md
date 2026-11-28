# GUI conventions

Rules that every panel, pick mode and result display of the window follows, so that a user
who learns one part of the window can predict the rest. Approved by the owner on
2026-11-27 after the second M8.G review; they come from the consistency pass over the
held window fixes and a comparison with Ansys Mechanical, COMSOL and Abaqus/CAE.

Every held window fix in `docs/tasks.md` follows these rules. Where an item's text and a
rule disagree, the rule wins. A new panel or tool follows them from the start. Items marked
**open** wait for the owner.

## C1. When a change takes effect

- **Changing which geometry an object applies to waits for "Update"; changing a value
  applies at once.** Update covers: the selection of a load, part or contact, a stream's
  walls, the mesh panel's structured parts, and the selection column of every
  value-per-selection table (boundary and point sizes, boundary divisions, temperature per
  part, and the Mesh panel's Refinements table).
- Values apply at once as today: a number or text on Enter or leaving the box, a dropdown
  of values (material, fluid, correlation, analysis type, time integration) when chosen, a
  checkbox when ticked. The network's From/To dropdowns name network nodes, not geometry,
  so they apply at once.
- Precedent in the window: the Material panel's library entry does nothing until "Use
  library values" is pressed.
- A change waiting for Update is marked (a colored border on the dropdown and the note
  "not applied"), with Update (✓) and Revert (↶) beside it. Update is one undo step.
- In a table row, Enter in the value box applies the whole row, its pending selection
  included, so a row is never half-applied.
- **Open (A):** leaving the panel with a change pending.

## C2. Picking in the view

Every pick works the same way: the selection field's New and Edit, the Selections panel's
Add and Remove, a stream's path, the nodal history's nodes, a path plot's points, the
probe and the geometry tool dialogs.

- A strip in the panel (or the dialog) shows an instruction and a running count ("2
  boundaries picked"); it is shown only while picking.
- What has been picked is marked in the view (highlight, markers, numbers).
- The toolbar switches to the kind of entity the pick needs and switches back afterwards.
  A field that accepts points or boundaries (Fixed Temperature) starts in Boundary.
- **Enter confirms, Esc cancels**, besides the strip's buttons. Cancel changes nothing.
- The probe's strip reads "Click to read values · Esc to stop".

## C3. Result displays are saved tree items

- Contour, vector plot, path plot and nodal history are items under Results, each with a
  panel, saved in the model file.
- The nodal history panel holds the node list with its pick strip (C2), the quantity and
  Plot; the path plot panel is held item 15.
- A new solve redraws them all. Each shows the contour's status words: "current", "out of
  date" or "unavailable" (its nodes or boundaries no longer exist).
- Heat-flow history and energy balance need no input; they stay Results-menu windows and
  also redraw after a new solve.
- This adds saved types to `docs/data-model.md`; the owner approves the entries.
- **Open (B):** whether edits to result items are undo steps.

## C4. Show and hide

Each result item has an eye toggle. The toggle of the displayed contour hides the field
and keeps its settings. Path drawings and node labels have their own toggles.

## C5. Grouping in panels

A panel long enough to need grouping uses framed boxes, each with a title and a one-line
description. Today's bold-label headings (Mesh, network) become boxes.

## C6. Icons and words

- An action on **one field or one table row** is an icon from one shared set: + add,
  ✕ remove, ✎ edit, ✓ update, ↶ revert, a crosshair for pick, a folder for browse. Each
  has a tooltip and an accessible name that say what it does.
- A command on **the whole object or panel** keeps words: Generate mesh, Validate, Solve,
  Use library values, Plot.
- This covers the Refinements, network and function-editor tables as well as the selection
  fields and value tables.

## C7. What an empty box means

- Every optional box shows the meaning of an empty value in grey hint text: "no limit",
  "suggested from the mesh", "from the geometry", "one per wall edge".
- An optional formula field names its empty mode by its meaning instead of "None":
  "Isotropic", "From network", "Use correlation".
- A required formula field starts in Constant, never in an empty mode.
- **Open (E):** the label "Conductivity (across axis, empty = isotropic)".

## C8. Readable choices

Every dropdown shows readable text ("Transient", "Every n-th step", "Per part",
"Quadratic (2)", "Vertical plate, natural convection, laminar"); the model stores the same
values as before. The mapping lives in the window, as for "Time integration".

## C9. Words for geometry

- Part, Boundary and Point everywhere outside the Geometry section: labels, tooltips,
  summaries, status lines, error and validation messages, the Issues panel and the View
  menu ("Part names", not "Region names"). No "region", and no "surface" or "curve" as a
  name for a part or boundary.
- The Geometry section keeps shape words, since its operations make shapes ("Surface from
  curves").
- **Open (H):** how a field's symbol is shown (labels in the view and summaries use `T_inf`,
  `h`, while the panel says "Fluid temperature").

## C10. Highlighting

Whenever a tree item or a focused field uses geometry, that geometry is highlighted in the
selection yellow: selections, parts, materials, loads, contacts (as today), and also a
stream's walls and path, an enclosure's surfaces, the Mesh panel's sized, divided and
structured entities while their row has focus, a path plot's ends A and B, and a nodal
history's nodes. Labels are drawn in front of lines.

## C11. Error messages

An error appears once, directly under its field. The message at the top of a panel is only
for an error that belongs to no single field.

## C12. Advanced fields

- An advanced field has a default that suits most models and changes how the solver or
  mesher works, not the physics. A field without a default, or one that reveals other
  fields, is never advanced.
- Advanced fields stay in their purpose box under a collapsed "More" line at its bottom; a
  box that is wholly advanced is collapsed itself. A field that applies only in some cases
  is hidden when it does not apply, not collapsed.
- **Open (C):** how a collapsed part shows values that are not the default.
- Per panel:
  - Analysis Settings: Time stepping › More holds Initial time step, Smallest time step,
    Time-step tolerance and Largest temperature change per step; Integration (Time
    integration, Lumped capacitance; its title shows the method) and Convergence are
    collapsed boxes. **Open (G):** confirm these two changes to held item 11.
  - Mesh: Element type › More holds Algorithm and Smoothing passes.
  - Correlation convection: More holds Characteristic length, Face direction, Wall
    temperature and Multiplier.
  - Stream: Coefficient › More holds Wall roughness, Number of cells, Nusselt option,
    Coefficient multiplier and Coefficient override.
  - Part: Material angle is hidden unless the material has a conductivity across the axis.
  - Material, loads, contact, Initial Condition, Results: nothing collapsed. Tables are
    not split.

## C13. Problems marked in the tree

A tree item that Validate would complain about carries a small warning mark, updated as
the model is edited (a load with no selection, a part with no material, a material with a
property not set). Its tooltip gives the message.
