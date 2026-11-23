# What the agents need from the owner

State on 2026-11-22. This file lists everything that waits on you, the owner. It was
checked against the documents and the code by the main agent and, independently, by an
OpenAI Codex agent (`gpt-6.2-astra`, read-only). Its corrections were verified before
being adopted.

An interactive version with charts, links and a place to record your answers is
[`docs/owner-review.html`](docs/owner-review.html). Open it in a browser.

Each item says:
- what is needed;
- the options, and the recommendation where there is a choice;
- what it unblocks;
- the effort it will take you;
- the files to read.

Answer in any form, for example "D1: (c), N = 100". The agent records the answer in
`docs/OPEN_QUESTIONS.md`, changes `docs/theory.md` or `docs/data-model.md` where needed
(an agent may not do that on its own; CLAUDE.md rules 2, 3 and 6), builds the task, and
removes the item from this file.

**Contents**
0. Suggested work sessions
1. Decisions that block tasks
2. Testing and evaluation that only a person can do
3. Release scope, holds and priorities
4. Confirmations of interim choices (block nothing)
5. Access and tools

---

## 0. Suggested work sessions

The effort figures are your active time only. They assume the reference book is at hand
and exclude the agents' work.

| Session | Items | Your time | Kind of work |
|---|---|---|---|
| A. Solver numerics | 1.1 D1, 1.2 D2, 1.3 D3 | 50–105 min | Study and approve; these block three tasks |
| B. Quick approvals | 1.4 D6, 1.5 Q27.3, 1.6 D9, 1.7 D10 (packaging), 1.10 D7, 1.11 D8, 1.12 D13, 1.9 D4 (interim) | 45–90 min | Mostly yes/no |
| C. Release scope | 3.1 release scope, 3.2 holds, 3.3 order, 3.4 3D | 15–30 min | Direction |
| D. In the window | 2.1 M8.G | 60–120 min | Hands-on, with the friction log |
| E. With the reference book | 2.2 M11.1, plus 1.8 D5 (signed range) and Q17.2 | 2–4 h | Checking values and sources |
| F. When convenient | 1.13 D12, section 4, 1.7 licence, 2.3 visualisation | 1.5–3 h | Design choices and confirmations |

Session A first: its answers unblock M11.17, M11.18 (item 2.1-3) and M11.19. Book sessions D
and E early, because each needs a long uninterrupted stretch.

---

## 1. Decisions that block tasks

The options and the evidence for D1–D13 are in `docs/review-2026-11-21-evaluation.md` §4
and in `docs/OPEN_QUESTIONS.md` Q29. The review itself is `REVIEW-2.md`.

### 1.1 D1: convergence at equilibrium (Theory §5) — blocks M11.17 — 15–30 min, study

**Problem.** Newton's test is ‖r‖ ≤ rtol · F_ref, with
F_ref = max(‖F‖₂, ‖K T‖₂, 1e-12) and rtol = 1e-6.
- At a uniform temperature, K T is zero up to round-off, because the conduction matrix
  annihilates a constant field.
- In a radiation-only model F is zero too: the radiation is in the residual-only part
  r_extra, not in F.

So F_ref falls to round-off, and so does the allowance. Reproduced: radiation to 300 K,
started at 300 K, ran 30 iterations with the residual at 40–64 % of F_ref. The run ended
with "no convergence", although the temperature change was 7e-11 K, far below ttol =
1e-4 K. The answer was right and the solver refused it.

**Options.**
- **(a)** Add ‖|K|·|T|‖₂ to F_ref; the start-up check in `transient.py` already uses it.
  Simple, but it loosens the test on every problem. The allowance then grows with the
  absolute temperature level, not with the heat flows: raising a body from 300 K to
  1000 K triples it although the conducted heat is unchanged. That is Codex's objection,
  and it is correct.
- **(b)** Also accept when the temperature change is below `ttol` and the residual is
  below an absolute floor in watts. Needs a floor value from you.
