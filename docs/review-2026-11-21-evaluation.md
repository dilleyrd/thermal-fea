# Evaluation of the codebase review of 2026-11-21, and a plan

The review being evaluated is `REVIEW-2.md` (copied unchanged from the external tool's
`codebase_review.md`), written on 2026-11-21 against commit 353a3ca. It reports:
- 19 high-severity bugs;
- about 30 medium bugs and about 20 low ones;
- departures from Plan §7, and inconsistencies in the documentation and data;
- a list of enhancements.

Every claim was checked against the code. The checking was done on 2026-11-21 by the
main agent (the solver findings) and by three subagents (flow, geometry and validation;
the GUI; packaging and documentation). Throwaway scripts in the scratchpad reproduced the
findings marked *reproduced*; nothing in the repository was changed.

Verdicts:
- **Confirmed:** the defect is in the code as described.
- **Partly:** real, but narrower or rarer than stated.
- **Not confirmed:** the claim is wrong.

"Owner" marks a fix that needs the owner's decision, because it changes `docs/theory.md`,
a data-model signature or file layout, or a documented behaviour (CLAUDE.md rules 2, 3
and 6).

## 1. Overall assessment

The review is mostly accurate, and far broader than `REVIEW.md`.
- Of about 75 claims, about 55 are confirmed, about 15 are real but overstated, and 2
  are wrong.
- Not all of the 19 "high" items are high:
  - **Serious in normal use:** 9 of them — 2.1-1, 2, 3, 5, 8, 9a, 11, 14 and 15.
  - **Real but reached only in edge cases:** 2.1-4, 6, 7, 10, 12, 13a, 16, 17 and 19.
- Where the review is wrong or overstated:
  - **"Three identical .h5 files":** wrong. They have the same size but different
    contents.
  - **2.2 plots:** "decompresses the whole mesh per step" is wrong, because the mesh is
    cached; the cited line is also wrong (`plots.py:905`, not 451).
  - **2.2 export, 0-step files:** they already raise `ModelError`; only `fps=nan` slips
    through.
  - **Pillow:** it is always installed through matplotlib, so the defect is a missing
    declaration, not a runtime failure.
  - **Transitive gmsh import in `gui/`:** true, but harmless; the GUI needs gmsh at
    start-up anyway.
  - **2.1-10:** the validity bound `(None, 60)` matches Theory §8 literally; the real
    defect is NaN beyond 90°.
  - **2.1-13a:** skipping validation when `built=None` is documented behaviour, not an
    accident.
  - **2.1-17 and 2.1-19:** need a bit-exact uniform field, or a thread still running
    10 s after the window closes.
- **Already known or already planned:**
  - the contact heat not stored (2.2);
  - the time-step guards (2.1-13f overlaps M11.12);
  - position-dependent sampling (2.1-13d overlaps M11.15);
  - time tolerances (2.3 overlaps M11.16);
  - the material-data checks (3.2 air and water, which are M11.1).
- **Section 4 (enhancements)** contains no defects. Most of it is new scope, and the
  owner has put two parts of it on hold: M9 and M10.2, and "API exposure", which falls
  under "no scripting".

## 2. Verdicts

### 2.1 High-severity items

