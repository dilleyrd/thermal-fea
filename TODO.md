# What the agents need from the owner

State on 2026-11-22. This file lists everything that waits on you, the owner, in the order
it matters. Each item says what is needed, the options and the agent's recommendation
where there is a choice, what it unblocks, and the files to read.

Answer in any form, for example "D1: (a)". The agent then:
- records the answer in `docs/OPEN_QUESTIONS.md`;
- changes `docs/theory.md` or `docs/data-model.md` where the answer requires it, which an
  agent may not do on its own (CLAUDE.md rules 2, 3 and 6);
- builds the task;
- removes the item from this file.

**Contents**
1. Decisions that block tasks
2. Testing and evaluation that only a person can do
3. Holds and priorities
4. Confirmations of interim choices (block nothing)
5. Access and tools

Quick summary:

| # | Item | Kind | Blocks |
|---|---|---|---|
| 1.1 | D1, convergence reference at equilibrium | Theory change | M11.17 |
| 1.2 | D2, fluid rows with θ < 1 | Theory change | M11.18 item 2.1-3 |
| 1.3 | D3, time-step error estimate | Theory change | M11.19 |
| 1.4 | D6, term results in the results file | File layout | M11.28 (contact heat) |
| 1.5 | Q27.3, oscillation-warning sentence | Theory wording | M11.10 |
| 1.6 | D9, contradictions in the documents | Document fixes | Release review M11.6 |
| 1.7 | D10, packaging and licence | Packaging | M11.30, release |
| 1.8 | D5, inclined plate beyond 90° | Correlation range | Part of M11.23 |
| 1.9 | D4, network near zero pressure drop | Theory change | Nothing yet |
| 1.10 | D7, position-dependent functions | Data-model change | Part of M11.23 |
| 1.11 | D8, `api.solve` without a built geometry | Behaviour | Part of M11.23 |
| 1.12 | D13, scope of new commands | Scope | Nothing |
| 1.13 | D12, design choices that can wait | Design | Nothing yet |
| 2.1 | M8.G, build V-10 and V-17 in the window | Human gate | Release |
| 2.2 | M11.1, check properties and correlations | Human task | Release (Plan §6 item 7) |
| 2.3 | Visualisation and pump example | Evaluation | Nothing |
| 3.x | Holds, priorities, 3D | Direction | Much of the remaining work |
| 4.x | Interim choices, Q1–Q26 | Confirmation | Nothing |
| 5.x | GitHub token, ffmpeg | Access | Automatic publishing, MP4 |

---

## 1. Decisions that block tasks

The options and the evidence for D1–D13 are in `docs/review-2026-11-21-evaluation.md`,
§4, and are listed in `docs/OPEN_QUESTIONS.md` Q29. The review itself is `REVIEW-2.md`.

### 1.1 D1: convergence at radiative equilibrium (Theory §5) — blocks M11.17

**Problem.** Newton's convergence test compares the residual with
F_ref = max(‖F‖₂, ‖K T‖₂, 1e-12). When a body sits at equilibrium with its surroundings,
for example radiation to 300 K starting at 300 K, F and K T cancel and F_ref falls to
round-off. The test can then never pass: the run stops at the iteration limit with an
error, although the answer is right. This was reproduced; the residual was 38 % of F_ref.

**Options.**
- **(a) Recommended.** Add a term to F_ref that cannot cancel, ‖|K|·|T|‖₂. The start-up
  check in `src/thermalfea/solver/transient.py` already uses it.
- **(b)** Also accept convergence when the temperature change is below `ttol` and the
  residual is below an absolute floor in watts. The floor would need a value from you.

**Unblocks.** M11.17, which changes Theory §5 and then `src/thermalfea/solver/nonlinear.py`.

**Files.**
- `docs/theory.md` §5;
- `src/thermalfea/solver/nonlinear.py` (`Assembled.reference`, the convergence test);
- `src/thermalfea/solver/transient.py` (`StepSystem.reference`, the `scale` of the start-up
  check);
- `REVIEW-2.md` item 2.1-1.

### 1.2 D2: fluid rows when θ < 1 (Theory §6) — blocks item 2.1-3 of M11.18