- **(c) Recommended (Codex, agreed).** Keep the physical relative test and `ttol`, and add
  a round-off floor: also accept when the residual is below N · ε times the magnitude of
  the assembled terms, ‖|K||T|‖ + ‖F‖ + ‖r_extra‖, on the free rows. ε is the machine
  precision, about 2.2e-16. The floor matters only when the reference has collapsed to
  round-off. **It needs the factor N from you**: a small multiple of machine precision,
  such as 10, 100 or 1000. Applies to steady and transient solves.

**Files.**
- `docs/theory.md` §5;
- `src/thermalfea/solver/nonlinear.py` (`Assembled.reference`, the convergence test in
  `newton`);
- `src/thermalfea/solver/transient.py` (`StepSystem.reference`, the start-up `scale`);
- `src/thermalfea/physics/radiation_ambient.py` (radiation in `r_extra`);
- `REVIEW-2.md` 2.1-1.

### 1.2 D2: stream fluid rows when θ < 1 (Theory §6, §9.1) — blocks item 2.1-3 of M11.18 — 20–45 min, study

**Problem.** Stream fluid nodes have no heat capacity, so their equations g_d = 0 are
algebraic. With the θ-method, g_d(n+1) = −(1 − θ)/θ · g_d(n). If a step starts with an
imbalance in the fluid equations, it:
- alternates for ever at θ = 0.5;
- halves each step at θ = 2/3.

A fresh run starts in balance, or takes a θ = 1 first step. A restart skips that step
(Q25.2), and its fluid state can be out of balance after the flow or the loads were
changed between the runs. Shown by the recurrence; not yet reproduced end to end.

**Options.**
- **(a) Recommended.** Treat the rows without capacitance (the fluid rows) fully
  implicitly, θ = 1, whatever θ the solid uses. Apply it in both the linear and the
  Newton paths. The solid keeps its second-order accuracy. **Add (Codex):** on a restart,
  first re-solve the fluid nodes for the stored wall temperatures and the new data, then
  rebuild g(n). Otherwise the first step's energy balance carries the old imbalance,
  (1 − θ)(Q_n − H_n).
- **(b)** On a restart, take one θ = 1 step for the whole system when the stored state is
  not in balance. Simpler, but it does not cover other causes.

**Files.**
- `docs/theory.md` §6 and §9.1;
- `src/thermalfea/solver/transient.py` (`StepSystem`, `initial_state`, `solve_transient`);
- `src/thermalfea/flow/stream.py`;
- `src/thermalfea/post/energy.py` (step energy balance);
- `docs/OPEN_QUESTIONS.md` Q14, Q25.2;
- `REVIEW-2.md` 2.1-3.

### 1.3 D3: the step-size error estimate (Theory §6.1) — blocks M11.19 — 15–30 min, study

**Problem.** After a fast change of a prescribed temperature the controller takes many
small steps. Reproduced with a 100 K rise over 1 ms, against a constant load:

| Load | Steps stored | Rejected |
|---|---|---|
| Constant load | 22 | 1 |
| 100 K rise over 1 ms | 70 | 15 |

The smallest step fell to about 1e-6 s; it did not reach `dt_min`. There are two causes:
- the error estimate and `max_dT_per_step` include the prescribed nodes, whose jump the
  predictor cannot follow;
- the predictor history is not restarted at a breakpoint.

Theory §6.1 gives no restart rule. The jump detector `_jumps` also:
- misses a jump that is continuous from the right;
- can misclassify a periodic load whose values agree at both ends of a step;
- has a probe t + 1e-8·Δt that rounds back to t when Δt/t is small.

**Recommended (both agents).** Yes, with Codex's safeguards:
- leave the prescribed DOFs out of the estimate and out of `max_dT_per_step`, handling a
  model with no free DOF;
- restart the predictor on the outgoing side of a physical breakpoint, but not of an
  output time;
- keep a change limit on the free solid temperatures for the first step after the
  restart, so that skipping the predictor cannot miss a fast solid response;
- fix the `_jumps` defects.

**Files.**
- `docs/theory.md` §6, §6.1;
- `src/thermalfea/solver/timestep.py` (`error_estimate`, `StepController`);
- `src/thermalfea/solver/transient.py` (`_jumps`, `mandatory_times`);
- `docs/OPEN_QUESTIONS.md` Q14, Q15;
- `REVIEW-2.md` 2.1-5.

