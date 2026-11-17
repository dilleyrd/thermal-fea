# Handover notes for the build

Written on 2026-11-16, after M8.12, by the agent that built M0 – M8.12, for whoever
continues: a different primary model, a new session, or a person. `PLAN.md` and the files
in `docs/` remain the specification. This file records only what is **not** written there:
how the work has been run, what the code offers beyond the plan, and where the remaining
tasks are likely to go wrong. Update it when any of this changes.

## 1. How a task is run

1. Read `PLAN.md` §3, §4, §7, then the task in `docs/tasks.md` and the sections it names.
2. Decide who writes it, by the tier in the task (Plan §4):
   - **[A]** — the small model as a subagent.
   - **[B]** — the mid model as a subagent.
   - **[C]** and gates — the primary model. Mechanical parts of a [C] task or gate
     (example scripts, tests that restate the verification table, forms, boilerplate) may
     still go to a subagent; the numerical core and the review stay with the primary.
3. A subagent gets a self-contained brief (it knows nothing about the project): the task
   text verbatim; the files to read first; the existing functions and classes to reuse,
   with their real signatures; the binding rules (below); the tests to write; the two
   finishing commands; and what to report. It must not commit, push or tick boxes.
4. The primary then checks the work itself, whoever wrote it:
   - `.venv/Scripts/ruff.exe check .` prints "All checks passed!";
   - the **whole** suite passes (`timeout 500 .venv/Scripts/python.exe -m pytest -q`,
     with `QT_QPA_PLATFORM=offscreen`); the count never goes down;
   - `git status` and `git diff` of existing files: no test weakened or deleted, no public
     signature changed, nothing outside the task;
   - a read of the new code against the rules of Plan §7, and of every formula or number
     against `docs/theory.md` / `docs/verification.md` (a subagent's claim that it copied
     them is not evidence);
   - fix small defects directly; send larger ones back to the same subagent.
5. Record every choice the documents leave open in `docs/OPEN_QUESTIONS.md` (next free
   number is **Q23**; GUI choices are collected in Q21).
6. Tick the box, commit as `M<n>.<k>: <task title>`, push to `origin` (never force-push),
   and give the owner a one-line status.

Rule 11 of Plan §4 governs unattended runs: stop at a task marked "Human", at a gate that
cannot be passed, or after three failed attempts. The owner has twice told the build to
continue past a human gate (M5.G) while they reviewed; do that only when told.

### Rules that subagents break unless told

- Never derive or retype a formula, and never invent a property, constant, tolerance,
  validity limit or default value. If it is not in `docs/` or the code, leave it out and
  report it.
- Never weaken or delete a test; tolerances are specification.
- No `print` in `src/`; type hints and NumPy docstrings with units; line length 100.
- No `if etype == ...`, no literal space dimension; element types through the registry.
- `gui/` holds no numerics; every model edit goes through `Document.edit`; the viewport is
  reached only through `SceneView`; a GUI module may import Matplotlib only if it is in
  `MATPLOTLIB_GUI_ALLOWED` (`tests/unit/test_layers.py`).
- Do not change signatures given in `docs/data-model.md` or the task text.

### This machine

- Use only `.venv/Scripts/python.exe` and `.venv/Scripts/ruff.exe`. Install nothing.
- Shell heredocs that write files fail here. Write files with the editor tools; a short
  `python - <<'PYEOF'` patch script with asserted anchors and no apostrophes is fine.
- Put a `timeout` on every long command. A test with an endless loop once hung the shell
  for ten minutes.
- The owner often runs sessions remotely: no real GUI windows (Qt offscreen, Matplotlib
  `Figure` + Agg, never `pyplot`), no modal dialogs in code that tests run, nothing that
  touches networking, power or other processes.
- Threads (since M8.9): every wait in a test is bounded; every thread is joined.

## 2. What exists beyond the plan

The plan names modules; these are the mechanisms later tasks should build on. Details
and reasons are in the open questions cited.