**Problem.** Stream fluid nodes have no heat capacity; their equations are algebraic.
With Crank–Nicolson (θ = 0.5), an imbalance in those equations at the start of a step
flips sign every step, so the outlet temperature oscillates. A fresh run hides this with
its θ = 1 first step. A restart skips that step (Q25.2), and so does a change of flow
within a run. Found by reading the code; not reproduced yet.

**Options.**
- **(a) Recommended.** Always treat the rows without capacitance (the fluid rows) fully
  implicitly, θ = 1, whatever θ the body uses. This also covers flow changes within a
  run.
- **(b)** On a restart, take one θ = 1 step when the stored state is not in equilibrium.

**Unblocks.** Item 2.1-3, the last part of M11.18.

**Files.**
- `docs/theory.md` §6 and §9.1;
- `src/thermalfea/solver/transient.py` (`StepSystem`, `solve_transient`);
- `src/thermalfea/flow/stream.py`;
- `docs/OPEN_QUESTIONS.md` Q25.2 and Q14;
- `REVIEW-2.md` item 2.1-3.

### 1.3 D3: the time-step error estimate (Theory §6.1) — blocks M11.19

**Problem.** After a fast change of a prescribed temperature, the step size collapses.
In the reproduction, a 100 K rise over 1 ms took 69 steps with 15 rejected and Δt down
to 1e-6 s, against 21 steps for a constant load. The cause is in Theory §6.1:
- the error estimate includes the prescribed nodes, whose jump the predictor cannot
  follow;
- the predictor is not restarted after a breakpoint of a table.

The review also found defects in the jump detector `_jumps`. It gives a false positive
when one step spans a whole period, misses a step that is continuous from the right, and
lets its probe underflow when Δt/t < 1e-8.

**Recommended.** Yes to both changes:
- leave prescribed DOFs out of the error e and out of max |ΔT|;
- restart the predictor, with no error test on the next step, after a mandatory time
  where a table has a breakpoint.

**Unblocks.** M11.19, which changes Theory §6.1 and then the code.

**Files.**
- `docs/theory.md` §6 and §6.1;
- `src/thermalfea/solver/timestep.py` (`error_estimate`, `StepController`);
- `src/thermalfea/solver/transient.py` (`_jumps`, `mandatory_times`);
- `docs/OPEN_QUESTIONS.md` Q14 and Q15;
- `REVIEW-2.md` item 2.1-5.

### 1.4 D6: term results in the results file (Data §9) — blocks M11.28

**Problem.** The solver computes the heat across each contact (`contact_heat`) and the
mean h of each correlation load, but never stores them. The window cannot show them, and
the pump showcase has to recover the contact heat by post-processing.

**Recommended.** Yes:
- store `Term.results()` in new groups of the results file, next to `/reactions` and
  `/fluid`;
- raise the schema version, so that older files still open;
- show the values in the window;
- make the showcase read them.

**Unblocks.** M11.28, and it closes the known contact-heat gap.

**Files.**
- `docs/data-model.md` §9;
- `src/thermalfea/solver/results_writer.py`;
- `src/thermalfea/post/results.py`;
- `src/thermalfea/physics/contact.py` (`contact_heat`, Q22.6);
- `src/thermalfea/gui/flow_results.py` and the result panels;
- `examples/pump_closure/` and `examples/pump_closure/showcase/fluxlib.py`.

### 1.5 Q27.3: wording of the oscillation-warning rule (Theory §6.1) — blocks M11.10

**Problem.** The first time step that the program suggests itself can trigger its own
"may oscillate" warning. You chose option (ii) on 2026-11-17: keep the suggestion and do
not warn about it. Before M11.10 is built, the rule has to be written into Theory §6.1.

**Needed.**
1. Confirm, or reword, this sentence, to go after "Oscillation warning: …":
   > "The warning is not logged when Δt is the suggested initial step Δt₀; it applies to
   > a step set by the user and to steps chosen by the step control."
2. Should later steps chosen by the automatic step control still be warned about? The
   sentence says yes, as now.

M11.10 is also on hold (section 3.1); you need to release it too.

**Files.**
- `docs/theory.md` §6.1;
- `docs/OPEN_QUESTIONS.md` Q27.3;
- `docs/tasks.md` M11.10;
- `src/thermalfea/solver/transient.py` (`first_step_size`, the `check_dt` hook).

### 1.6 D9: contradictions in the documents — needed for the release review (M11.6)