### 1.4 D6: term results in the results file (Data §9) — blocks M11.28 — 10–20 min, yes/no

**Problem.** Two quantities are computed but never stored, so the window cannot show
them:
- the heat across each contact: `ContactTerm.results()` gives `contact_heat:<name>`;
- the mean h of each correlation load: `evaluator.py` gives `h_mean`.

The run layer collects only the flow providers' results. Stream `h_mean` is already
stored.

**Recommended.** Yes:
- store `Term.results()` in new groups of the results file;
- raise the schema version;
- show the values in the window;
- make the pump example read them instead of recomputing them.

**Note (Codex):** older files stay readable if the reader treats the new groups as
optional. But `post/results.py` refuses a *newer* schema version, so files written after
the change cannot be read by older copies of the program. Accept that, or keep the
version and add the groups as optional.

**Files.**
- `docs/data-model.md` §9;
- `src/thermalfea/solver/run.py` (where results are collected);
- `src/thermalfea/solver/results_writer.py`;
- `src/thermalfea/post/results.py` (schema check);
- `src/thermalfea/physics/contact.py` (`heat_across`, `results`);
- `src/thermalfea/convection/evaluator.py`;
- `examples/pump_closure/closure_model.py`.

### 1.5 Q27.3: the oscillation-warning sentence (Theory §6.1) — blocks M11.10 — 3–5 min, quick

**Corrected.** The oscillation warning is checked once, before the first step
(`transient.py`: `check_dt` before the loop; Q15.7). Later steps are never checked. The
sentence proposed in Q27.3 says the warning "applies … to steps chosen by the step
control". Approving it as written would therefore *add* warnings for later steps.

**Choose.**
- **(i) Recommended.** "The warning is checked once, for the first step, and is not
  logged when that step is the suggested Δt₀." This keeps today's behaviour and
  suppresses only the false warning.
- **(ii)** Also check every step chosen by the step control. This adds new warnings.

M11.10 is also on hold (3.2); release it at the same time.

**Files.**
- `docs/theory.md` §6.1;
- `docs/OPEN_QUESTIONS.md` Q15.7, Q27.3;
- `src/thermalfea/solver/transient.py`;
- `src/thermalfea/physics/timescales.py` (`warn_if_oscillation_likely`);
- `src/thermalfea/solver/compile.py` (the `check_dt` hook).

### 1.6 D9: contradictions in the documents (with Q11) — needed for M11.6 — 10–20 min, mostly yes/no

1. **Sign of heat flows.** Theory §7 says a boundary heat flow is positive *out of* the
   body. The code, Q11 and the guide all use positive *into* the body. Recommended:
   change Theory §7 to "positive into", reversing the sign of its four boundary
   formulas. The magnitudes are unchanged.
2. **Q11, second half: the scale of the relative imbalance.** When one fixed-temperature
   condition both supplies and removes all the heat, the net flows cancel. The
   denominator therefore also includes the heat through the prescribed nodes, summed node
   by node. Confirm. Note that a contact's heat is internal and has its own direction,
   from the lower to the higher region id.
3. **Data §8 and §9 are out of date.**
   - `/fluid/<i>` and `/reactions/<i>` are numbered, with the name in an attribute.
   - Data §8 lacks `CorrelationConvection.params` and `Stream.h_override`.

   Recommended: bring them up to date.
4. **Theory §6.1 says the suggested Δt₀ is "shown in the GUI".** It is logged, and the
   log appears in the window's Messages panel, but nothing shows it before the solve.
   Choose: reword to "logged (shown in the Messages panel)", or add a task to show it
   before solving.
5. **Q20.1 and `docs/handover.md` say the providers are updated "before every
   assembly".** Since M11.20 they are updated once per Newton iterate. An agent can
   correct these records if you agree.

`thermalfea export` in PLAN.md has moved to 1.12.

**Files.**
- `docs/theory.md` §6.1, §7;
- `docs/data-model.md` §8, §9;
- `docs/OPEN_QUESTIONS.md` Q11, Q17.1, Q18.1, Q20.1;
- `docs/handover.md`;
- `src/thermalfea/post/reactions.py`.