| Mechanism | Where | Notes |
|---|---|---|
| Four assembly channels | `solver/assembler.py` | `add_matrix` (K), `add_vector` (F), `add_tangent` (tangent only), `add_residual` (residual only), `add_sparse`. Q8. |
| Constraints | `solver/terms.py`, `solver/problem.py` | `Constraint` protocol; `CompiledProblem.prescribed(t)`. Q8. |
| Extra DOFs | `solver/dofs.py: DofMap.add_extra` | Used by streams (`stream:<name>`); results as `/steps/fields/<name>` with location `extra:<group>`. |
| Flow providers | `flow/provider.py`, `flow/coupling.py` | `problem.providers`; `update` before every assembly. Q20. |
| Facet integration | `physics/batches.py: facet_batches`, `FacetBatch` | Weights `∫ N g ds`; see `flow/stream.py: setup` for face weights w_j and areas. |
| Sign convention | everywhere | A reported heat flow is positive **into** the body. Q11. |
| Energy balance | `post/energy.py`, `post/reactions.py` | θ-weighted per step (Q16); `gross` scale (Q11); a constraint with `exchanges_heat = False` reports nothing. |
| First step θ = 1 | `solver/transient.py` | When the start is out of equilibrium. Needed for V-21. Q14. |
| Verification pattern | `examples/vNN_*.py`, `tests/verification/cases.py` | `run(etype) -> dict`, loaded with `load()`; `check_balance`. Helpers in `examples/common.py`. |
| Hand-built problems | `tests/unit/handmade.py` | `make_problem`, `make_state`: physics tests without gmsh. |
| Tangent test pattern | `tests/unit/test_radiation_ambient.py` | Tangent against finite differences of the residual. |
| Forms | `core/forms.py`, `model/*_forms.py` | `FormSpec` / `FieldSpec`, no Qt; registered per class. Q21.6. |
| GUI wiring | `gui/app.py: main` | One `attach_*` function per feature; controllers with one entry point; panels through `gui/panels.py: register_panel`. |
| Background work | `gui/worker.py` | `BackgroundTask`, `SerialWorker` (all gmsh calls on one thread). Q21.11. |

## 3. State on 2026-11-16

- Done and pushed: M0 – M7 and M8.1 – M8.14; M5.G confirmed by the owner. 1794 tests.
- Next: **M8.G, a human gate**: the owner builds V-10 and V-17 in the GUI following
  `docs/gui-walkthrough.md` and fills in the friction log at its end. The GUI has never
  been opened on a real screen — every GUI test ran offscreen, the end-to-end test of
  M8.14 included — so expect layout and usability findings. Start it with
  `.venv\Scripts\python.exe -m thermalfea.gui.app`. Friction points already known are
  listed in section 4 of the walkthrough. `gui/app.py: build_application` builds the
  whole application without showing it; tests use it.
- On 2026-11-16 the owner put **M9 (enclosure radiation) and M10.2 (phase change) on
  hold** and asked for M10.1 (thermal contact) while they do the M8.G review. M10.1 is
  done (Q22). Do not start M9 or M10.2 until the owner says so.
- On 2026-11-16 the owner also put **M10.5 (report) on hold** as a future to-do item.
  Skip it; do not start it until the owner says so.
- On 2026-11-16 the owner said **not to implement anything associated with scripting**
  for now (ideas discussed: export of a GUI model as a Python script, `api.add_*`
  wrappers for loads, a parameter-sweep helper, public access to the system matrices).
  None of these is a task; do not add them without the owner asking.
- Awaiting the owner's confirmation, none blocking: Q11, Q14, Q17.2, Q18.2, Q20, Q21, Q22, Q23, Q24.
- Known gaps, recorded in Q21 and Q24: a few read-outs are still SI only (Q24.5); GIF export blocks the window; the stream "pick path points" toggle
  does not exclude the probe and the chart path pick; MP4 export is untested (no ffmpeg).

## 4. Notes on the remaining tasks

These point at where the specification is and at what already exists. They are not
derivations; the formulas are in `docs/theory.md`.