Each needs a yes or no; an agent may not edit these documents on its own.

1. **Sign of heat flows.** Theory §7 says a heat flow through a boundary set is positive
   *out of* the body. The code, Q11 and the guide all use positive *into* the body.
   Recommended: correct Theory §7 to "positive into the body".
2. **Data §9 is out of date.**
   - `/fluid/<i>` and `/reactions/<i>` are numbered, with the name in an attribute.
   - Data §8 lacks `CorrelationConvection.params` (Q17.1) and `Stream.h_override`
     (Q18.1).

   Recommended: bring Data §8 and §9 up to date with the code.
3. **`thermalfea export` in PLAN.md.** The command does not exist. Drop the line, or make
   it a task. It falls under your "no scripting" hold (see 1.12).
4. **Theory §6.1 says the suggested Δt₀ is "shown in the GUI".** It is not. Drop the
   words, or add a task to show it.
5. **Q20.1 describes the old behaviour.** It says the providers are updated "before every
   assembly"; since M11.20 that is once per Newton iteration. This one is a correction of
   the record, and an agent can make it if you agree.

**Files.**
- `docs/theory.md` §6.1 and §7;
- `docs/data-model.md` §8 and §9;
- `PLAN.md`;
- `docs/OPEN_QUESTIONS.md` Q11, Q17, Q18 and Q20;
- `guide/` (regenerated by `scripts/build_guide.py`).

### 1.7 D10: packaging and licence — needed for M11.30 and the release

1. **Licence.** The repository has none. Without one, nobody else may legally use, copy
   or change the code, even though it is public on GitHub. Choose one, for example MIT,
   BSD-3-Clause, Apache-2.0 or GPL-3.0, or say that it stays proprietary.
2. **pandas.** It was added to the core dependencies on 2026-11-20 at your request, for
   the pump showcase only; the program itself does not use it. Recommended: move it to an
   optional extra `examples`, installed with `pip install thermalfea[examples]`. Or keep
   it in the core.
3. **Duplicate images.** Twelve showcase images (4.2 MB) are stored twice, in
   `examples/pump_closure/showcase/` and in `guide/examples/img/`, because MkDocs only
   publishes files inside `guide/`. Recommended: keep both copies.
4. **A README.** The repository has none. Should an agent write a short one: what the
   program is, how to install it, and a link to the guide?

**Files.**
- `pyproject.toml`;
- `LICENSE` (new);
- `README.md` (new);
- `guide/examples/img/` and `examples/pump_closure/showcase/`;
- `guide/installation.md`.

### 1.8 D5: inclined natural convection beyond 90° — part of M11.23

**Problem.** For an inclination |θ| > 90°, g cos θ is negative, Ra is negative, and the
correlation returns NaN without any message. Theory §8 gives the validity range only as
"θ ≤ 60°".

**Needed.**
1. Should |θ| > 90° be refused with an error? Recommended: yes.
2. Is the validity range symmetric, |θ| ≤ 60°, or one-sided, −90° < θ ≤ 60°? Which sign
   is the heated surface facing up?

**Files.**
- `docs/theory.md` §8 (correlation table, `inclined_natural`);
- `src/thermalfea/convection/correlations.py` and `src/thermalfea/convection/fluid_props.py`;
- `src/thermalfea/convection/correlation_info.py` (the validity text);
- `REVIEW-2.md` item 2.1-10.

### 1.9 D4: pipe network near zero pressure drop (Theory §9.2) — blocks nothing yet

**Problem.** A network with a nearly balanced bridge and a loss branch does not converge.
A 1e-7 imbalance stops at the 200-iteration cap, because the conductance of a loss
branch behaves like 1/√|Δp| near Δp = 0.

**Options.**
- **(a) Recommended for now.** Keep the scheme, and give a clear error naming the branch
  and suggesting a remedy.
- **(b) Later.** Regularise the loss-branch conductance near Δp = 0. This changes Theory
  §9.2 and needs a regularisation width from you or from a reference.

**Files.**
- `docs/theory.md` §9.2;
- `src/thermalfea/flow/network.py`;
- `docs/OPEN_QUESTIONS.md` Q19;
- `REVIEW-2.md` item 2.1-7.

### 1.10 D7: functions that depend on position — part of M11.23