| ID | Claim | Verdict | Evidence | Plan |
|---|---|---|---|---|
| 2.1-1 | Newton never converges at radiative equilibrium | **Confirmed, reproduced** | A steady model with radiation to 300 K, started at 300 K, hits the 30-iteration limit with residual 1.2e-11 W = 38 % of F_ref. F_ref is as written in **Theory §5**. | Owner (D1), then M11.17 |
| 2.1-2 | Restart crashes with a network-fed stream | Confirmed (by reading) | `initial_state(resume=True)` skips `initialize`, so `provider.update` never runs before `term_heats` (`run.py:314`); `StreamTerm.mass_flow` raises. | M11.18 |
| 2.1-3 | Quasi-steady fluid rows oscillate with θ < 1 after a restart | Plausible (by reasoning) | Fluid rows are algebraic. With θ = 0.5, a nonzero g_d(T₀) alternates sign each step. A restart skips the θ = 1 start-up step (Q25.4). | Owner (D2), then M11.18 |
| 2.1-4 | The pivot-ratio test rejects well-posed multi-scale systems | Plausible, not reproduced | `SINGULAR_PIVOT_RATIO = 1e-13` on an unscaled matrix (`linear.py:23, 77`). The ratio claimed needs extreme inputs. | Within M11.3: a test first |
| 2.1-5 | The error estimate includes prescribed DOFs and is not reset after a jump | **Partly, reproduced** | A fixed temperature rising 100 K over 1 ms takes 69 steps (15 rejected, Δt down to 1e-6 s), against 21 steps for a constant one. It does not collapse to dt_min. The estimate is as written in **Theory §6.1**. | Owner (D3), then M11.19 |
| 2.1-6 | Curved quadratic facets fail `Mesh.validate()` | Confirmed, edge case | It needs about one 90° Q8 element per quarter ring. It passes at a realistic size. | M11.26 |
| 2.1-7 | The network does not converge on a nearly balanced bridge with a loss branch | Confirmed, reproduced | A 1e-7 imbalance stops at 200 iterations. The scheme is the one written in **Theory §9.2**. | Owner (D4) |
| 2.1-8 | Hydraulics are re-solved inside line-search trials | **Confirmed** | `steady.py:52` calls `provider.update` on every assembly. **Theory §9.2** says "at most once per nonlinear iteration", so the code is wrong. | M11.20 |
| 2.1-9a | The stream heating flag counts cells without a wall as 0 K | **Confirmed** | `stream.py:356-359`. The Dittus–Boelter exponent flips from 0.4 to 0.3, which changes h by about 17 % for water. | M11.21 |
| 2.1-9b | One heating flag per stream | Partly | Theory §8.1 gives no rule per cell; this is a design choice. | Owner (D12) |
| 2.1-10 | Inclined natural convection gives NaN for \|θ\| > 90° | Confirmed, reproduced | g cos θ < 0 gives Ra < 0. The validity bound matches Theory §8, which is ambiguous about negative angles. | Owner (D5) |
| 2.1-11 | A DXF major arc (bulge > 1) is mirrored | **Confirmed, reproduced** | `dxf.py:~304` `copysign` loses the sign. For bulge 2 the centre is (1, +0.75) instead of (1, −0.75). | M11.22 |
| 2.1-12 | Structured meshing depends on the order of the list; a surface with a hole passes the side count | Confirmed (by reading) | `mesher.py:141-171`. The explicit divisions are applied first, so the conflict is between automatic counts. | M11.26 |
| 2.1-13a | `api.solve(model, mesh)` skips validation | Partly | It is documented: validation needs `built`. The gap is real. | Owner (D8) |
| 2.1-13b | Load dimensions are not checked (heat flux on a surface passes) | Confirmed | `validate.py:212` accepts `(0, 1, 2)` for every load that is not a fixed temperature. | M11.23 |
| 2.1-13c | The fluid lookup is case-sensitive in validation | Confirmed, reproduced | `"air"` passes `library.fluid()` but fails `validate()`. | M11.23 |
| 2.1-13d | `_sample` evaluates only t = 0 | Confirmed | Overlaps M11.15. | M11.15, extended |
| 2.1-13e | NaN material properties pass the positivity check | Confirmed, reproduced | Python's `min` ignores NaN, depending on its position. | M11.23 |
| 2.1-13f | dt_min, time_tol, rtol, ttol and max_dT_per_step are unchecked | Confirmed | Overlaps M11.12. | M11.12, extended |
| 2.1-13g | Streams, networks, initial conditions, contact conductance, empty selections and duplicate names are unvalidated | Confirmed | Data §8 lists only minimum checks, so these are extra checks. | M11.23 |
| 2.1-14 | The viewport shrinks about 20 % at every step change | **Confirmed, reproduced** | Width 0.98 → 0.78 → 0.63 → 0.50 → 0.40. The colour bar is removed without restoring `AXES_RECT`. | M11.24 |
| 2.1-15 | New, Open and Examples keep the old result objects, probes and panel | **Confirmed, reproduced** | `results_tools.py:340-365`. | M11.25 |
| 2.1-16a | A background build overwrites selections edited during the build | Confirmed (by reading) | `document.py:300-302`. | M11.25 |
| 2.1-16b | A build of model A is attached to model B | Partly | `set_built` marks it stale and rebuilds, so the wrong state is only transient. | M11.25 (minor) |
| 2.1-16c | A failed build drops the rebuild queued after it | Confirmed | `geometry_tools.py:378-383`. | M11.25 |
| 2.1-17 | "Manual" colour scale is impossible on a uniform field | Partly | It needs a bit-exact uniform field; a real step 0 worked. | M11.24 (minor) |
| 2.1-18 | Stale selection tags and chart nodes after a new mesh or model | Confirmed, reproduced (tags) | `viewport_mpl.py:986-990`, `chart_tools.py:449-456`. | M11.25 |
| 2.1-19 | `BackgroundTask.shutdown` does not park a thread that is still running | Confirmed, rare | It needs a task still running 10 s after the window closes. | M11.25 (minor) |

