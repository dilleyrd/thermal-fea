# GUI identity plan (owner decisions of 2026-11-24)

Status: **revised after an independent review** (Codex, 2026-11-24, 16 findings, all
taken in; see §8). The tasks are M11.49–M11.64 in `docs/tasks.md`.

## 1. Goal

An engineer must be able to tell at a glance:
- what each item in the Model panel is;
- where it sits on the model;
- what it represents physically;
- which model state a result was solved from.

The design must carry over to 3D without rewording or restructuring (Plan §7).

The proposal the owner reviewed is https://claude.ai/artifact/RGQmdWAkgsREaaEwPiMgWq
(private). It took CalculiX GraphiX 2.24 as a reference:
- named sets carry every load and material;
- sets can be drawn in a colour, listed and stepped through;
- results carry a header.

## 2. Owner decisions (2026-11-24)

| # | Decision |
|---|---|
| D1 | Each region gets a name and is called a **Part**. |
| D2 | Named sets (selections) are visible and editable in the tree, as in cgx. |
| D3 | A material keeps its own name ("Material 1"), and its library source is shown beside it ("Aluminum, pure · library"). |
| D4 | The pick toolbar and the panels say **Part · Boundary · Point** instead of Surface · Curve · Point. |
| D5 | One result per model, as today, with a clear header and a list of changes since the solve. No multiple runs. |
| D6 | Contacts, Flow and Enclosures fold into one dimmed line while they are all empty. |
| D7 | The summary is a second column in the tree. |
| D8 | Build all this before the owner's M8.G V-17 session. The owner then reviews V-10 and V-17 again on the updated GUI. |

The owner's go-ahead ("implement this") also approves the data-model and interface
additions in §4, which the proposal listed under "What needs your approval". Multiple
runs (proposal Phase 3) are dropped by D5.

## 3. Vocabulary and the domain dimension (Plan §7 rules 1 and 3)

`model/vocabulary.py` sits below the GUI, so validation can use it too. It is the only
place that maps roles to dimensions and words:

- `domain_dim(model) -> int`: the dimension of the model's domain, known before any
  build or mesh. Today it returns 2 for `"planar"` and `"axisymmetric"`. A future 3D
  analysis type adds one entry. This is the single source of the number, and no GUI code
  writes a literal 2.
- `ROLES = ("part", "boundary", "edge", "point")`.
- `role_dim(role, model) -> int | None`:
  - part = `domain_dim`;
  - boundary = `domain_dim - 1`;
  - edge = 1 only when `domain_dim - 1 > 1`, otherwise None;
  - point = 0.
- `role_of(dim, model) -> str` is the inverse.
- `entity_word(dim, model, plural=False) -> str` gives "part" / "parts",
  "boundary" / "boundaries", "edge" / "edges", "point" / "points".

At the picking boundary, a role maps to a dimension and the dimension maps to the
existing `SelectionMode` value through the inverse of `SceneView`'s `MODE_DIM`. **The
`SelectionMode` values in Data §13 do not change.** Geometry dialogs keep "surface" and
"curve" where they mean a shape. A test uses a synthetic `domain_dim` of 3 to check the
role mapping (part→3, boundary→2, edge→1, point→0).

## 4. Data-model and interface changes

1. **Data §3 `RegionAssignment.name: str = ""`.**
   - **Display name:** one function, `part_name(region) -> str`, returns `name` or else
     the selection's name. Every display of a part goes through it. The serializer passes
     only the keys present, so old files and scripts load with `""`, with no migration
     and no schema bump.
   - **Uniqueness:** display names are unique among parts. This is checked on Add part,
     on rename, and on reassigning a part's selection. A part whose display name would
     change because its selection was renamed keeps it: before renaming a selection,
     `rename_selection` writes the old display name into each unnamed part that uses it.
   - **Ambiguous rows:** legacy rows with an ambiguous or empty display name stay
     addressable by index (`("regions", i)`), as today.
   - **Per-region initial temperatures:** `InitialCondition.per_region` stays keyed by
     selection name. The editor labels rows with part names, stores the selection keys,
     and keeps valid keys that match no part.