**Problem.** A total load in watts (`HeatPower`, `HeatFlow`) that is given as a function
of x or y is evaluated at the origin without any message. Rejecting it needs a way to
tell whether a function depends on position.

**Recommended.** Add a read-only attribute `depends_on_position` to `Function`, next to
the existing `depends_on_T`. That is an addition to a Data-model interface, so it needs
your approval.

**Files.**
- `docs/data-model.md` (the `Function` protocol);
- `src/thermalfea/core/functions.py`;
- `src/thermalfea/model/validate.py`;
- `src/thermalfea/physics/` (the load terms).

### 1.11 D8: `api.solve` without a built geometry — part of M11.23

**Problem.** `api.solve(model, mesh)` validates the model only when `built=` is passed,
which is documented in Q12.1. Without it, a model with, say, a negative conductivity
reaches the solver unchecked.

**Recommended.** Without `built`, run the checks that need only the model: materials,
settings, loads and streams. Keep skipping only the checks that need the geometry. The
alternative is to keep the documented skip.

**Files.**
- `src/thermalfea/api.py` (`solve`);
- `src/thermalfea/model/validate.py`;
- `docs/OPEN_QUESTIONS.md` Q12.1.

### 1.12 D13: scope — new commands and API exposure

The review suggests new commands `thermalfea validate`, `summary` and `export`, and
exposing the post-processing helpers in `api`. The agent has treated these as covered by
your "Don't implement anything associated with scripting right now" and excluded them.

**Needed.** Confirm that they stay excluded, or say which you want as tasks.

**Files.** `src/thermalfea/cli.py`, `src/thermalfea/api.py`, `REVIEW-2.md` section 4.

### 1.13 D12: design choices that can wait — block nothing yet

Each is a behaviour that no document settles. Reply to any of them when convenient; until
then the current behaviour stays.

1. **One heating flag per stream, or one per cell**, for Dittus–Boelter. One per stream
   now; M11.21 fixed how it is computed.
2. **Warnings when a duct correlation is used outside its validity range.** Off now.
3. **Selections:**
   - whether matching a selection after a rebuild should also use the bounding box
     (Data §5 names the centre and measure only);
   - what to do when two entities match one stored fingerprint.
4. **Transforms:**
   - whether `Transform(copy=False)` should move the points that belong to the shape;
   - whether points and curves, not only surfaces, can be transformed and used by a
     Line.
5. **User fluids.** The library has a place for fluids defined by the user, but it is
   never read.
6. **Point loads at a contact.** When a contact splits the mesh, a point load at the end
   of the contact curve stays on the side of the lower region id (Q22.5).
7. **"Short duration" tolerances in `src/thermalfea/solver/run.py`:** what counts as a run too short to
   take a step.

**Files.** `docs/review-2026-11-21-evaluation.md` §2.2 and §4 item 12; `REVIEW-2.md`.

---

## 2. Testing and evaluation that only a person can do

### 2.1 M8.G human gate: build V-10 and V-17 in the window

**What.** No person has ever used the program on a real screen; every GUI test runs
offscreen. The gate is:
1. start the program with `.venv\Scripts\python.exe -m thermalfea.gui.app`, as in
   `guide/installation.md`, or with `thermalfea-gui` once M11.30 adds that entry point;
2. build verification cases V-10 and V-17 from an empty model, following
   `docs/gui-walkthrough.md`;
3. solve them, and check the results against the targets in `docs/verification.md`;
4. list every point of friction: anything unclear, slow, wrong or missing. Screenshots
   help.

The agents will turn the list into tasks. Since the last look, the window changed in
M11.24 (colour bar), M11.25 (New, Open, remesh, closing the solve dialog) and the M10
work (contacts, DXF import, units, restart).

**Unblocks.** The M8.G box, and the release review M11.6.