### 2.2 Medium items

Physics, solver and results I/O:
- **Material function of t or x silently evaluated at t = 0, x = 0:** confirmed,
  reproduced. Plan: M11.23.
- **Position-dependent `HeatPower`/`HeatFlow` silently evaluated at the origin:**
  confirmed. Rejecting it needs a flag for position dependence on `Function`, which is a
  Data-model signature. Plan: owner (D7).
- **`_jumps` detector:**
  - false positive when one step spans a whole period: partly;
  - misses a step that is continuous from the right: confirmed;
  - the probe underflows when Δt/t < 1e-8: confirmed;
  - two extra assemblies per step, each updating the flow provider: confirmed.

  Plan: M11.19 (and M11.20 for the provider updates).
- **Initial condition per region counted twice for a mixed T3 + Q4 region:** confirmed,
  but it only changes the weighting at an interface. Plan: M11.27.
- **`Term.results()` never written (contact heat, h_mean):** confirmed. This is the
  known contact-heat gap. Plan: owner (D6), then M11.28.
- **`/meta` overwritten before the first new step of a restart:** confirmed
  (`results_writer.py:350`). Plan: M11.18.
- **Contact split leaves `node_sets`/`point_nodes` unchanged:** confirmed. Which side
  owns a point load is a choice. Plan: owner (D12).
- **Contact split raises a raw `ValueError`:** partly; only on a hand-built inconsistent
  mesh. Plan: M11.27.
- **An L3 facet below 0 K at a Gauss point raises `ModelError` and aborts:** confirmed.
  Raising `ConvergenceError` instead lets the line search and the step cut-back handle
  it. Plan: M11.23.
- **Missing guards:**
  - negative velocity: confirmed;
  - power-law C or n: partly;
  - a load on the axis r = 0: partly;
  - a stream mass flow that depends on T: confirmed;
  - network roughness, K_minor and self-loops: confirmed.

  Plan: M11.23. Duct validity warnings: owner (D12).

Geometry, model and post-processing:
- **Selection matching ignores `bbox`:** partly. Data §5 specifies the centre and the
  measure only. Plan: owner (D12).
- **Duplicate matched tags:** confirmed, rare. Plan: owner (D12).
- **Ownership of points under `Transform(copy=False)`:** partly; the code comment says
  it is intended. Plan: owner (D12).
- **`curve_ends` lost after `Transform(copy=True)`:** partly. Plan: M11.26.
- **A Transform cannot feed a Line:** confirmed; transforming points and curves would be
  a new feature. Plan: owner (D12).
- **DXF duplicate segments and the nesting of fit-point splines:** confirmed. Plan:
  M11.22.