2. **Data §6 `Material.source: MaterialSource | None = None`** (keyword-only), with
   `MaterialSource(library: Literal["builtin", "user"], entry: str)`.
   - **Where it is set:** Use library values sets it. The `(library, entry)` comes from
     the picker, so a built-in and a user entry with the same name stay distinct.
   - **What it affects:** the solver ignores it. The restart check (`results_writer`)
     and the "edited" test compare **physical properties only** (k, k2, rho, cp,
     phase_change), so a change in provenance never refuses a restart.
   - **User library files** keep the source when one is present.
   - **"Edited"** is worked out by comparing values, never stored. If the entry no longer
     exists, the material shows "library entry not found".
3. **Data §5, `model/selections.py`:** `selection_refs(model, name)` is **one traversal**
   that yields writable references. The same traversal serves the users list, rename and
   delete protection. It covers:
   - regions, every BC (suppressed ones too), contacts' interface selection, enclosure
     `surfaces[i].selection` and stream `walls` (with repeated entries);
   - the mesh `curve_sizes`, `point_sizes` and `curve_divisions` keys, plus
     `structured_surfaces` and `refinements[i].selection`;
   - the `per_region` keys.

   References in registered form fields are found generically. The dict-keyed and
   nested ones are listed in one explicit table there.

   Built on that traversal:
   - `selection_users(model, name) -> list[SelectionUse]` gives `(address, label)` for
     each user.
   - `rename_selection(model, old, new)` checks before changing anything: the new name is
     non-empty, not in use as a selection, and not a key already present in any of the
     dicts (even a dangling one). On refusal it raises `ModelError` and leaves the model
     untouched, so `Document.edit` pushes no undo command.
   - `delete_selection(model, name)` is refused while there are users.
   - **Reserved `all`:** the build recreates it (`api.build`), so rename, delete, changes
     to its members, and creating a selection under that name are refused. Parts and
     loads may still use it.
   - **Mesh invalidation:** the mesher writes a node set for every selection
     (`mesher.py`). A change to a selection key or to its members therefore makes the
     mesh stale in `Document._invalidate`, which today treats selection edits as
     results-only. Results already written stay intact.
4. **Data §4 `rename_operation(model, old_id, new_id)`** in `model/geometry_edit.py`.
   - **How:** it rewrites every reference by walking `REF_RULES`, keeping repeats, order
     and nested hole loops. It does not use `dependents`, which flattens and removes
     repeats.
   - **Refusals:** it refuses a blank or duplicate id before changing anything.
   - **Rebuild:** the geometry is rebuilt, so `op_entities` follows.
5. **Data §13 `SceneView` additions.** The existing methods do not change.
   - `entity_hovered: Signal(int, int)`: `(dim, tag)` under the pointer in the current
     pick mode; `(-1, -1)` when there is none.
   - `entity_clicked: Signal(int, int)`: the entity hit by a **single** click, as distinct
     from box picks and Ctrl toggles, which stay on `selection_changed`.
   - `set_entity_colors(dim, colors: dict[int, str], legend: list[tuple[str, str]])`
     fills geometry entities and shows a legend of `(label, colour)` entries. Empty
     arguments clear it.

   These are plain data with no Matplotlib, so a VTK viewport can implement them too.
6. **`BuiltGeometry.point_curves: dict[int, list[int]]`** (Data §4, alongside
   `curve_surfaces`) gives the curves that meet at each point. It comes from gmsh
   adjacencies in `_describe`. Inspect uses it to find the parts at a point.

Deferred to 3D (recorded in CONTINUE §7, not built now):
- show/hide or ghost parts;
- overlay items anchored to entities instead of `(x, y)`.

## 5. Tree layout after the change

```
Model — V-10 NAFEMS T4 · planar · t 1 m       (dock title; no extra root node)
Geometry                     2 steps
  lower strip                rectangle 0.6 × 0.2 m
Parts                        1
  ■ Plate                    Material 1 · 2 surfaces · t 1 m
Selections                   4
  ▬ cooled                   2 boundaries · Cooling
Materials                    1
  ■ Material 1               Aluminum, pure · library
Mesh                         T6 · 0.025 m · current
Initial Condition            20 °C
Loads & Boundary Conditions  3
  Cooling                    Convection · h 750 W/(m²·K), T∞ 0 °C → cooled
Contacts · Flow · Enclosures none          (dimmed; one line while all are empty)
Analysis Settings            steady
Results                      steady · 24 Nov 14:05 · out of date
  Temperature 1              contour
```

- **Columns:** column 0 is the name and the only editable column. Column 1 is generated
  text, never stored, refreshed on `model_changed`, `geometry_built`, `mesh_changed`,
  results changes and `stale_changed`.