**Files.**
- `docs/gui-walkthrough.md` (the steps);
- `docs/verification.md` (V-10, V-17);
- `guide/getting-started.md` and `guide/tutorials/` (the user's view);
- `guide/limitations.md` (known defects, so that you can skip them);
- `src/thermalfea/gui/`.

### 2.2 M11.1 human task: check the property tables and the correlations

**What.** Compare every material and fluid property table, and every correlation and its
validity range, with a heat-transfer reference text, for example Incropera, *Fundamentals
of Heat and Mass Transfer*. Record the source and the edition of each.

Until this is done, the user guide says "source not yet recorded" for every correlation
and table. Plan §6 item 7, a release criterion, is not met.

**Specific points found so far:**
- **Air.** The data model says "Air at 1 atm", but the densities match 1 bar (D11).
  Which is intended?
- **Water.** The table has only 5 points. Is the linear interpolation between them
  accurate enough over the range?
- **Citations.** Only the names the theory text gives are recorded: Churchill–Bernstein,
  Churchill–Chu, Gnielinski, Dittus–Boelter and Churchill 1977 (Q17.6, Q26.2).

**How the agent helps.** It can produce a table of every value to check, with the file
and line of each, if you ask for one.

**Unblocks.** The sources in the guide, and the release.

**Files.**
- `docs/data-model.md` §6 (property tables);
- `docs/theory.md` §8 and §8.1 (correlations and ranges);
- `src/thermalfea/materials/data/solids.json`, `src/thermalfea/materials/data/fluids.json` (the stored
  values);
- `src/thermalfea/convection/correlations.py` and `src/thermalfea/convection/fluid_props.py`;
- `guide/correlations.md` and `guide/materials.md` (generated by
  `scripts/build_guide.py`);
- `docs/OPEN_QUESTIONS.md` Q17.6 and Q26.2.

### 2.3 Visualisation and the pump example: evaluation you planned

1. **Visualisation over more boundary conditions.** In the M5.G review (2026-11-16) you
   said you would test the visualisation over a wider range of boundary conditions once
   the build is complete. This includes MP4 export, which has never run because ffmpeg is
   not installed (5.2).
2. **The pump main-closure example.** All its inputs are marked illustrative. If it is to
   represent a real design, provide or confirm:
   - the dimensions;
   - the materials;
   - the six contact conductances;
   - the heat-up history;
   - the fluid temperatures.

**Files.**
- `examples/pump_closure/` (model, run script, `out/*.h5`);
- `examples/pump_closure/showcase/` (figures `fig01`–`fig07`);
- `guide/examples/pump-closure.md`;
- `src/thermalfea/post/plots.py` and `src/thermalfea/post/export.py`.

---

## 3. Holds and priorities

### 3.1 Work on hold: release when you want it built

| Task | What | Files |
|---|---|---|
| M9.1–M9.5 | Enclosure radiation: view factors, obstruction, radiosity, panel, axisymmetric | `docs/theory.md` §10, `docs/tasks.md` M9 |
| M10.2 | Phase change (V-36) | `docs/theory.md` §12 |
| M10.5 | Self-contained HTML report | `docs/tasks.md` M10.5 |
| M11.7 | Axisymmetric choice in the Analysis Settings panel | `docs/tasks.md`, Q27.1 |
| M11.8 | Display fixes: unset mass flow, cross-section in the HTC calculator, "steady state" label | Q26.4 (b), (c), (f) |
| M11.9 | Dialog for new correlation and radiation loads | Q27.2 |
| M11.10 | No false oscillation warning for the suggested first step (needs 1.5 too) | Q27.3 |
| Scripting | Exporting a model as a script, `api.add_*`, sweep helpers, public matrices | your instruction of 2026-11 |

### 3.2 Order of the remaining work

These need no decision and can be built whenever you say:
- **Review fixes:**
  - M11.12, input guards (extended);
  - M11.13, mesh out of date after selection edits;
  - M11.14, path locator;
  - M11.15, position-dependent temperatures (extended);
  - M11.16, early output times.
- **More review fixes:**
  - M11.23, validation coverage, except the parts that wait for D5, D7 and D8;
  - M11.26, meshing;
  - M11.27, inputs and outputs;
  - M11.29, GUI flow and selection fixes;
  - M11.30, packaging and documentation, except the parts that wait for D10.
- **Not on hold but not started:**
  - M11.2, a report of the verification suite;
  - M11.3, performance;
  - M11.5, a Windows installer (PyInstaller).

**Needed.** The order, or "continue in the listed order". Without other instructions the
agent continues with M11.12 → M11.16, then M11.23, M11.26, M11.27, M11.29 and M11.30.

**Files.** `docs/tasks.md`; `docs/CONTINUE.md` §5.

### 3.3 3D

You asked about the effort on 2026-11-21. The estimate was 35–55 tasks, in three phases:
1. headless 3D through the API and the command line, viewed in ParaView;
2. a 3D window;
3. streams and enclosure radiation in 3D.

**Needed.** Whether to plan it. If yes, the agent writes milestone M12 into
`docs/tasks.md`; nothing is written until you ask.

**Files.** `docs/CONTINUE.md` §7; `PLAN.md` §7; `docs/review-2026-11-21-evaluation.md`
§2.4.

---

## 4. Confirmations of interim choices (block nothing)

During the build the agents had to fill gaps the documents leave open. Each choice is in
use and tested. Confirm it, or say what to change. A change becomes a task.

| Question | The choice made | Where |
|---|---|---|
| Q1 | `Material(name, k, rho, cp, *, k2=None, phase_change=None)`: `k2` and `phase_change` are keyword-only | `src/thermalfea/materials/`, Data §6 |
| Q11 | Every reported heat flow is positive into the body (see 1.6, item 1) | `src/thermalfea/post/reactions.py` |
| Q14 | A start that is out of equilibrium with the loads counts as a discontinuity: θ = 1 on the first step | `src/thermalfea/solver/transient.py` |
| Q17.2 | The characteristic length of horizontal plates is the length of the selection, not area/perimeter | `src/thermalfea/convection/` |
| Q18.2 | One c_p per stream, at the inlet temperature | `src/thermalfea/flow/stream.py` |
| Q20.1–8 | How the providers are called, the initial fluid temperatures, one stream per duct branch, reversed flow refused, the enthalpy heat flow, the `/fluid` layout, the tighter V-29 tolerance, symmetry only a hint (note: 20.1 is now once per iteration, see 1.6) | `src/thermalfea/flow/`, `src/thermalfea/solver/` |
| Q21.1–12 | GUI choices: what an edit makes out of date, pseudo-dimensions for nodes and elements, picking rules, pasting tables, tree actions, geometry tools (angles in radians), threads, result objects as view state | `src/thermalfea/gui/` |
| Q21.7 | Velocity is shown in m/s with no unit choice. Do you want one? | `src/thermalfea/core/units.py` |
| Q22.1–7 | Contact: the mesh is split at compile time; the duplication rule; T-dependent conductance refused; the geometry factor from the lower region id; point loads on the lower side; the reported heat; a "Contacts" node in the tree | `src/thermalfea/core/contact_split.py`, `src/thermalfea/solver/compile.py` |
| Q23.1–7 | DXF: the join tolerance; entities ignored or refused; nesting rule; `$INSUNITS` not read; arcs split at 120° | `src/thermalfea/geometry/dxf.py` |
| Q24.2 | The unit presets SI (mm) and US customary, with the units listed in Q24.2 | `src/thermalfea/core/units.py` |
| Q24.5 | Still SI only: Transform parameters, the HTC calculator, the solve dialog, the correlation parameters, CSV and VTU export | `src/thermalfea/core/units.py`, `src/thermalfea/gui/` |
| Q25.1–6 | Restart: how it is asked for, what matches an uninterrupted run, automatic stepping on a restart, the `last_step` attribute | `src/thermalfea/solver/run.py`, `src/thermalfea/solver/results_writer.py` |
| Q26.1–3 | The guide: MkDocs; sources marked "not yet recorded" (see 2.2); illustrative tutorial inputs | `guide/`, `mkdocs.yml` |

Full text of each: `docs/OPEN_QUESTIONS.md`, under the question number.

---

## 5. Access and tools

### 5.1 Automatic publishing of the user guide (optional)

The guide is published by hand with `mkdocs gh-deploy`; see `docs/CONTINUE.md` §4.
Publishing from a GitHub Actions workflow would need one of:
- a git credential with the `workflow` scope, since a push of `.github/workflows/` is
  refused now;
- `gh auth login` on this machine.

Nothing is blocked; publishing by hand works.

**Files.** `mkdocs.yml`; `.github/workflows/` (would be new).

### 5.2 ffmpeg (optional)

MP4 export of animations needs ffmpeg on the PATH. It is not installed, so MP4 export has
never been tested; GIF export works. Install it if you want MP4, and the agent will add a
test.

**Files.** `src/thermalfea/post/export.py`; `src/thermalfea/gui/` (the export dialog).