### 1.7 D10: packaging and licence — M11.30 and the release — 5–10 min (packaging), 20–60 min (licence)

1. **Licence.** The repository has no licence file. Without one there is no explicit
   permission for others to use, copy or change the code. Choose one, for example MIT,
   BSD-3-Clause, Apache-2.0 or GPL-3.0, or say that it stays proprietary.
2. **pandas.** It is in the core dependencies for the pump showcase only (added
   2026-11-20 at your request). Recommended: move it to an optional extra `examples`.
3. **Duplicate images.** Twelve showcase images (4.2 MB) are stored twice:
   - seven in `examples/pump_closure/showcase/figures/` and five in
     `examples/pump_closure/out/`;
   - again in `guide/examples/img/`, because MkDocs publishes only files inside `guide/`.

   Recommended: keep both copies.
4. **README.** There is none at the root. Should an agent write a short one: what the
   program is, how to install it, and a link to the guide?

The other M11.30 work (the Pillow declaration, the `thermalfea-gui` entry point, the
layer guards, the guide wording) needs no decision.

**Files.**
- `pyproject.toml`;
- `LICENSE` and `README.md` (both new);
- `guide/examples/img/`;
- `guide/examples/pump-closure.md`.

### 1.8 D5: inclined natural convection beyond 90° — 2–5 min (guard) + range in session E

**Problem.** For |θ| > 90°, g cos θ < 0, so Ra < 0 and the correlation's sixth root
returns NaN:
- +100° gives NaN together with a validity warning;
- −100° gives NaN with no message, because the validity check is one-sided (≤ 60°).

Theory §8 says only "θ ≤ 60°".

**Needed.**
1. **Now:** approve a hard check that refuses a non-finite angle or |θ| > 90° before
   evaluating, and points to the horizontal-plate correlations near 90°. Recommended.
2. **In session E**, from the source text:
   - is the validity range symmetric, |θ| ≤ 60°?
   - which face is the heated one?

   Until then the 60° bound stays as written.

**Files.**
- `docs/theory.md` §8;
- `src/thermalfea/convection/correlations.py` (formula, about line 208; validity bound,
  about line 628);
- `src/thermalfea/convection/evaluator.py` (cos θ, about line 141; warnings, about line
  287);
- `src/thermalfea/convection/correlation_info.py` (displayed text);
- `REVIEW-2.md` 2.1-10.

### 1.9 D4: network near zero pressure drop (Theory §9.2) — 5 min (interim) / 30–60 min (remedy)

**Problem.** A loss branch has a conductance proportional to 1/√|Δp| as Δp → 0, and the
relative-change test treats a tiny branch like a main one. A bridge out of balance by
1e-7 stops at the 200-iteration cap. Mass is still conserved at the nodes, because the
flows come from the continuity solve.

**Options.**
- **(a) Recommended now.** A clear error naming the worst branch, its pressure drop, both
  flow estimates, and the largest continuity residual.
- **(b) Later.** One of:
  - a mixed absolute and relative flow test, which needs a justified absolute scale;
  - a coupled pressure–flow formulation that uses Δp = R ṁ|ṁ| directly.

  Changing the physical law near Δp = 0 (regularisation) would need a justified width.

**Files.**
- `docs/theory.md` §9.2;
- `src/thermalfea/flow/network.py`;
- `docs/OPEN_QUESTIONS.md` Q19;
- `REVIEW-2.md` 2.1-7.

### 1.10 D7: functions that depend on position (Data §1) — 5–10 min, yes/no

**Problem.** A total load in watts (`HeatPower`, `HeatFlow`) given as a function of x or
y is evaluated at the origin, with no message.

**Recommended.** Add a read-only attribute `depends_on_position` to the `Function`
protocol, next to `depends_on_T`, and refuse such a function for a total load. It is an
addition to a Data-model interface, so it needs your approval.

**Files.**
- `docs/data-model.md` §1;
- `src/thermalfea/core/functions.py`;
- `src/thermalfea/physics/body_loads.py`;
- `src/thermalfea/physics/surface_loads.py`;
- `src/thermalfea/model/validate.py`.