- **Summaries:** `gui/tree_summary.py` has one function per kind. Load summaries are
  built from the registered form's title, its selection fields and `format_value` from
  `overlay_labels`, without the object's name, so a load registered later is summarised
  with no GUI change.
- **Addresses:** internal section keys and addresses stay the same (`"regions"`,
  `"solution"`, the result-provider addresses). Only the titles change ("Parts",
  "Results").

## 6. Freshness of the result (one definition)

A result is **current** exactly when `model/compare.py: model_changes(solved, current)`
returns an empty list.
- `solved` is the model stored in the attached results file (`Results.model`).
- `current` is the document's model.
- The tree summary, the results panel and the viewport title all use this test.

`Document.results_stale` keeps its present uses, such as solve gating, but the display no
longer reads it.

- **What counts as a change:**
  - Both models are serialised and normalised. The exclusions are display units, the
    cached selection tags (fingerprints are compared), the derived `all` selection and
    the result display objects.
  - Any difference that is left counts as a change, so nothing is ever reported current
    by mistake.
  - Each difference is then *described* through names and form labels, for example
    "Cooling: h 750 → 500 W/(m²·K)", "Mesh: global size 0.05 → 0.025 m", "Added load
    Base", "Cooling suppressed", "Geometry steps reordered".
  - A difference that no form describes falls back to the section, for example "Mesh
    refinements changed".
- **Missing snapshot:** the writer stores no model for model-less solves. When there is
  none, the header says "comparison unavailable".
- **Restart:** a restart rewrites the model metadata, so the comparison is against the
  latest model that was continued, and the header says so.
- **Header contents:** analysis, mesh (element types, node and element counts from
  `Results.mesh`) and "results written ‹created›". The time is labelled as file
  creation, because that is what `created` is.
- **Unchanged:** reopening a file keeps today's check that refuses a sidecar results file
  whose model differs (`file_tools.py`).

## 7. Tasks (in build order)

Tiers as in `docs/tasks.md`: [A] haiku, [B] sonnet, [C] main model. Each task has its own
tests, and the whole check passes before each commit.

1. **M11.49 [B] Vocabulary.** `model/vocabulary.py` (§3).
   - Applied to: toolbar labels and tooltips; the selection editor's texts ("2 boundaries
     picked"); selection-field labels in forms ("Interface boundaries", "Structured
     parts"); and validation and issue messages that name a dimension.
   - Tests include the synthetic 3D mapping and an empty, unbuilt model.
2. **M11.50 [B] Two-column tree.**
   - The column mechanism, the dock title and the View toggle for the column.
   - Column 0 only is editable, and the refresh signals are wired.
   - Summaries for what exists today: geometry steps, loads, mesh, initial condition,
     analysis, and a material's k.
   - Existing tree tests are kept, finding items by address.
3. **M11.51 [A] Fold empty sections.** One dimmed line while Contacts, Flow (no streams
   and no network) and Enclosures are all empty.
   - Its context menu offers Add contact, Add stream and Create network. There is no
     enclosure action, because M9 is held.
   - Undo back to empty folds the line again.
4. **M11.52 [B] Geometry steps highlight what they own.**
   - Extends `highlight_address` and uses the current build.
   - A step that owns nothing, or a build that failed, clears the highlight with a status
     message.
5. **M11.53 [C] Selection references, rename and delete (model layer).**
   - §4.3, with `all` reserved, the collision preflight and mesh invalidation.
   - Tests: a model using one selection in every possible place; refusals leave the model
     and the undo stack unchanged; and the node sets written by the next solve.
6. **M11.54 [B] Selections section and panel.**
   - The tree section, with role glyph, count and users.
   - Highlight, using the current build; a stale selection shows as stale.
   - The panel: rename, kind, entities, the parts it bounds, users as links, Add and
     Remove from viewport, and Delete (disabled while used or for `all`).
   - Page Up / Page Down step through the selections.
   - The issues panel gains a selection branch that navigates by address.
   - Depends on M11.49, M11.50 and M11.53.
7. **M11.55 [B] Name the selection at Apply.**
   - A "New name" box with an **unused** suggestion. Validation happens inside the same
     `Document.edit` that assigns the field.
   - Apply returns success explicitly.
   - Tests: re-Apply, and a refused collision, covering the widget, the model and the
     undo count.
   - Depends on M11.53.