- **The quality report turns +inf into 1.8e308:** confirmed, reproduced. Plan: M11.27.
- **`Expression` accepts `1e309` and `10**400`:** partly; it returns inf rather than
  raising `OverflowError`. Plan: M11.27.
- **Serialization:**
  - JSON `true` accepted where 1 or 2 is expected: confirmed;
  - NaN and inf accepted: partly;
  - shallow copy before migration: latent;
  - NumPy scalars refused: confirmed.

  Plan: M11.27.
- **User fluids never read:** confirmed. Plan: owner (D12).
- **The CLI logs only errors by default, and `api.solve` drops validation warnings:**
  confirmed. Plan: M11.27.
- **Post-processing:**
  - `cached_property` goes stale after a re-solve: confirmed, low impact;
  - a sawtooth in `wall_temperature`: partly;
  - `wall_temperature` with no facets: confirmed;
  - commas in a BC name break the CSV header: confirmed;
  - the PVD file name is not escaped: partly;
  - `fps=nan`: partly;
  - `_selected_temperatures` is slow: partly.

  Plan: M11.27; the speed of `_selected_temperatures` goes to M11.3.

GUI:
- **Confirmed** (plan: M11.25 / M11.29):
  - renaming a stream leaves the network branch reference dangling (reproduced);
  - `add_stream` creates an in-plane stream with no path (reproduced);
  - the correlation panel offers `duct_internal`;
  - the selection editor updates its label even when Apply fails;
  - the selection editor does not sync the toolbar;
  - the selection editor does not end pick mode when the panel changes;
  - the new-stream dialog accepts an area or perimeter of 0;
  - the network number parser prints the SI bound and rejects a decimal comma;
  - the flow-results window: a dead CSV button, dropped save errors, leaked windows,
    charts never marked out of date;
  - the function editor's preview and Table limits.
- **Partly:** unit mixing, which only shows when the file's units differ from the
  document's.
- **A design choice:** the fixed-temperature selection starts in Point mode.

### 2.3 Low items

All are confirmed or partly confirmed:
- short-duration tolerances in `run.py`: with M11.16 (owner, D12, on the meaning);
- a 1-ULP time mismatch: with M11.19;
- `from_results` initial condition checks nodes only and has an empty-times crash:
  M11.18;
- `calculator.htc` logs although its docstring says it never logs: M11.27;
- NumPy scalars and `parse_xy_list` NaN: M11.27;
- duplicate tags in `api._select`: M11.27;
- reserved Windows file names and a raw `OSError` for a bad output directory (it fails
  before the solve, not after it as the review says): M11.27;
- streams in the CLI summary and counts in `info`: M11.27;
- GUI lifecycle gaps (solve dialog close; an empty refinement selection; units in the
  dialogs): M11.25 / M11.29;
- showcase hygiene (the "if False" is in a comment, not live code): M11.30.

### 2.4 Packaging, Plan §7 and documentation