### 1.11 D8: `api.solve` without a built geometry — 5–10 min, yes/no

**Problem.** `api.solve(model, mesh)` runs `validate()` only when `built=` is passed,
which is documented in Q12.1. Without it, the compiler's guards still catch some errors,
but not all.

**Recommended.** Without `built`, run the checks that need only the model: materials,
settings, loads and streams. The alternative is to keep the documented skip.

**Files.**
- `src/thermalfea/api.py` (`solve`);
- `src/thermalfea/model/validate.py`;
- `src/thermalfea/solver/compile.py`;
- `docs/OPEN_QUESTIONS.md` Q12.1.

### 1.12 D13: scope — new commands and API exposure — 0–3 min

The review suggests:
- new commands `thermalfea validate`, `summary` and `export`;
- exposing the post-processing helpers in `api`.

PLAN.md also lists a `thermalfea export` command that does not exist. All of this is
treated as covered by your "no scripting" hold and stays excluded unless you say
otherwise. Choose: keep it excluded, and drop the `export` line from PLAN.md; or name
the commands you want as tasks.

**Files.**
- `src/thermalfea/cli.py`;
- `src/thermalfea/api.py`;
- `PLAN.md`;
- `REVIEW-2.md` §4.

### 1.13 D12: design choices that can wait — 30–60 min in all, by topic

Until you answer, the current behaviour stays.

1. **Heating flag.** One flag per stream (now; M11.21 fixed how it is computed) or one
   per cell, for Dittus–Boelter.
2. **Duct validity warnings in the stream solver.** There are none now. The HTC
   calculator already shows them.
3. **Selections:**
   - should matching after a rebuild also use the bounding box? (Data §5 names only the
     centre and the measure);
   - what should happen when two stored fingerprints resolve to the same current entity?
4. **Transforms:**
   - should `Transform(copy=False)` move the points of the shape?
   - should points and curves be transformable, and usable by a Line?
5. **User fluids.** Fluids in the user library are loaded, but `library.fluid()` searches
   only the built-in ones. Make them usable?
6. **Point loads at a contact (Q22.5).** A fixed temperature on a point at the end of a
   contact curve fixes only the side of the lower region id. Keep that, or fix both
   sides?
7. **Tolerances in `solver/run.py`.** They decide when an output time matches and
   whether a run can be continued. Confirm their meaning.
8. **Embedded points and curves (Q5).** A free point or curve drawn inside a surface is
   removed, not embedded in the mesh. Do you want embedding, for a point load or a probe
   line?
9. **Pick mode.** "Pick in viewport" for a fixed temperature starts in Point mode, not
   Curve. Check this in M8.G (walkthrough §4, item 2).

**Files.**
- `docs/review-2026-11-21-evaluation.md` §2.2 and §4 item 12;
- `src/thermalfea/model/selections.py`;
- `src/thermalfea/materials/library.py`;
- `src/thermalfea/solver/run.py`;
- `docs/OPEN_QUESTIONS.md` Q5, Q22.5.

---

## 2. Testing and evaluation that only a person can do

### 2.1 M8.G human gate: build V-10 and V-17 in the window — 60–120 min

No person has used the program on a real screen; every GUI test runs offscreen. The
steps:
1. Start the program with `.venv\Scripts\python.exe -m thermalfea.gui.app`.
2. Follow `docs/gui-walkthrough.md` to build V-10 and V-17 from an empty model, and
   solve both.
3. Fill in walkthrough §5:
   - the friction log: step, what you did, what happened, severity (blocker / slows me
     down / cosmetic), and a suggested change;
   - minutes per case;
   - the answer for each case and whether it is inside tolerance: V-10 within 0.15 °C,
     V-17 within 2e-3.
4. Confirm or dismiss the eight known frictions in walkthrough §4.

Changed since the walkthrough was written: M10 (contacts, DXF, units, restart), M11.24
(colour bar) and M11.25 (New, Open, remesh, closing the solve dialog). The agents turn
the log into tasks.

**Files.**
- `docs/gui-walkthrough.md` (§4 and §5 especially);
- `docs/verification.md` (V-10, V-17);
- `guide/getting-started.md` and `guide/tutorials/`;
- `guide/limitations.md`.