8. **M11.56 [C] Parts.** §4.1.
   - Titles become "Part" and "Parts", and Add part names each part "Part N".
   - Inline rename. Region names and the highlight use `part_name`.
   - Issues navigate by address.
   - The per-region initial-condition editor, and summaries.
   - Depends on M11.50 and M11.53.
9. **M11.57 [B] Material source.** §4.2.
   - Provenance comes from the picker.
   - The panel shows the states: library, edited (which properties), custom, and
     entry not found.
   - Restore library values.
   - Restart and "edited" compare physical properties only.
   - Tests: built-in and user entries with the same name, a missing entry, and a
     provenance-only change against an old result.
   - Depends on M11.50.
10. **M11.58 [C] Model comparison (headless).** `model/compare.py` (§6).
    - Tests: a value change, suppress, a refinement change, geometry reorder, a table
      value change, a rename, display units ignored, the `all` selection and cached tags
      ignored, and the section fallback.
11. **M11.59 [B] Result header and freshness in the GUI.** §6, wired into the tree, the
    panel and the viewport title.
    - Tests: edit, undo, redo; an unchanged remesh; an edit during a solve; save and
      reopen; a missing snapshot; and a restart.
    - Depends on M11.50 and M11.58.
12. **M11.60 [B] Entity report.** `gui/inspect.py: entity_report(document, dim, tag)`
    gives the role and number, the selections that contain the entity, the active and
    suppressed loads and contacts on it, and **all** incident parts (an interface has
    two). It adds `BuiltGeometry.point_curves`.
    - Tests: a shared interface, a point, and a stale build.
    - Depends on M11.53 and M11.56.
13. **M11.61 [B] Hover and inspect wiring.** `SceneView.entity_hovered` and
    `entity_clicked`.
    - The tooltip follows the hover in a Part, Boundary or Point mode.
    - A single click shows the report in Properties and marks the tree items involved, but
      only while no selection editor or geometry tool is picking; an active tool takes
      precedence.
    - Depends on M11.60.
14. **M11.62 [B] Colour by part.** `SceneView.set_entity_colors`.
    - View > Colour by: Part / Material / None (default Part).
    - The tree swatches use the same `kind_color` colours.
    - Tests: fills keep holes, fills are hidden under a result contour, and the load
      legend stays.
    - Depends on M11.56.
15. **M11.63 [C] Rename geometry steps.** §4.4.
    - Inline rename in the tree in one undo step.
    - Tests: references from point, line, arc, spline, hole loop, boolean, transform and
      delete; rename, build, undo, rebuild; and refusals.
    - Depends on M11.52.
16. **M11.64 [B] Guide and walkthrough.**
    - Rewrite the V-10 and V-17 steps in `docs/gui-walkthrough.md`, plus
      `guide/getting-started.md` and the tutorial pages, for the new names and wording,
      with the expected tree for each case.
    - **The owner's re-review in M8.G depends on this task.**
    - Depends on M11.49–M11.63.

M11.6 (release review) then depends on M11.7–M11.64, M8.G and M11.1.

## 8. The independent review and what changed

Codex reviewed the first draft on 2026-11-24 and recommended "revise before
implementation". Its findings, in its own numbering, and where each went:

1. **`all` is rebuilt by every build.** It is now reserved (§4.3).
2. **Geometry rename missed point, line, arc and spline references.** It now walks
   `REF_RULES` (§4.4).
3. **Two conflicting freshness definitions.** There is now one comparison (§6).
4. **A form-based diff misses suppress, refinements and reorder.** The comparison now
   normalises the serialised model first and only then describes the differences (§6).
5. **The header must handle missing snapshots and restarts** (§6).
6. **Selection edits change the mesher's node sets.** They now make the mesh stale
   (§4.3).
7. **Writable reference locations.** One traversal and a collision preflight (§4.3).
8. **Apply could report success after a collision** (M11.55).
9. **Part-name uniqueness with fallback names, and the initial-condition editor**
   (§4.1).
10. **Material provenance against the restart check** (§4.2).
11. **No domain-dimension source.** `domain_dim` in the model layer (§3).
12. **The click owner, incident parts and stale builds for highlight and inspect**
    (§4.5, §4.6, M11.60–M11.61).
13. **Issue links by address** (M11.54, M11.56).
14. **Tree editing, refresh, folded Flow actions, and no enclosure action** (§5,
    M11.51).
15. **Load summary text and the legend** (§5, §4.5).
16. **Order:** vocabulary first, summaries alongside their data, the comparison and the
    report as headless tasks, and the walkthrough before the re-review (§7).