**M9.1 – M9.2 view factors (Theory §10.1; V-22a–d).** Pure geometry on arrays; keep it
free of the mesh classes so it can be tested on hand-written segments. Things that go
wrong: the facing test needs outward normals, so the orientation of each facet relative
to its parent element must be taken from the mesh, not assumed; a sight line always
touches the two segments it joins and their neighbours at shared end points, so the
blocking test must not count contact at an end point as an intersection; V-22a asks for
1e-10 on single segments, which only the unsubdivided crossed-strings path can give.
The smoothing loop (reciprocity, then row scaling, five times) is specified exactly; do
it as written, and report the row sums **before** smoothing (the M9.2 acceptance).

**M9.3 radiosity coupling (Theory §10; V-23, V-24).** The enclosure is a `Term`. Its heat
is nonlinear in T and belongs in the residual-only and tangent-only channels
(`add_residual`, `add_tangent`), exactly as `physics/radiation_ambient.py` does for
radiation to ambient — read that term and its test first. The tangent block is dense
(insert in full for n ≤ 3000, else its diagonal, as §10 says); a dense block makes the
matrix unsymmetric in general, so set `symmetric = False`. Face temperatures and areas
use the same weights as the stream walls (`flow/stream.py: setup`). The acceptance asks
for the tangent against finite differences: copy the pattern of the ambient-radiation
test. Report the net radiative heat through `boundary_heat` with the positive-in
convention, and check the energy balance closes on V-23. Model class: `Enclosure` in
`model/bcs.py`; validation must reject enclosures in axisymmetric models until M9.5.

**M9.5 axisymmetric view factors (Theory §10.2).** The hardest remaining numerics. The
text gives the kernel and the validation cases but not the quadrature orders or the
subdivision; choosing them is a decision to record in `OPEN_QUESTIONS.md`, with a
convergence test that shows the chosen orders meet the closed forms.

**M10.1 thermal contact (Theory §11; V-35).** Two parts. The mesh step duplicates nodes
along the contact curve; the rule for which side gets the new nodes and when an end point
is duplicated is in the task text — follow it literally, and test on a hand-built mesh
that facets, `parent_elem` and node sets stay consistent. Then a `Term` over matched edge
pairs. V-35 has a 1e-9 tolerance, so the pairing of the two sides' nodes must be exact,
not nearest-neighbour within a loose tolerance.

**M10.2 phase change (Theory §12; V-36).** The forced settings (lumped capacitance,
backward Euler, `max_dT_per_step`) must be applied by the compiler and visible to the
user, not silently; the capacitance term is in `physics/capacitance.py`.

**M10.4 unit systems (done, Q24).** `core/units.py` holds one unit per quantity and the
presets; forms convert through `to_display`/`from_display` in `core/forms.py`; plots and
read-outs take `Results.display_units`. Tools > Units... changes them (undoable, nothing
goes stale). A new form field with a dimension needs a `quantity`; a new quantity is one
entry in `_TABLE` plus a field of `UnitSettings`.

**M10.6 restart.** The results writer always creates a new file
(`solver/results_writer.py: open`); appending needs a second way to open it, and the
θ-method needs g(T_n, t_n) of the last stored step (`solver/transient.py`), which is
recomputed, not stored.

**M11.3 performance.** Element geometry is cached per problem (`problem.cache`); the
transient driver already reuses the factorisation in the linear case with constant Δt.
Measure before changing anything.

**M11.6 release review.** Every entry of `OPEN_QUESTIONS.md` must be resolved or
documented; several are waiting for the owner (section 3).

## 5. If the primary model changes

Nothing in the repository names a model. The tiers of Plan §4 map to "small, mid,
strongest available". Two things compensate for a less capable primary on the [C] tasks:

- Let the verification cases decide. Write the verification example and its test **first**
  from `docs/verification.md`, run it, and treat any failure as a code error (rule 5). Do
  not move on while a case passes only at a looser tolerance.
- After each [C] task, have a second agent that did not write the code review the diff
  against the theory section, formula by formula, and report discrepancies. Plan §4 asks
  for exactly this ("strongest model, or a human review afterwards").