### 2.2 M11.1 human task: properties and correlations against a reference text — 2–4 h

Spot-check the property tables, and check every correlation and validity range, against
a heat-transfer text such as Incropera, *Fundamentals of Heat and Mass Transfer*. Record
the source and the edition of each. Until this is done the guide says "source not yet
recorded", and Plan §6 item 7 is not met.

Take these to the same session:
- **Air.** The documents say "1 atm", but the densities match 1 bar (D11). Which is
  intended?
- **Water.** The table has only 5 points. Is linear interpolation between them accurate
  enough?
- **D5, inclined plate.** The signed validity range and which face is the heated one
  (1.8).
- **Q17.2, horizontal plates.** The characteristic length is the selection length, or
  area/perimeter?
- **Citations.** Only those the theory names are recorded so far: Churchill–Bernstein,
  Churchill–Chu, Gnielinski, Dittus–Boelter and Churchill 1977.

An agent can prepare a checklist of every value with its file and line; ask for it.

**Files.**
- `docs/data-model.md` §6;
- `docs/theory.md` §8, §8.1;
- `src/thermalfea/materials/data/solids.json` and `fluids.json`;
- `src/thermalfea/convection/correlations.py` and `fluid_props.py`;
- `guide/correlations.md` and `guide/materials.md` (generated);
- `docs/OPEN_QUESTIONS.md` Q17, Q26.2.

### 2.3 Visualisation testing, and the pump example — 30–60 min; optional

1. **Visualisation.** You planned to test it over more kinds of boundary condition
   (M5.G, 2026-11-16). MP4 export has never succeeded: ffmpeg is not installed. The error
   when it is missing is tested; see 5.2.
2. **Pump example (optional).** All its inputs are marked illustrative. If it should
   represent a real design, supply the dimensions, materials, six contact conductances,
   heat-up history and fluid temperatures. The inputs are indexed in
   `examples/pump_closure/README.md`.

**Files.**
- `src/thermalfea/post/plots.py`;
- `src/thermalfea/post/export.py`;
- `examples/pump_closure/`;
- `guide/examples/pump-closure.md`.

---

## 3. Release scope, holds and priorities — 15–30 min

### 3.1 What the first release must contain

Plan §6 criterion 1: every case in `docs/verification.md` passes. But the cases for the
held features cannot run:
- V-22a–d, V-23 and V-24 need M9, enclosure radiation;
- V-36 needs M10.2, phase change.

Plan §5 also says the first usable release is M0–M8, and Plan §1 allows the axisymmetric
view factors (M9.5) to ship after version 1. **Choose:** build M9 and M10.2 before the
release, or exclude those cases from version 1, stated in the guide's limitations.

**Files.** `PLAN.md` §1 (the note on M9.5), §5 and §6; `docs/verification.md`;
`guide/limitations.md`.

### 3.2 Work on hold