| ID | Verdict | Plan |
|---|---|---|
| Pillow not declared | Partly (installed through matplotlib) | M11.30: declare it |
| pandas in the core dependencies | Confirmed. It was added at the owner's request on 2026-11-20 for the showcase. | Owner (D10) |
| 28.7 MB of committed outputs | Confirmed; committed at the owner's request | No change (D10) |
| Three identical .h5 files | **Not confirmed** (the sha256 hashes differ) | None |
| 12 images duplicated in `guide/examples/img/` | Confirmed (4.2 MB). MkDocs needs them inside `guide/`. | Owner (D10); recommend keeping them |
| No README or licence; no `gui-scripts` entry; `tests/gui/.gitkeep`; `.deepeval/` | Confirmed | M11.30 (the licence is the owner's choice, D10) |
| Plan §7 departures: timescales, mesher, export z, function z, `SURFACE_DIM`, positivity, results writer, validate `isinstance` | Confirmed, but latent until 3D. Rule 11 holds. | Fix with M12 if 3D goes ahead. Add the cheap guards to `test_layers.py` (M11.30). |
| Air labelled "1 atm" while the densities are at 1 bar; water table of 5 points | Confirmed (the interpolation errors are unchecked) | M11.1 (human task), D11 |
| Transform units text in the guide | Confirmed: the creation dialogs do convert | M11.30 |
| Heat-flow sign in Theory §7 ("positive out"), against Q11 and the guide ("positive in") | Confirmed | Owner (D9): Theory text |
| Data-model staleness (`/fluid/<i>` naming, `params`, `h_override`); `thermalfea export` in PLAN; Theory says the GUI shows Δt₀; "right-click Flow" | Confirmed (the last one only partly) | Owner (D9) for Data and PLAN; M11.30 for the guide wording |

## 3. Proposed tasks (M11.17–M11.30)

Ordered by priority. Tags: [A] cheap model, [B] mid model, [C] main model.

**Wrong results or crashes in normal use; no owner decision needed:**
- **M11.20 [B] Hydraulics once per nonlinear iteration** (2.1-8, and the provider updates
  inside `_jumps`). Theory §9.2 already says so. Tests: line-search trials do not change
  the network state; the hydraulic solve count per iteration is at most 1.
- **M11.24 [A] Viewport colour bar** (2.1-14, 2.1-17). Restore `AXES_RECT` when the
  colour bar is removed; allow Manual on a uniform field. Test: the axes position is
  stable over 10 step changes.
- **M11.22 [A] DXF arcs and loops** (2.1-11, duplicate segments, fit-spline nesting).
  Test: bulge 2 gives the correct centre and area.
- **M11.21 [B] Stream heating flag** (2.1-9a). Average over cells that have a wall only.
  Test: with 15 % of cells without a wall, the exponent stays 0.4.
- **M11.25 [B] GUI state on New, Open and remesh** (2.1-15, 16, 18, 19, and the solve
  dialog close). Tests: each reproduction, offscreen.
- **M11.18 [B] Restart, second part** (2.1-2; `/meta` written only after the first new
  step; a `from_results` initial condition uses the M11.11 mesh check and refuses an
  empty file). It also takes 2.1-3 once D2 is decided.

**Validation and guards:**
- **M11.12 [A], extended:** add `dt_min`, `time_tol`, `rtol`, `ttol` and
  `max_dT_per_step` > 0.
- **M11.15 [B], extended:** also sample time tables over the run (2.1-13d).
- **M11.23 [B] Validation coverage:**
  - the dimension of each load's selection, read from its registered `selection_dims`
    (this also removes the `isinstance` checks);
  - fluid names regardless of case;
  - NaN properties;
  - material functions must depend on T only;
  - streams, networks, initial conditions and contacts;
  - empty selections and duplicate names;
  - the runtime guards in convection and flow;
  - an L3 film temperature below zero raises `ConvergenceError`.

**Solver and time stepping (after the owner's decisions):**
- **M11.17 [C] Convergence at equilibrium** (D1): Theory §5, then the code.
- **M11.19 [B] Steps at fast changes** (D3 and the `_jumps` defects): Theory §6.1, then
  the code.

**Robustness, low priority:**
- **M11.26 [B] Meshing:** structured-surface order and holes (2.1-12), the orientation of
  curved facets (2.1-6), `curve_ends` after a Transform.
- **M11.27 [A] Inputs and outputs:** serialization, NumPy scalars, `Expression`
  finiteness, `parse_xy_list`, the quality inf, CSV and PVD escaping, `fps`, the
  flow-post edge cases, the docstring of `calculator.htc`. Also:
  - the CLI logs warnings by default and catches `OSError`;
  - `info` shows streams and contacts;
  - the CLI summary shows streams;
  - `api.solve` logs validation warnings;
  - duplicate tags;
  - the initial-condition weighting;
  - the contact `ValueError`.
- **M11.29 [A] GUI flow and selection fixes:** the confirmed medium GUI items.
- **M11.30 [A] Packaging and documentation corrections** that need no owner decision:
  - declare Pillow;
  - a `thermalfea-gui` entry point;
  - remove `.gitkeep`;
  - `test_layers.py` guards: only `solver/linear.py` may import `scipy.sparse.linalg`,
    and no `print` in `src/`;
  - the guide wording (Transform units, adding a stream);
  - showcase hygiene: close the file, drop the `print` calls.
- **M11.28 [B] Term results in the results file** (D6): contact heat and h_mean, shown
  in the program; the showcase then uses them.

M11.6 (release review) then depends on M11.7–M11.30.

## 4. Decisions for the owner (proposed Q29)

1. **D1, Theory §5 F_ref.** At equilibrium F_ref falls to round-off. Options:
   - (a) add a term that cannot cancel, such as ‖|K|·|T|‖, which the start-up check in
     `transient.py` already uses;
   - (b) declare convergence when ‖sΔT‖∞ ≤ ttol and ‖r_f‖ is below an absolute floor.

   Recommend (a).
2. **D2, fluid rows with θ < 1** (Theory §6). Options:
   - (a) always treat the fluid rows (no capacitance) fully implicitly;
   - (b) take a θ = 1 start-up step on a restart when the state is not in equilibrium.

   Recommend (a), which also covers changes of flow within a run.
3. **D3, error estimate** (Theory §6.1). Exclude prescribed DOFs from e and from
   max |ΔT|, and restart the predictor after a mandatory time where a table has a
   breakpoint. Recommend yes.
4. **D4, network iteration** (Theory §9.2). Regularise the loss-branch conductance near
   Δp = 0, or accept the current behaviour and give a clearer error. Recommend the
   clearer error now and regularisation later.
5. **D5, inclined natural convection.** Raise an error for |θ| > 90°. Is the validity
   range |θ| ≤ 60° (symmetric)? Theory §8 says only θ ≤ 60°.
6. **D6, results file** (Data §9). Store `Term.results()` (contact heat per contact,
   h_mean per correlation load) in new groups, with a schema-version step. Recommend yes;
   this closes the known contact-heat gap.
7. **D7, Function protocol** (Data model). Add a `depends_on_position` attribute so that
   loads given in watts can refuse a position-dependent expression. Recommend yes.
8. **D8, `api.solve` without `built`.** Run the checks that need only the model, or
   keep the documented skip. Recommend the model-only checks.
9. **D9, documents.**
   - Correct Theory §7 to "positive into the body" (Q11).
   - Correct Data §9 (`/fluid/<i>` and `/reactions/<i>` with `name` attributes) and
     add `CorrelationConvection.params` and `Stream.h_override`.
   - Drop `thermalfea export` from PLAN, or make it a task.
   - Drop "shown in the GUI" from Theory §6.1, or show Δt₀.
10. **D10, packaging.**
    - Move pandas from the core dependencies to an optional extra `examples`. It was
      added to the core on 2026-11-20 at the owner's request.
    - Choose a licence.
    - Keep the duplicate guide images (recommended) or link to the copies in `examples/`.
11. **D11, material data.** Air is "1 atm" in the documents but 1 bar in the data, and
    the water table has 5 points. Both belong to the human check M11.1.
12. **D12, design choices** that can wait:
    - a heating flag per cell;
    - duct validity warnings;
    - `bbox` in selection matching, and the policy for duplicate matches;
    - Transform semantics, and transforming points and curves;
    - user fluids;
    - ownership of point loads at a contact split;
    - the meaning of short-duration tolerances.
13. **D13, scope.** The review suggests `thermalfea validate`, `summary` and `export`
    commands, and exposing post-processing helpers in `api`. The "no scripting" hold
    probably covers these, so they are excluded unless the owner says otherwise.
    Section 4 (enhancements: physics, correlations, CAD operations, performance and 3D)
    is new scope, not defects. Performance belongs to M11.3, and 3D to a possible M12.