| Task | What | Files |
|---|---|---|
| M9.1–M9.5 | Enclosure radiation (M9.5's quadrature orders are chosen and tested when it is built) | `docs/theory.md` §10, `docs/tasks.md` M9 |
| M10.2 | Phase change (V-36) | `docs/theory.md` §12 |
| M10.5 | Self-contained HTML report | `docs/tasks.md` M10.5 |
| M11.7 | Axisymmetric choice in the Analysis Settings panel | Q27.1 |
| M11.8 | Display fixes: an unset mass flow, the cross-section in the HTC calculator, the "steady state" label | Q26.4 (b), (c), (f) |
| M11.9 | A dialog for new correlation and radiation loads | Q27.2 |
| M11.10 | No false oscillation warning (needs 1.5) | Q27.3 |
| Scripting | Model-as-script export, `api.add_*`, sweep helpers, public matrices | your instruction |

### 3.3 Order of the remaining work

These need no decision.
- **Default order:**
  1. M11.12–M11.16 (already directed by you);
  2. M11.23, validation (its D5, D7 and D8 parts follow your answers);
  3. M11.26, meshing;
  4. M11.27, inputs and outputs;
  5. M11.29, GUI fixes;
  6. M11.30, packaging.
- **Not started:**
  - M11.2, the verification report;
  - M11.3, performance;
  - M11.5, the Windows installer.

Say "continue" or give another order.

### 3.4 3D

The estimate given on 2026-11-21 was 35–55 tasks, in three phases:
1. headless 3D, viewed in ParaView;
2. a 3D window;
3. streams and enclosure radiation in 3D.

Plan it as milestone M12, or not yet? See `docs/CONTINUE.md` §7.

---

## 4. Confirmations of interim choices (block nothing)

Each choice is in use and tested. Confirm it, or say what to change.

| Question | The choice made | Where |
|---|---|---|
| Q1 | `Material(name, k, rho, cp, *, k2=None, phase_change=None)`: `k2` and `phase_change` keyword-only | `src/thermalfea/materials/` |
| Q14 | A start out of equilibrium with the loads counts as a discontinuity: θ = 1 on the first step | `src/thermalfea/solver/transient.py` |
| Q17.2 | The characteristic length of horizontal plates is the selection length (take to session E) | `src/thermalfea/convection/` |
| Q18.2 | One c_p per stream, at the inlet temperature | `src/thermalfea/flow/stream.py` |
| Q20.2–8 | Initial fluid temperatures marched from the inlet; one stream per duct branch; reversed flow refused; the enthalpy heat flow; the `/fluid` layout; the V-29 tolerance; symmetry only a hint | `src/thermalfea/flow/` |
| Q21.1–6, 8–12 | GUI: what an edit makes out of date; pseudo-dimensions for nodes and elements; picking rules; pasting tables; tree actions; booleans; threads; result objects as view state | `src/thermalfea/gui/` |
| Q22.1–4, 6–7 | Contact: split at compile time; the duplication rule; T-dependent conductance refused; the geometry factor from the lower region; the reported heat; the "Contacts" node | `src/thermalfea/core/contact_split.py` |
| Q23.1–5 | DXF: join tolerance; ignored and refused entities; nesting; `$INSUNITS` not read; arcs split at 120° | `src/thermalfea/geometry/dxf.py` |
| Q24.1–6, 8 | Units: one unit per quantity; the SI (mm) and US customary presets; new quantities velocity, area and angle; expressions evaluated in SI; what stays SI only (Transform parameter editor, HTC calculator, solve dialog, solver messages, correlation parameters, CSV/VTU export, `api.summary`); results shown in their file's units until Units is used; the chart CSV follows the display units | `src/thermalfea/core/units.py` |
| Q25.1–3, 5–6 | Restart: how it is asked for, what matches an uninterrupted run, automatic stepping, the `last_step` attribute | `src/thermalfea/solver/run.py` |
| Q26.1, 3 | The guide is MkDocs; the tutorial inputs are illustrative | `guide/` |
| **All other entries** | Q2, Q4, Q6–Q10, Q12, Q13, Q15, Q16, Q19 (earlier interim choices: model defaults, the selection `all`, the solver details, the step-controller details, the network convergence measure). Recommended: accept them as documented and list any exceptions | `docs/OPEN_QUESTIONS.md` |

Already settled, so there is nothing to confirm:
- Q3;
- Q25.4 (decided in Q28.1);
- Q29.14;
- the test edits recorded in Q23.6–7 and Q24.7;
- Q21.7 (a velocity unit exists since M10.4).

---

## 5. Access and tools (optional)

### 5.1 Automatic publishing of the user guide

The guide is published by hand with `mkdocs gh-deploy` (`docs/CONTINUE.md` §4). A GitHub
Actions workflow would need a git credential that may push `.github/workflows/`, that is,
one with the `workflow` scope. Signing in with `gh auth login` alone does not grant that
scope. Nothing is blocked.

### 5.2 ffmpeg

MP4 export needs ffmpeg on the PATH. GIF export works, and so does the error when ffmpeg
is missing. Install ffmpeg if you want MP4, and an agent will add a test that encodes a
file.

**Files.**
- `src/thermalfea/post/export.py`;
- `tests/unit/test_export.py`;
- `src/thermalfea/gui/chart_tools.py` (the animation export offers GIF).
